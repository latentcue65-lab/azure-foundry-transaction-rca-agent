import copy
import json
import time
from datetime import datetime

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from rca_agent.backends import ReplayBackend, ToolCall, Turn
from rca_agent.engine import investigate
from rca_agent.models import InvestigationRequest, QueryArgs
from rca_agent.seed import sample_request
from rca_agent.sources import ScopeError, SourceReader, readonly_db, resolve_scope
from rca_agent.tools import ToolExecutor
from rca_agent.validation import application_schema, validate_report


@pytest.mark.parametrize(
    "transaction,status",
    [
        ("TX9001", "identified"),
        ("TX9002", "identified"),
        ("TX9003", "insufficient_evidence"),
        ("TX9004", "no_failure"),
        ("TX9005", "suspected"),
        ("TX9006", "insufficient_evidence"),
        ("TX9007", "insufficient_evidence"),
        ("TX9008", "identified"),
    ],
)
def test_real_three_source_pipeline(settings, transaction, status):
    result = investigate(settings, InvestigationRequest(**sample_request(transaction)))
    report, diagnostics = result["report"], result["diagnostics"]
    assert report["rootCause"]["status"] == status
    assert diagnostics["outcome"] == "completed", diagnostics["errors"]
    assert all(c["complete"] for c in diagnostics["sourceCoverage"].values())
    Draft202012Validator(application_schema(), format_checker=FormatChecker()).validate(report)
    assert len(report) == 6
    assert "no LLM" in diagnostics["backend"]
    assert {c["tool"] for c in diagnostics["toolCalls"]} >= {
        "read_file_events",
        "fetch_api_events",
        "query_database_events",
    }
    snapshot = json.loads((settings.output_dir / (diagnostics["investigationId"] + ".json")).read_text())
    assert all(
        e["event"]["customerId"] == "C1001" and e["event"]["transactionId"] == transaction
        for e in snapshot["evidenceSnapshot"]
    )
    if transaction == "TX9001":
        assert len(diagnostics["correlation"]["causalEdges"]) == 4
        assert report["failureFlow"][0]["event"] == "Checkout started."
        timestamps = [datetime.fromisoformat(s["timestamp"]) for s in report["failureFlow"]]
        assert timestamps == sorted(timestamps)
        assert "50.00" in report["rootCause"]["summary"] and "125.00" in report["rootCause"]["summary"]
        assert {e["source"] for e in report["evidence"]} == {"file", "api", "database"}
        assert any(c["arguments"].get("attemptId") == "PA1" for c in diagnostics["toolCalls"])
    if transaction == "TX9005":
        assert "recovered" in report["rootCause"]["summary"]
        assert len({e["traceId"] for e in report["evidence"]}) == 2


def test_customer_scope_and_ambiguity(settings):
    with pytest.raises(ScopeError, match="No authorized"):
        investigate(settings, InvestigationRequest(**sample_request("TX9999")))
    request = sample_request()
    request["transactionId"] = None
    with pytest.raises(ScopeError) as error:
        resolve_scope(settings, InvestigationRequest(**request))
    assert len(error.value.candidates) == 8
    assert not settings.output_dir.exists()


@pytest.mark.parametrize("fault", ["unavailable", "malformed"])
def test_api_failure_is_disclosed_never_replaced(settings, fault):
    settings = settings.model_copy(update={"mock_api_url": settings.mock_api_url + "?fault=" + fault})
    result = investigate(settings, InvestigationRequest(**sample_request()))
    assert result["report"]["rootCause"]["status"] == "suspected"
    assert not result["diagnostics"]["sourceCoverage"]["api"]["complete"]
    assert not any(e["source"] == "api" for e in result["report"]["evidence"])
    assert any("api" in x for x in result["report"]["rootCause"]["limitations"])


def test_pagination_requires_all_pages(settings):
    settings = settings.model_copy(update={"page_size": 1, "max_turns": 20})
    result = investigate(settings, InvestigationRequest(**sample_request("TX9005")))
    assert all(c["complete"] for c in result["diagnostics"]["sourceCoverage"].values())
    assert result["diagnostics"]["outcome"] == "completed"
    assert any(c["nextCursor"] for c in result["diagnostics"]["toolCalls"])


def test_budget_exhaustion_is_honest(settings):
    settings = settings.model_copy(update={"max_turns": 1})
    result = investigate(settings, InvestigationRequest(**sample_request()))
    assert result["diagnostics"]["outcome"] == "budget_exhausted"
    assert result["report"]["rootCause"]["status"] == "insufficient_evidence"


def test_direct_connection_is_read_only(settings):
    with readonly_db(settings) as db:
        with pytest.raises(Exception, match="readonly"):
            db.execute("DELETE FROM events")


def executor_with_evidence(settings):
    scope = resolve_scope(settings, InvestigationRequest(**sample_request()))
    executor = ToolExecutor(settings, scope, time.monotonic() + 30)
    for name in ["read_file_events", "fetch_api_events", "query_database_events"]:
        executor.execute(name, {"traceId": None, "attemptId": None, "cursor": 0})
    return executor


