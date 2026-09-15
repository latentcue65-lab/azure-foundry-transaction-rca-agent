import json
import time

import httpx
from azure.ai.projects import AIProjectClient
from azure.core.credentials import AccessToken

from rca_agent.config import Settings
from rca_agent.foundry import FoundryBackend, definition


class FakeCredential:
    def get_token(self, *scopes, **kwargs):
        return AccessToken("synthetic-test-token", int(time.time()) + 3600)

    def close(self):
        pass


def test_registered_definition_uses_supported_sdk_shapes():
    settings = Settings(_env_file=None, model_name="test-deployment")
    agent = definition(settings).as_dict()
    assert agent["kind"] == "prompt"
    assert agent["model"] == "test-deployment"
    assert len(agent["tools"]) == 4
    for tool in agent["tools"]:
        assert tool["type"] == "function"
        assert tool["strict"] is True
        assert tool["parameters"]["additionalProperties"] is False
        assert set(tool["parameters"]["required"]) == set(tool["parameters"]["properties"])
    fmt = agent["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert set(fmt["schema"]["properties"]) == {
        "customerId",
        "transactionId",
        "rootCause",
        "failureFlow",
        "evidence",
        "recommendation",
    }


def test_real_sdk_serializes_agent_reference_and_tool_outputs_without_network():
    requests = []

    def transport(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path.endswith("/conversations"):
            return httpx.Response(
                200, json={"id": "conv_test", "object": "conversation", "created_at": 1, "metadata": {}}
            )
        assert request.url.path.endswith("/responses")
        if len(requests) == 2:
            output = [
                {
                    "id": "fc_1",
                    "type": "function_call",
                    "call_id": "call_test",
                    "name": "read_file_events",
                    "arguments": '{"traceId":null,"attemptId":null,"cursor":0}',
                    "status": "completed",
                }
            ]
        else:
            output = [
                {
                    "id": "msg_1",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": '{"sample":"response"}', "annotations": []}],
                }
            ]
        return httpx.Response(
            200,
            json={
                "id": f"resp_{len(requests)}",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "output": output,
                "model": "test-deployment",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 10,
                    "total_tokens": 20,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    settings = Settings(
        _env_file=None,
        project_endpoint="https://unit-test.services.ai.azure.com/api/projects/test",
        model_name="test-deployment",
        agent_version="7",
    )
    backend = FoundryBackend.__new__(FoundryBackend)
    backend.settings = settings
    backend.version = "7"
    backend.conversation_id = None
    backend.credential = FakeCredential()
    backend.project = AIProjectClient(endpoint=settings.project_endpoint, credential=backend.credential)
    backend.client = backend.project.get_openai_client(
        http_client=httpx.Client(transport=httpx.MockTransport(transport)), max_retries=0
    )
    try:
        first = backend.next([{"role": "user", "content": "Investigate"}], 20)
        assert first.calls[0].call_id == "call_test"
        second = backend.next(
            [{"type": "function_call_output", "call_id": "call_test", "output": '{"events":[]}'}], 20
        )
        assert second.text == '{"sample":"response"}'
        for _, body in requests[1:]:
            assert body["agent_reference"]["version"] == "7"
            assert body["agent_reference"]["name"] == settings.agent_name
            assert body["conversation"] == "conv_test"
            assert body["parallel_tool_calls"] is False
        assert requests[-1][1]["input"][0]["call_id"] == "call_test"
    finally:
        backend.close()
