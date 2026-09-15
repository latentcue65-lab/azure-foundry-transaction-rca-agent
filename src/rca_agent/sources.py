"""Read-only source adapters. The model never supplies paths, URLs, or SQL."""

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass

import httpx

from rca_agent.config import Settings
from rca_agent.models import Event, InvestigationRequest, QueryArgs, utc

MAX_SOURCE_BYTES = 2_000_000


class ScopeError(ValueError):
    def __init__(self, message: str, candidates: list | None = None):
        super().__init__(message)
        self.candidates = candidates


@contextmanager
def readonly_db(settings: Settings):
    connection = sqlite3.connect(settings.db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


@dataclass
class Scope:
    request: InvestigationRequest
    transaction_id: str
    mappings: set[tuple[str, str]]
    final_status: str

    def permits(self, event: Event) -> bool:
        if event.customerId != self.request.customerId or event.transactionId != self.transaction_id:
            return False
        if not self.request.fromTime <= event.timestamp <= self.request.toTime:
            return False
        if event.traceId is not None:
            return any(
                t == event.traceId and (event.attemptId is None or a == event.attemptId)
                for t, a in self.mappings
            )
        # Missing trace is usable only with a recorded attempt association; never time proximity alone.
        return event.attemptId is not None and any(a == event.attemptId for _, a in self.mappings)

    def describe(self) -> dict:
        return {
            "customerId": self.request.customerId,
            "transactionId": self.transaction_id,
            "fromTime": utc(self.request.fromTime),
            "toTime": utc(self.request.toTime),
            "transactionSnapshotStatus": self.final_status,
            "traceMappings": [{"traceId": t, "attemptId": a} for t, a in sorted(self.mappings)],
        }


def resolve_scope(settings: Settings, request: InvestigationRequest) -> Scope:
    with readonly_db(settings) as db:
        # Do not reveal whether a supplied transaction exists under a different customer.
        sql = "SELECT transaction_id, final_status FROM transactions WHERE customer_id=? AND created_at>=? AND created_at<=?"
        args = [request.customerId, utc(request.fromTime), utc(request.toTime)]
        if request.transactionId:
            sql += " AND transaction_id=?"
            args.append(request.transactionId)
        rows = db.execute(sql + " ORDER BY created_at, transaction_id LIMIT 101", args).fetchall()
        if not rows:
            raise ScopeError("No authorized transaction found in the requested window")
        if len(rows) > 1:
            raise ScopeError(
                "Select a transactionId; multiple transactions match", [dict(r) for r in rows[:100]]
            )
        tx = rows[0]["transaction_id"]
        mappings = {
            (r[0], r[1])
            for r in db.execute(
                "SELECT trace_id,attempt_id FROM transaction_traces WHERE transaction_id=?", (tx,)
            )
        }
    return Scope(request, tx, mappings, rows[0]["final_status"])


class SourceReader:
    def __init__(self, settings: Settings, scope: Scope):
        self.settings, self.scope = settings, scope
        self.api_snapshot: list[tuple[dict, str]] | None = None
        self.api_snapshot_hash: str | None = None

    def read(self, source: str, query: QueryArgs, deadline: float) -> dict:
        if query.traceId and not any(t == query.traceId for t, _ in self.scope.mappings):
            raise ScopeError("Trace is outside this investigation")
        if query.attemptId and not any(a == query.attemptId for _, a in self.scope.mappings):
            raise ScopeError("Attempt is outside this investigation")
        if query.traceId and query.attemptId and (query.traceId, query.attemptId) not in self.scope.mappings:
            raise ScopeError("Trace and attempt do not have a recorded association")
        try:
            if source == "file":
                records = self._file()
            elif source == "api":
                records = self._api(deadline)
            else:
                records = self._database(query)
            selected, invalid, excluded = [], 0, 0
            for raw, locator in records:
                if time.monotonic() > deadline:
                    raise TimeoutError("Investigation deadline reached")
                try:
                    event = Event.model_validate(raw)
                except ValueError:
                    invalid += 1
                    continue
                if not self.scope.permits(event):
                    excluded += 1
                    continue
                if query.traceId and event.traceId != query.traceId:
                    continue
                if query.attemptId and event.attemptId != query.attemptId:
                    continue
                selected.append((event, locator))
            selected.sort(key=lambda x: (x[0].timestamp, x[0].eventId, x[1]))
            page = selected[query.cursor : query.cursor + self.settings.page_size]
            next_cursor = query.cursor + len(page)
            truncated = next_cursor < len(selected)
            return {
                "status": "partial" if invalid else "ok",
                "records": page,
                "truncated": truncated,
                "nextCursor": next_cursor if truncated else None,
                "invalidRecords": invalid,
                "excludedRecords": excluded,
                "matchedCount": len(selected),
                "error": "Malformed source records were excluded" if invalid else None,
                "snapshotHash": self.api_snapshot_hash if source == "api" else None,
            }
        except (httpx.HTTPError, OSError, sqlite3.Error, ValueError, TimeoutError) as exc:
            # Keep remote payloads, credentials, filesystem paths, and connection strings out of diagnostics.
            kind = "timeout" if isinstance(exc, (httpx.TimeoutException, TimeoutError)) else "unavailable"
            return {
                "status": kind,
                "records": [],
                "truncated": False,
                "nextCursor": None,
                "invalidRecords": 0,
                "excludedRecords": 0,
                "matchedCount": 0,
                "error": f"{source} retrieval failed ({type(exc).__name__})",
                "snapshotHash": None,
            }

    def _file(self):
        path = self.settings.log_path.resolve()
        approved = (self.settings.data_dir / "logs").resolve()
        if not path.is_relative_to(approved) or path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("File outside approved scope or too large")
        with path.open(encoding="utf-8") as stream:
            for line, text in enumerate(stream, 1):
                try:
                    raw = json.loads(text)
                except ValueError:
                    raw = {}
                yield raw, f"file:logs/checkout.jsonl:{line}"

    def _database(self, query: QueryArgs):
        sql = "SELECT event_id,event_json FROM events WHERE customer_id=? AND transaction_id=? AND timestamp_utc>=? AND timestamp_utc<=?"
        args = [
            self.scope.request.customerId,
            self.scope.transaction_id,
            utc(self.scope.request.fromTime),
            utc(self.scope.request.toTime),
        ]
        if query.traceId:
            sql += " AND trace_id=?"
            args.append(query.traceId)
        if query.attemptId:
            sql += " AND attempt_id=?"
            args.append(query.attemptId)
        with readonly_db(self.settings) as db:
            total_bytes = 0
            for row in db.execute(sql + " ORDER BY timestamp_utc,event_id", args):
                total_bytes += len(row["event_json"].encode())
                if total_bytes > MAX_SOURCE_BYTES:
                    raise ValueError("Database source exceeds POC read budget")
                try:
                    raw = json.loads(row["event_json"])
                except ValueError:
                    raw = {}
                yield raw, f"database:transactions.db/events/event_id={row['event_id']}"

    def _api(self, deadline: float):
        if self.api_snapshot is not None:
            return self.api_snapshot
        for attempt in range(2):
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                with httpx.Client(
                    timeout=min(self.settings.http_timeout, remaining), follow_redirects=False
                ) as client:
                    with client.stream("GET", self.settings.mock_api_url) as response:
                        response.raise_for_status()
                        chunks, size = [], 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > MAX_SOURCE_BYTES or time.monotonic() > deadline:
                                raise ValueError("HTTP response exceeds size/deadline budget")
                            chunks.append(chunk)
                payload = b"".join(chunks)
                body = json.loads(payload)
                events = body.get("events") if isinstance(body, dict) else body
                if not isinstance(events, list):
                    raise ValueError("Expected an events array or object containing events")
                digest = hashlib.sha256(payload).hexdigest()
                self.api_snapshot_hash = digest
                self.api_snapshot = [
                    (raw, f"api:payment-events/snapshot={digest[:12]}/index={i}")
                    for i, raw in enumerate(events)
                ]
                return self.api_snapshot
            except (httpx.TimeoutException, httpx.ConnectError):
                if attempt == 1:
                    raise
        raise RuntimeError("Unreachable")
