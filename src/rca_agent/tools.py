import time

from rca_agent.config import Settings
from rca_agent.evidence import EvidenceRegistry
from rca_agent.models import EvidenceArgs, QueryArgs
from rca_agent.sources import Scope, SourceReader

SOURCE_TOOLS = {"read_file_events": "file", "fetch_api_events": "api", "query_database_events": "database"}


def provider_schema(schema: dict) -> dict:
    """Strip application validation keywords unsupported by strict tool-schema subsets."""
    allowed = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "$ref",
        "$defs",
        "anyOf",
        "description",
    }

    def visit(value):
        if isinstance(value, list):
            return [visit(v) for v in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key not in allowed:
                continue
            if key in {"properties", "$defs"}:
                result[key] = {name: visit(child) for name, child in item.items()}
            else:
                result[key] = visit(item)
        return result

    return visit(schema)


def tool_definitions() -> list[dict]:
    descriptions = {
        "read_file_events": "Read actual checkout JSONL logs within the bound customer/transaction/time scope. Start cursor at 0; null filters search all known traces. Continue nextCursor pages.",
        "fetch_api_events": "Fetch a real HTTP payment log API and filter its snapshot by the bound scope. A historical httpStatus in an event is not the status of fetching logs.",
        "query_database_events": "Query local SQLite historical audit/event rows directly with predefined read-only SQL. Use discovered attemptId to investigate a recorded failure.",
    }
    tools = [
        {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": provider_schema(QueryArgs.model_json_schema()),
            "strict": True,
        }
        for name, description in descriptions.items()
    ]
    tools.append(
        {
            "type": "function",
            "name": "get_evidence",
            "description": "Retrieve previously issued evidence IDs from this investigation. Cannot access other investigations.",
            "parameters": provider_schema(EvidenceArgs.model_json_schema()),
            "strict": True,
        }
    )
    return tools


class ToolExecutor:
    def __init__(self, settings: Settings, scope: Scope, deadline: float):
        self.settings, self.scope, self.deadline = settings, scope, deadline
        self.reader = SourceReader(settings, scope)
        self.registry = EvidenceRegistry(settings.max_events)
        self.calls: list[dict] = []
        self.coverage = {
            s: {"attempted": False, "complete": False, "status": "not_queried", "errors": []}
            for s in SOURCE_TOOLS.values()
        }
        self.pages: dict[str, dict[int, int | None]] = {s: {} for s in self.coverage}

    def execute(self, name: str, arguments: dict) -> dict:
        if len(self.calls) >= self.settings.max_tool_calls or time.monotonic() >= self.deadline:
            raise TimeoutError("Tool call or time budget exhausted")
        started = time.monotonic()
        source = SOURCE_TOOLS.get(name)
        try:
            if name == "get_evidence":
                parsed = EvidenceArgs.model_validate(arguments)
                if not all(e in self.registry.records for e in parsed.evidenceIds):
                    raise ValueError("Evidence IDs must belong to this investigation")
                result = {
                    "status": "ok",
                    "events": [self._observation(self.registry.records[e]) for e in parsed.evidenceIds],
                }
            elif source:
                query = QueryArgs.model_validate(arguments)
                self.coverage[source]["attempted"] = True
                fetched = self.reader.read(source, query, self.deadline)
                observations = []
                for event, locator in fetched.pop("records"):
                    try:
                        observations.append(self._observation(self.registry.add(source, event, locator)))
                    except ValueError as exc:
                        fetched.update(status="partial", error=str(exc))
                if fetched["error"]:
                    self.coverage[source]["complete"] = False
                    self.pages[source].clear()
                    errors = self.coverage[source]["errors"]
                    if fetched["error"] not in errors:
                        errors.append(fetched["error"])
                broad = query.traceId is None and query.attemptId is None
                if broad and fetched["status"] == "ok":
                    self.pages[source][query.cursor] = fetched["nextCursor"]
                    cursor, visited = 0, set()
                    while cursor in self.pages[source] and cursor not in visited:
                        visited.add(cursor)
                        cursor = self.pages[source][cursor]
                        if cursor is None:
                            self.coverage[source]["complete"] = True
                            break
                self.coverage[source]["status"] = fetched["status"]
                result = {
                    **fetched,
                    "events": observations,
                    "sourceCoverage": self.coverage,
                    "correlation": self.registry.correlation(),
                }
            else:
                raise ValueError("Unknown tool; only the registered read-only tools are available")
        except ValueError:
            # Do not echo rejected arguments: they may contain attempted data exfiltration or secrets.
            result = {
                "status": "invalid_arguments",
                "events": [],
                "error": "Tool name or arguments violate the bound schema/scope",
            }
        self.calls.append(
            {
                "tool": name if name in {*SOURCE_TOOLS, "get_evidence"} else "unknown_tool",
                "arguments": arguments if result["status"] != "invalid_arguments" else {"rejected": True},
                "status": result["status"],
                "eventCount": len(result["events"]),
                "elapsedMs": round((time.monotonic() - started) * 1000),
                "nextCursor": result.get("nextCursor"),
                "error": result.get("error"),
            }
        )
        return result

    @staticmethod
    def _observation(record):
        return {"evidence": record.evidence.model_dump(), "event": record.event.model_dump(mode="json")}
