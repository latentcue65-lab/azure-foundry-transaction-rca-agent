import argparse
import json
import sys
from contextlib import nullcontext
from pathlib import Path

from rca_agent.config import Settings, ensure_azure_cli_on_path
from rca_agent.models import InvestigationRequest
from rca_agent.seed import sample_request, seed


def doctor(settings: Settings, live: bool = False) -> dict:
    result = {
        "mode": settings.mode,
        "databaseExists": settings.db_path.is_file(),
        "logFileExists": settings.log_path.is_file(),
        "foundryEndpointSet": bool(settings.project_endpoint),
        "foundryModelSet": bool(settings.model_name),
        "liveVerified": False,
    }
    if live:
        settings.require_foundry()
        ensure_azure_cli_on_path()
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        with DefaultAzureCredential() as credential:
            with AIProjectClient(
                endpoint=settings.project_endpoint,
                credential=credential,
                connection_timeout=5,
                read_timeout=20,
                retry_total=0,
            ) as project:
                deployments = list(project.deployments.list())
                result["modelDeploymentFound"] = any(d.name == settings.model_name for d in deployments)
                if not result["modelDeploymentFound"]:
                    raise ValueError("Configured model deployment was not found in this project")
                result["liveVerified"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description="Customer transaction RCA agent")
    commands = parser.add_subparsers(dest="command", required=True)
    seed_parser = commands.add_parser("seed", help="Create synthetic file, API, and SQLite fixtures")
    seed_parser.add_argument("--reset", action="store_true")
    mock = commands.add_parser("mock-api", help="Run the standalone mock HTTP API")
    mock.add_argument("--port", type=int, default=8091)
    server = commands.add_parser("serve", help="Start local API and interview UI")
    server.add_argument("--port", type=int, default=8000)
    server.add_argument("--mode", choices=["foundry", "replay"])
    server.add_argument(
        "--with-mock", action="store_true", help="Start bundled mock on an available loopback port"
    )
    demo = commands.add_parser("demo", help="Run a complete integration demo using a real local HTTP mock")
    demo.add_argument("--mode", choices=["foundry", "replay"], default="replay")
    demo.add_argument("--transaction", default="TX9001")
    analyze = commands.add_parser("analyze", help="Analyze a JSON request against the configured HTTP source")
    analyze.add_argument("--input", type=Path, required=True)
    analyze.add_argument("--mode", choices=["foundry", "replay"])
    commands.add_parser(
        "register", help="Create a named/versioned Foundry agent with tools and output schema"
    )
    check = commands.add_parser("doctor", help="Check configuration without displaying secrets")
    check.add_argument("--live", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if getattr(args, "mode", None):
        settings = settings.model_copy(update={"mode": args.mode})
    try:
        if args.command == "seed":
            print(json.dumps(seed(settings, args.reset), indent=2))
        elif args.command == "mock-api":
            from rca_agent.mock_api import serve_mock

            serve_mock(settings.data_dir, args.port)
        elif args.command == "register":
            from rca_agent.foundry import register

            print(json.dumps(register(settings), indent=2))
        elif args.command == "doctor":
            print(json.dumps(doctor(settings, args.live), indent=2))
        elif args.command in {"demo", "analyze"}:
            from rca_agent.engine import investigate
            from rca_agent.mock_api import running_mock

            if args.command == "demo" and not settings.db_path.exists():
                seed(settings)
            request = InvestigationRequest.model_validate(
                sample_request(args.transaction)
                if args.command == "demo"
                else json.loads(args.input.read_text(encoding="utf-8"))
            )
            context = running_mock(settings.data_dir) if args.command == "demo" else nullcontext(None)
            with context as endpoint:
                if endpoint:
                    settings = settings.model_copy(update={"mock_api_url": endpoint})
                result = investigate(settings, request)
            print(json.dumps(result["report"], indent=2))
            d = result["diagnostics"]
            print(
                f"Mode: {d['backend']} | outcome: {d['outcome']} | audit: {settings.output_dir / (d['investigationId'] + '.json')}",
                file=sys.stderr,
            )
            if d["outcome"] != "completed":
                return 2
        elif args.command == "serve":
            import uvicorn

            from rca_agent.api import create_app
            from rca_agent.mock_api import running_mock

            context = running_mock(settings.data_dir) if args.with_mock else nullcontext(None)
            with context as endpoint:
                if endpoint:
                    settings = settings.model_copy(update={"mock_api_url": endpoint})
                print(
                    f"Mode: {settings.mode}. Replay is a deterministic test double, not an LLM.", flush=True
                )
                uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(
            f"Operation failed ({type(exc).__name__}). Check Azure login, project permissions, model and source configuration.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