def test_tools_reject_arbitrary_scope_paths_and_sql(settings):
    executor = executor_with_evidence(settings)
    for name, args in [
        ("read_file_events", {"path": "../../.env"}),
        ("query_database_events", {"sql": "SELECT * FROM customers"}),
        ("fetch_api_events", {"url": "http://evil.invalid"}),
        ("read_file_events", {"traceId": "foreign", "attemptId": None, "cursor": 0}),
        ("get_evidence", {"evidenceIds": ["foreign:EV-1"]}),
        ("execute_shell", {"command": "whoami"}),
    ]:
        assert executor.execute(name, args)["status"] == "invalid_arguments"


def test_duplicate_ingestion_preserves_evidence_identity(settings):
    executor = executor_with_evidence(settings)
    count = len(executor.registry.records)
    executor.execute("read_file_events", {"traceId": None, "attemptId": None, "cursor": 0})
    assert len(executor.registry.records) == count


def test_malformed_file_is_partial_not_empty_success(settings):
    with settings.log_path.open("a", encoding="utf-8") as log:
        log.write("this is malformed\n")
    executor = executor_with_evidence(settings)
    assert not executor.coverage["file"]["complete"]
    assert executor.coverage["file"]["errors"]


def test_missing_trace_requires_recorded_attempt(settings):
    scope = resolve_scope(settings, InvestigationRequest(**sample_request()))
    reader = SourceReader(settings, scope)
    event = reader.read("file", QueryArgs(traceId=None, attemptId=None, cursor=0), time.monotonic() + 10)[
        "records"
    ][0][0]
    assert scope.permits(event.model_copy(update={"traceId": None}))
    assert not scope.permits(event.model_copy(update={"traceId": None, "attemptId": None}))
    assert not scope.permits(event.model_copy(update={"traceId": "unmapped"}))


@pytest.mark.parametrize("mutation", ["citation", "excerpt", "customer", "timestamp", "sequence"])
def test_rejects_fabricated_report_fields(settings, mutation):
    executor = executor_with_evidence(settings)
    backend = ReplayBackend(executor.scope)
    backend.coverage = executor.coverage
    backend.observations = {k: executor._observation(v) for k, v in executor.registry.records.items()}
    report = backend._report()
    validate_report(report, executor)
    if mutation == "citation":
        report["rootCause"]["evidenceIds"] = ["invented"]
    elif mutation == "excerpt":
        report["evidence"][0]["excerpt"] = "invented cause"
    elif mutation == "customer":
        report["customerId"] = "C2001"
    elif mutation == "timestamp":
        report["failureFlow"][0]["timestamp"] = "2026-09-14T12:00:00Z"
    elif mutation == "sequence":
        report["failureFlow"][0]["step"] = 2
    with pytest.raises(ValueError):
        validate_report(report, executor)


def test_model_errors_do_not_fall_back_to_replay(settings):
    class Broken:
        name = "simulated provider failure"

        def next(self, inputs, remaining):
            raise ConnectionError("private connection detail")

        def close(self):
            pass

    result = investigate(settings, InvestigationRequest(**sample_request()), lambda scope: Broken())
    assert result["diagnostics"]["outcome"] == "execution_failed"
    assert not result["diagnostics"]["toolCalls"]
    assert "private connection" not in json.dumps(result)


def test_schema_invalid_model_report_gets_only_one_repair(settings):
    class Invalid:
        name = "invalid report test double"

        def next(self, inputs, remaining):
            return Turn(text='{"customerId":"C1001"}')

        def close(self):
            pass

    result = investigate(settings, InvestigationRequest(**sample_request()), lambda scope: Invalid())
    assert result["diagnostics"]["modelTurns"] == 2
    assert result["diagnostics"]["outcome"] == "validation_failed"


def test_prompt_injection_tool_request_is_rejected(settings):
    class Malicious:
        name = "injection test double"

        def next(self, inputs, remaining):
            return Turn(calls=[ToolCall("evil", "read_file_events", '{"path":"../../.env"}')])

        def close(self):
            pass

    result = investigate(
        settings.model_copy(update={"max_turns": 2}),
        InvestigationRequest(**sample_request()),
        lambda scope: Malicious(),
    )
    assert all(c["status"] == "invalid_arguments" for c in result["diagnostics"]["toolCalls"])
    assert not result["report"]["evidence"]


def test_contract_copy_matches_published_schema():
    from pathlib import Path

    assert application_schema() == json.loads(Path("docs/contracts/rca-output.schema.json").read_text())


def test_flow_timestamp_accepts_equivalent_microsecond_precision(settings):
    executor = executor_with_evidence(settings)
    backend = ReplayBackend(executor.scope)
    backend.coverage = executor.coverage
    backend.observations = {k: executor._observation(v) for k, v in executor.registry.records.items()}
    report = backend._report()
    report["failureFlow"][1]["timestamp"] = "2026-09-14T10:00:00.070000Z"
    validate_report(report, executor)


@pytest.mark.parametrize(
    "field,value", [("fromTime", "2026-09-14T09:00:00"), ("toTime", "2026-09-12T00:00:00Z")]
)
def test_request_rejects_invalid_time_scope(field, value):
    request = copy.deepcopy(sample_request())
    request[field] = value
    with pytest.raises(ValueError):
        InvestigationRequest(**request)
