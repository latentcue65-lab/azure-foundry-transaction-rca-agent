import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass

from rca_agent.models import Event, Evidence, utc


@dataclass(frozen=True)
class Record:
    event: Event
    evidence: Evidence
    sha256: str


class EvidenceRegistry:
    def __init__(self, limit: int):
        self.records: dict[str, Record] = {}
        self.limit = limit

    def add(self, source: str, event: Event, locator: str) -> Record:
        canonical = json.dumps(event.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        if len(canonical.encode()) > 8000:
            raise ValueError("Event exceeds the per-record evidence size limit")
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        identifier = f"{source}:{event.eventId}"
        if identifier in self.records:
            old = self.records[identifier]
            if old.sha256 != digest:
                raise ValueError("Source event ID was reused with different content")
            return old
        if len(self.records) >= self.limit:
            raise ValueError("Investigation event budget reached")
        evidence = Evidence(
            evidenceId=identifier,
            source=source,
            locator=locator,
            traceId=event.traceId,
            timestamp=utc(event.timestamp),
            excerpt=canonical,
        )
        record = Record(event.model_copy(deep=True), evidence, digest)
        self.records[identifier] = record
        return record

    def ordered(self) -> list[Record]:
        return sorted(self.records.values(), key=lambda r: (r.event.timestamp, r.evidence.evidenceId))

    def correlation(self) -> dict:
        groups = defaultdict(list)
        outcomes = defaultdict(set)
        missing_trace = []
        edges, unresolved = [], []
        by_event = defaultdict(list)
        for record in self.ordered():
            by_event[record.event.eventId].append(record)
        for record in self.ordered():
            e = record.event
            groups[e.attemptId].append(record.evidence.evidenceId)
            if e.traceId is None:
                missing_trace.append(record.evidence.evidenceId)
            if e.eventType in {"checkout.failed", "checkout.succeeded"}:
                outcomes[e.attemptId].add(e.eventType)
            parent = e.attributes.get("causedByEventId")
            if parent:
                candidates = by_event.get(parent, []) if isinstance(parent, str) else []
                if len(candidates) == 1:
                    edges.append(
                        {
                            "from": candidates[0].evidence.evidenceId,
                            "to": record.evidence.evidenceId,
                            "basis": "explicit causedByEventId in source record",
                        }
                    )
                else:
                    unresolved.append(record.evidence.evidenceId)
        return {
            "attempts": [{"attemptId": a, "evidenceIds": ids} for a, ids in groups.items()],
            "conflictingAttempts": [a for a, states in outcomes.items() if len(states) > 1],
            "missingTraceEvidence": missing_trace,
            "causalEdges": edges,
            "unresolvedCauseLinks": unresolved,
            "orderingNote": "Display order uses event timestamps; association uses recorded trace/attempt mappings. Timestamps alone do not prove cause.",
        }

    def export(self) -> list[dict]:
        return [
            {
                "event": r.event.model_dump(mode="json"),
                "evidence": r.evidence.model_dump(),
                "sha256": r.sha256,
            }
            for r in self.ordered()
        ]
