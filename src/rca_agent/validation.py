import json
from datetime import datetime
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker

from rca_agent.models import RCA
from rca_agent.tools import ToolExecutor


def same_instant(left: str, right: str) -> bool:
    """Compare ISO-8601 timestamps by time, not rendering precision.

    Azure structured output can validly render the same UTC instant as `.070Z`
    or `.070000Z`. Evidence provenance still stays exact; this only validates a
    flow step's reference to its cited source event.
    """
    try:
        return datetime.fromisoformat(left.replace("Z", "+00:00")) == datetime.fromisoformat(
            right.replace("Z", "+00:00")
        )
    except ValueError:
        return False


def application_schema() -> dict:
    return json.loads(files("rca_agent").joinpath("rca_schema.json").read_text(encoding="utf-8"))


def validate_report(candidate: dict, executor: ToolExecutor) -> RCA:
    report = RCA.model_validate(candidate)
    Draft202012Validator(application_schema(), format_checker=FormatChecker()).validate(report.model_dump())
    scope, registry = executor.scope, executor.registry
    if report.customerId != scope.request.customerId or report.transactionId != scope.transaction_id:
        raise ValueError("Report customer/transaction does not match the request")
    ids = [e.evidenceId for e in report.evidence]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate evidence IDs in report")
    for e in report.evidence:
        if e.evidenceId not in registry.records or registry.records[e.evidenceId].evidence != e:
            raise ValueError("Evidence metadata or excerpt was invented/modified")
    for part in [report.rootCause, *report.failureFlow, *report.recommendation]:
        if len(part.evidenceIds) != len(set(part.evidenceIds)) or not set(part.evidenceIds) <= set(ids):
            raise ValueError("A citation is missing from the report evidence")
    if [s.step for s in report.failureFlow] != list(range(1, len(report.failureFlow) + 1)):
        raise ValueError("Failure flow step numbers must be sequential")
    for step in report.failureFlow:
        records = [registry.records[e] for e in step.evidenceIds]
        if step.service not in {r.event.service for r in records}:
            raise ValueError("Failure flow service is not present in its cited events")
        if step.timestamp is not None and not any(
            r.evidence.timestamp is not None and same_instant(step.timestamp, r.evidence.timestamp)
            for r in records
        ):
            raise ValueError("Failure flow timestamp is not present in its cited events")
    complete = all(c["complete"] for c in executor.coverage.values())
    if report.rootCause.status in {"identified", "no_failure"} and not complete:
        raise ValueError("A complete finding requires complete three-source coverage; qualify the finding")
    if registry.correlation()["conflictingAttempts"] and report.rootCause.status in {
        "identified",
        "no_failure",
    }:
        raise ValueError("Conflicting outcomes require a qualified finding with limitations")
    events = [registry.records[i].event for i in ids]
    if report.rootCause.status == "no_failure":
        if not any(e.eventType == "checkout.succeeded" for e in events):
            raise ValueError("No-failure requires positive checkout success evidence")
        if any(e.eventType == "checkout.failed" for e in events):
            raise ValueError("Report the historical failure/recovery rather than no_failure")
    # Canonical source facts always come from the application registry.
    return report.model_copy(update={"evidence": [registry.records[i].evidence for i in ids]})


def insufficient_report(executor: ToolExecutor, reason: str) -> RCA:
    return RCA.model_validate(
        {
            "customerId": executor.scope.request.customerId,
            "transactionId": executor.scope.transaction_id,
            "rootCause": {
                "status": "insufficient_evidence",
                "summary": "The investigation could not establish a supported root cause.",
                "evidenceIds": [],
                "limitations": [reason],
            },
            "failureFlow": [],
            "evidence": [r.evidence.model_dump() for r in executor.registry.ordered()],
            "recommendation": [
                {
                    "action": "Review the source coverage and retrieve the missing observations before concluding.",
                    "reason": reason,
                    "evidenceIds": [],
                }
            ],
        }
    )
