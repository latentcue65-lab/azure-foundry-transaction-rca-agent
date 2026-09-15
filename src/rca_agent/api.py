import json
import uuid
from importlib.resources import files

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from rca_agent.config import Settings
from rca_agent.engine import investigate
from rca_agent.models import RCA, InvestigationRequest
from rca_agent.seed import SCENARIOS, sample_request
from rca_agent.sources import ScopeError


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(
        title="Transaction RCA Agent",
        version="0.1.0",
        description="Single-user POC. Registered Foundry agent with local read-only tools. Replay mode is a deterministic test double.",
    )
    app.mount("/static", StaticFiles(directory=str(files("rca_agent").joinpath("static"))), name="static")

    @app.middleware("http")
    async def no_cache_investigations(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index():
        return HTMLResponse(
            files("rca_agent").joinpath("static/index.html").read_text(encoding="utf-8"),
            headers={
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'",
            },
        )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "mode": settings.mode,
            "dataReady": settings.db_path.exists(),
            "foundryConfigured": bool(settings.project_endpoint and settings.model_name),
            "llmEnabled": settings.mode == "foundry",
            "authentication": "local single-user POC",
        }

    @app.get("/api/scenarios")
    def scenarios():
        return [
            {"name": label, "request": sample_request(tx)}
            for tx, customer, label, _ in SCENARIOS
            if customer == "C1001"
        ]

    @app.post("/api/analyze", response_model=RCA)
    def analyze(request: InvestigationRequest, response: Response):
        try:
            run = investigate(settings, request)
        except ScopeError as exc:
            raise HTTPException(
                status_code=409 if exc.candidates else 404,
                detail={"message": str(exc), "candidates": exc.candidates},
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Investigation setup failed ({type(exc).__name__}); check local configuration",
            ) from exc
        response.headers["X-Investigation-Id"] = run["diagnostics"]["investigationId"]
        response.headers["X-RCA-Mode"] = settings.mode
        response.headers["X-RCA-Outcome"] = run["diagnostics"]["outcome"]
        response.headers["Cache-Control"] = "no-store"
        return run["report"]

    @app.get("/api/investigations/{investigation_id}")
    def get_run(investigation_id: uuid.UUID):
        path = settings.output_dir / f"{investigation_id}.json"
        if not path.is_file():
            raise HTTPException(404, "Investigation not found")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/api/investigations")
    def list_runs(
        customer_id: str = Query(min_length=1, max_length=80, alias="customerId"),
        limit: int = Query(default=20, ge=1, le=100),
    ):
        """Local single-user report history, filtered by customer; never return evidence in the index."""
        summaries = []
        for path in settings.output_dir.glob("*.json"):
            try:
                uuid.UUID(path.stem)
                run = json.loads(path.read_text(encoding="utf-8"))
                report, diagnostics = run["report"], run["diagnostics"]
                if report["customerId"] != customer_id:
                    continue
                summaries.append(
                    {
                        "investigationId": str(uuid.UUID(path.stem)),
                        "customerId": report["customerId"],
                        "transactionId": report["transactionId"],
                        "status": report["rootCause"]["status"],
                        "createdAt": diagnostics["createdAt"],
                        "mode": diagnostics["mode"],
                        "outcome": diagnostics["outcome"],
                    }
                )
            except (ValueError, KeyError, TypeError, OSError):
                # Evaluation reports, interrupted writes and damaged artifacts aren't runs.
                continue
        return sorted(summaries, key=lambda row: row["createdAt"], reverse=True)[:limit]

    return app
