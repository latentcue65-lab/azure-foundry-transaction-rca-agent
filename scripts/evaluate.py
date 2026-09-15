"""Repeatable scenario evaluation. Never equate replay scores to LLM accuracy."""

import argparse
import json
import re
from datetime import datetime, timezone

from rca_agent.config import Settings
from rca_agent.engine import investigate
from rca_agent.mock_api import running_mock
from rca_agent.models import InvestigationRequest
from rca_agent.seed import sample_request

EXPECTATIONS = {
    "TX9001": {"identified"},
    "TX9002": {"identified"},
    "TX9003": {"insufficient_evidence", "suspected"},
    "TX9004": {"no_failure"},
    "TX9005": {"suspected", "insufficient_evidence"},
    "TX9006": {"insufficient_evidence"},
    "TX9007": {"insufficient_evidence"},
    "TX9008": {"identified"},
}


def evaluate_run(transaction: str, result: dict) -> dict:
    report, diagnostics = result["report"], result["diagnostics"]
    checks = {
        "completed": diagnostics["outcome"] == "completed",
        "findingStatus": report["rootCause"]["status"] in EXPECTATIONS[transaction],
        "allSourcesCovered": all(c["complete"] for c in diagnostics["sourceCoverage"].values()),
        "customerTransaction": report["customerId"] == "C1001" and report["transactionId"] == transaction,
    }
    if transaction == "TX9005":
        summary = report["rootCause"]["summary"].lower()
        checks["recoveryMentioned"] = bool(
            re.search(
                r"\brecover(?:ed|y)?\b|\bretry\b.{0,40}\b(?:succeeded|completed successfully)\b|\bsuccessful retry\b",
                summary,
            )
        )
        # Verify both outcomes are actually cited, not only a matching phrase.
        referenced = set(report["rootCause"]["evidenceIds"])
        flow_references = {i for step in report["failureFlow"] for i in step["evidenceIds"]}
        cited_events = [
            json.loads(e["excerpt"])
            for e in report["evidence"]
            if e["evidenceId"] in referenced & flow_references
        ]
        checks["bothAttemptOutcomesCited"] = all(
            any(e["eventType"] == kind and e["attemptId"] == attempt for e in cited_events)
            for kind, attempt in [("checkout.failed", "PA1"), ("checkout.succeeded", "PA2")]
        )
    return {
        "transactionId": transaction,
        "passed": all(checks.values()),
        "checks": checks,
        "status": report["rootCause"]["status"],
        "investigationId": diagnostics["investigationId"],
        "agentVersion": diagnostics.get("agentVersion"),
        "elapsedMs": diagnostics["elapsedMs"],
        "toolCalls": len(diagnostics["toolCalls"]),
        "modelTurns": diagnostics["modelTurns"],
        "usage": diagnostics["usage"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["replay", "foundry"], required=True)
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="Recheck the previous evaluation's saved audits without model calls",
    )
    args = parser.parse_args()
    settings = Settings().model_copy(update={"mode": args.mode})
    previous = None
    if args.rescore:
        previous = json.loads(
            (settings.output_dir / f"evaluation-{args.mode}.json").read_text(encoding="utf-8")
        )
        print("Re-scoring saved audits; no new model calls.", flush=True)
    rows = []
    with running_mock(settings.data_dir) as url:
        settings = settings.model_copy(update={"mock_api_url": url})
        for transaction in EXPECTATIONS:
            if previous:
                saved = next(row for row in previous["results"] if row["transactionId"] == transaction)
                result = json.loads(
                    (settings.output_dir / (saved["investigationId"] + ".json")).read_text(encoding="utf-8")
                )
                if result["diagnostics"]["mode"] != args.mode:
                    raise ValueError("Saved audit mode does not match the requested evaluation mode")
            else:
                result = investigate(settings, InvestigationRequest(**sample_request(transaction)))
            row = evaluate_run(transaction, result)
            rows.append(row)
            print(f"{transaction}: {'PASS' if row['passed'] else 'FAIL'} ({row['status']})", flush=True)
    output = {
        "mode": args.mode,
        "llmEvaluation": args.mode == "foundry",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "rescoredSavedAudits": args.rescore,
        "passed": sum(r["passed"] for r in rows),
        "total": len(rows),
        "results": rows,
        "limitations": "Automated status, coverage and recovery checks are not a semantic RCA accuracy score. Review linked reports for causal support and recommendation quality. Replay uses no LLM.",
    }
    path = settings.output_dir / f"evaluation-{args.mode}.json"
    path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Saved {path}: {output['passed']}/{output['total']} cases passed.")
    return 0 if output["passed"] == output["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
