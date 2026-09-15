import json
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

from jsonschema import ValidationError as SchemaValidationError

from rca_agent.backends import ReplayBackend
from rca_agent.config import Settings
from rca_agent.models import InvestigationRequest
from rca_agent.sources import resolve_scope
from rca_agent.tools import ToolExecutor
from rca_agent.validation import insufficient_report, validate_report


def investigate(
    settings: Settings, request: InvestigationRequest, backend_factory: Callable | None = None
) -> dict:
    started = time.monotonic()
    deadline = started + settings.deadline_seconds
    scope = resolve_scope(settings, request)
    executor = ToolExecutor(settings, scope, deadline)
    identifier = str(uuid.uuid4())
    if backend_factory:
        backend = backend_factory(scope)
    elif settings.mode == "replay":
        backend = ReplayBackend(scope)
    else:
        from rca_agent.foundry import FoundryBackend

        backend = FoundryBackend(settings, scope)
    turns, repairs, response_ids, usage, errors = 0, 0, [], [], []
    report = None
    outcome = "completed"
    inputs = [
        {
            "role": "user",
            "content": json.dumps({"scope": scope.describe(), "issueDescription": request.issueDescription}),
        }
    ]
    observed_chars = 0
    try:
        for _ in range(settings.max_turns):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Investigation deadline reached")
            turn = backend.next(inputs, remaining)
            turns += 1
            if time.monotonic() > deadline:
                raise TimeoutError("Investigation deadline reached")
            if turn.response_id:
                response_ids.append(turn.response_id)
            if turn.usage:
                usage.append(turn.usage)
            if turn.calls:
                inputs = []
                for call in turn.calls:
                    try:
                        arguments = json.loads(call.arguments)
                    except (ValueError, TypeError):
                        arguments = None
                    result = executor.execute(call.name, arguments)
                    output = json.dumps(result, default=str)
                    observed_chars += len(output)
                    if observed_chars > 180000:
                        raise TimeoutError("Model observation budget reached")
                    inputs.append({"type": "function_call_output", "call_id": call.call_id, "output": output})
                continue
            try:
                report = validate_report(json.loads(turn.text), executor)
                break
            except (ValueError, TypeError, KeyError, SchemaValidationError) as exc:
                # Validation messages name a contract rule only; they don't log raw model text.
                errors.append(f"Candidate rejected: {type(exc).__name__}: {str(exc)[:240]}")
                if repairs >= 1:
                    outcome = "validation_failed"
                    report = insufficient_report(
                        executor, "Model report failed application validation after one repair attempt."
                    )
                    break
                repairs += 1
                inputs = [
                    {
                        "role": "user",
                        "content": "The candidate failed application validation. "
                        "Check exact source excerpts/IDs, customer scope, source coverage, flow references and schema. "
                        "Return a corrected report; if evidence is incomplete, use a qualified status with limitations.",
                    }
                ]
        if report is None:
            outcome = "budget_exhausted"
            report = insufficient_report(executor, "Investigation model-turn budget was exhausted.")
    except Exception as exc:
        # Preserve honest diagnostics; provider failure must never switch to replay automatically.
        outcome = "budget_exhausted" if isinstance(exc, TimeoutError) else "execution_failed"
        errors.append(f"Investigation stopped: {type(exc).__name__}")
        report = insufficient_report(
            executor,
            f"Investigation stopped ({type(exc).__name__}); review run diagnostics and source availability.",
        )
    finally:
        backend.close()
    diagnostics = {
        "investigationId": identifier,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "mode": settings.mode,
        "backend": backend.name,
        "outcome": outcome,
        "elapsedMs": round((time.monotonic() - started) * 1000),
        "modelTurns": turns,
        "toolCalls": executor.calls,
        "sourceCoverage": executor.coverage,
        "correlation": executor.registry.correlation(),
        "scope": scope.describe(),
        "responseIds": response_ids,
        "conversationId": getattr(backend, "conversation_id", None),
        "agentVersion": getattr(backend, "version", None),
        "usage": usage,
        "errors": errors,
    }
    result = {"report": report.model_dump(), "diagnostics": diagnostics}
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    # Persist only authorized normalized records. Atomic replacement avoids partially readable runs.
    destination = settings.output_dir / f"{identifier}.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({**result, "evidenceSnapshot": executor.registry.export()}, indent=2), encoding="utf-8"
    )
    temporary.replace(destination)
    return result
