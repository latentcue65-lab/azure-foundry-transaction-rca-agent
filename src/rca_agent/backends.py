"""Backend boundary: the replay is a test double, never a substitute for an LLM claim."""

import json
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass
class Turn:
    calls: list[ToolCall] = field(default_factory=list)
    text: str = ""
    response_id: str | None = None
    usage: dict = field(default_factory=dict)


class ReplayBackend:
    """Deterministic integration-test backend. It reads tool observations, not expected answers.

    This demonstrates I/O and validates the executor without Azure credentials. It is NOT an LLM.
    Real interviews should use FoundryBackend and label any offline run as replay.
    """

    name = "replay (deterministic test double; no LLM)"

    def __init__(self, scope):
        self.scope = scope
        self.observations = {}
        self.queried = set()
        self.pending = None
        self.last_args = None
        self.targeted = False
        self.coverage = {}
        self.counter = 0
        self.next_page = None

    def next(self, inputs: list[dict], remaining: float) -> Turn:
        for item in inputs:
            if item.get("type") != "function_call_output":
                continue
            result = json.loads(item["output"])
            for observation in result.get("events", []):
                self.observations[observation["evidence"]["evidenceId"]] = observation
            self.coverage = result.get("sourceCoverage", self.coverage)
            self.next_page = result.get("nextCursor")
        if self.next_page is not None:
            args = {**self.last_args, "cursor": self.next_page}
            self.next_page = None
            return self._call(self.pending, args)
        if "read_file_events" not in self.queried:
            return self._call("read_file_events")
        if "fetch_api_events" not in self.queried:
            return self._call("fetch_api_events")
        if not self.targeted:
            self.targeted = True
            failed = next(
                (
                    o
                    for o in self.observations.values()
                    if o["evidence"]["source"] == "api" and o["event"]["attributes"].get("errorCode")
                ),
                None,
            )
            if failed:
                return self._call(
                    "query_database_events",
                    {
                        "traceId": failed["event"]["traceId"],
                        "attemptId": failed["event"]["attemptId"],
                        "cursor": 0,
                    },
                )
        if not getattr(self, "broad_database", False):
            self.broad_database = True
            return self._call("query_database_events")
        return Turn(text=json.dumps(self._report()))

    def _call(self, name, args=None):
        self.counter += 1
        self.pending = name
        self.queried.add(name)
        self.last_args = args or {"traceId": None, "attemptId": None, "cursor": 0}
        return Turn(calls=[ToolCall(f"replay-{self.counter}", name, json.dumps(self.last_args))])

    def _report(self):
        observations = sorted(
            self.observations.values(),
            key=lambda o: (datetime.fromisoformat(o["event"]["timestamp"]), o["evidence"]["evidenceId"]),
        )
        failures = [o for o in observations if o["event"]["eventType"] == "checkout.failed"]
        successes = [o for o in observations if o["event"]["eventType"] == "checkout.succeeded"]
        conflicts = bool(
            {o["event"]["attemptId"] for o in failures} & {o["event"]["attemptId"] for o in successes}
        )
        wallet = next((o for o in observations if o["event"]["eventType"] == "wallet.debit_rejected"), None)
        pool = next(
            (o for o in observations if o["event"]["eventType"] == "database.connection_acquire_failed"), None
        )
        limits = [
            f"{source} coverage is incomplete ({c['status']})."
            for source, c in self.coverage.items()
            if not c["complete"]
        ]
        status = "insufficient_evidence"
        summary = "Available observations do not establish the underlying cause of the transaction outcome."
        action = "Retrieve the missing downstream decision logs before retrying or concluding."
        reason = "The available evidence does not establish the underlying cause or safe remediation."
        if conflicts:
            limits.append("The same attempt has conflicting checkout success and failure records.")
            summary = (
                "Checkout outcome records conflict; a reliable final outcome and cause cannot be established."
            )
        elif wallet:
            a = wallet["event"]["attributes"]
            if (
                a.get("errorCode") == "INSUFFICIENT_BALANCE"
                and a.get("decision") == "REJECTED"
                and isinstance(a.get("availableMinor"), int)
                and isinstance(a.get("requestedMinor"), int)
                and a["availableMinor"] < a["requestedMinor"]
            ):
                status = "suspected" if limits else "identified"
                summary = (
                    f"At the recorded debit decision, {a.get('currency')} {a['availableMinor'] / 100:.2f} "
                    f"was available against {a['requestedMinor'] / 100:.2f} requested. "
                    "Insufficient wallet funds caused the recorded debit rejection."
                )
                if failures:
                    summary += " Checkout subsequently recorded failure for the associated attempt."
                limits.append("The records do not establish why the wallet balance was low.")
                action = "Check available funds or choose another payment method before another attempt."
                reason = "The historical wallet decision records insufficient funds."
        elif pool:
            status = "suspected" if limits else "identified"
            summary = "The ledger recorded connection pool exhaustion while acquiring a connection; the associated payment and checkout failed."
            limits.append(
                "The records do not establish why connections remained occupied; a leak is not proven."
            )
            action = (
                "Inspect connection hold times, pool utilization, and release paths before changing capacity."
            )
            reason = "The database-side audit explicitly records connection pool exhaustion."
        elif successes and not failures:
            status = "suspected" if limits else "no_failure"
            summary = "Checkout success is recorded for this transaction; no checkout failure was observed in the retrieved scope."
            action = "No corrective action is indicated by the retrieved success evidence."
            reason = "Checkout has explicit success evidence."
        elif successes and failures:
            status = "suspected"
            summary = "An earlier payment attempt timed out; a mapped retry under a new trace succeeded and checkout recovered. The underlying timeout cause is unknown."
            limits.append("Provider-side evidence explaining the earlier timeout is missing.")
            action = "Avoid another payment attempt; review the recovered transaction and investigate the earlier timeout separately."
            reason = "A later mapped attempt has positive checkout success evidence."
        if status == "insufficient_evidence" and not limits:
            limits.append("No evidence establishes the underlying failure mechanism.")
        # Keep untrusted messages as evidence data, never as executable instructions or report guidance.
        relevant = [o for o in observations if o["event"]["eventType"] != "client.note"]
        ids = [o["evidence"]["evidenceId"] for o in relevant]
        return {
            "customerId": self.scope.request.customerId,
            "transactionId": self.scope.transaction_id,
            "rootCause": {"status": status, "summary": summary, "evidenceIds": ids, "limitations": limits},
            "failureFlow": [
                {
                    "step": i + 1,
                    "timestamp": o["evidence"]["timestamp"],
                    "service": o["event"]["service"],
                    "event": o["event"]["message"],
                    "evidenceIds": [o["evidence"]["evidenceId"]],
                }
                for i, o in enumerate(relevant)
            ],
            "evidence": [o["evidence"] for o in relevant],
            "recommendation": [{"action": action, "reason": reason, "evidenceIds": ids}],
        }

    def close(self):
        pass
