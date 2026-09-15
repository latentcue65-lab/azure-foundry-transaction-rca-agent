import hashlib
import json
import time
from importlib.resources import files
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    FunctionTool,
    PromptAgentDefinition,
    PromptAgentDefinitionTextOptions,
    TextResponseFormatJsonSchema,
)
from azure.identity import DefaultAzureCredential

from rca_agent.backends import ToolCall, Turn
from rca_agent.config import Settings, ensure_azure_cli_on_path
from rca_agent.models import RCA
from rca_agent.tools import provider_schema, tool_definitions

REGISTRATION = Path(".foundry-agent.json")


def definition(settings: Settings) -> PromptAgentDefinition:
    instructions = files("rca_agent").joinpath("prompts/investigator.txt").read_text(encoding="utf-8")
    return PromptAgentDefinition(
        model=settings.model_name,
        instructions=instructions,
        tools=[FunctionTool(**{k: v for k, v in tool.items() if k != "type"}) for tool in tool_definitions()],
        text=PromptAgentDefinitionTextOptions(
            format=TextResponseFormatJsonSchema(
                name="transaction_rca",
                schema=provider_schema(RCA.model_json_schema()),
                strict=True,
            )
        ),
    )


def definition_hash(settings: Settings) -> str:
    return hashlib.sha256(json.dumps(definition(settings).as_dict(), sort_keys=True).encode()).hexdigest()


def register(settings: Settings) -> dict:
    settings.require_foundry()
    ensure_azure_cli_on_path()
    with DefaultAzureCredential() as credential:
        with AIProjectClient(
            endpoint=settings.project_endpoint,
            credential=credential,
            connection_timeout=5,
            read_timeout=30,
            retry_total=0,
        ) as project:
            agent = project.agents.create_version(
                agent_name=settings.agent_name, definition=definition(settings)
            )
    metadata = {
        "name": agent.name,
        "version": agent.version,
        "model": settings.model_name,
        "projectEndpoint": settings.project_endpoint,
        "definitionHash": definition_hash(settings),
    }
    REGISTRATION.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


class FoundryBackend:
    name = "foundry (registered agent; real LLM)"

    def __init__(self, settings: Settings, scope):
        settings.require_foundry()
        ensure_azure_cli_on_path()
        self.credential = None
        self.project = None
        self.client = None
        self.conversation_id = None
        self.settings = settings
        self.version = settings.agent_version
        if not self.version and REGISTRATION.is_file():
            saved = json.loads(REGISTRATION.read_text(encoding="utf-8"))
            if (
                saved.get("projectEndpoint") == settings.project_endpoint
                and saved.get("name") == settings.agent_name
                and saved.get("definitionHash") == definition_hash(settings)
            ):
                self.version = saved["version"]
        if not self.version:
            raise ValueError(
                "Run rca register, or set FOUNDRY_AGENT_VERSION to the registered compatible version"
            )
        try:
            self.credential = DefaultAzureCredential()
            self.project = AIProjectClient(
                endpoint=settings.project_endpoint,
                credential=self.credential,
                connection_timeout=5,
                read_timeout=30,
                retry_total=0,
            )
            self.client = self.project.get_openai_client(timeout=90, max_retries=0)
        except Exception:
            self.close()
            raise

    def next(self, inputs: list[dict], remaining: float) -> Turn:
        started = time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Investigation deadline exhausted")
        if self.conversation_id is None:
            self.conversation_id = self.client.conversations.create(timeout=min(remaining, 30)).id
        remaining -= time.monotonic() - started
        if remaining <= 0:
            raise TimeoutError("Investigation deadline exhausted during conversation creation")
        # Tool-turn responses can take longer than a simple chat completion,
        # especially after several evidence payloads. Keep the request bounded
        # by the investigation deadline rather than an arbitrary 30-second cap.
        response = self.client.responses.create(
            input=inputs,
            conversation=self.conversation_id,
            extra_body={
                "agent_reference": {
                    "name": self.settings.agent_name,
                    "version": self.version,
                    "type": "agent_reference",
                }
            },
            parallel_tool_calls=False,
            max_output_tokens=12000,
            timeout=min(remaining, 90),
        )
        if response.status not in {"completed", None}:
            raise RuntimeError(f"Foundry response did not complete ({response.status})")
        calls = [
            ToolCall(i.call_id, i.name, i.arguments) for i in response.output if i.type == "function_call"
        ]
        if any(
            getattr(c, "type", None) == "refusal"
            for i in response.output
            for c in (getattr(i, "content", None) or [])
        ):
            raise RuntimeError("Foundry model refused the investigation")
        return Turn(
            calls=calls,
            text=response.output_text,
            response_id=response.id,
            usage=response.usage.model_dump() if response.usage else {},
        )

    def close(self):
        # Keep the cloud conversation for the interview audit. Explicit deletion is a separate lifecycle action.
        for client in [self.client, self.project, self.credential]:
            if client is not None:
                client.close()
