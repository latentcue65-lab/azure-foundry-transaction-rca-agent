import copy
import runpy

from rca_agent.engine import investigate
from rca_agent.models import InvestigationRequest
from rca_agent.seed import sample_request

evaluate_run = runpy.run_path("scripts/evaluate.py")["evaluate_run"]


def test_recovery_evaluation_accepts_wording_but_requires_both_outcomes(settings):
    result = investigate(settings, InvestigationRequest(**sample_request("TX9005")))
    for summary in [
        "Transaction recovered after a timeout.",
        "A retry (PA2) completed successfully.",
        "The retry payment succeeded, allowing the checkout to recover.",
    ]:
        result["report"]["rootCause"]["summary"] = summary
        assert evaluate_run("TX9005", result)["passed"]
    missing = copy.deepcopy(result)
    missing["report"]["rootCause"]["evidenceIds"] = []
    assert not evaluate_run("TX9005", missing)["checks"]["bothAttemptOutcomesCited"]
    result["report"]["rootCause"]["summary"] = "A timeout occurred."
    assert not evaluate_run("TX9005", result)["checks"]["recoveryMentioned"]


def test_timeout_evaluation_rejects_unqualified_identified_status(settings):
    result = investigate(settings, InvestigationRequest(**sample_request("TX9003")))
    assert evaluate_run("TX9003", result)["passed"]
    result["report"]["rootCause"]["status"] = "identified"
    assert not evaluate_run("TX9003", result)["passed"]
