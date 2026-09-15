from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestigationRequest(StrictModel):
    customerId: str = Field(min_length=1, max_length=80, pattern=r"^[\w-]+$")
    transactionId: str | None = Field(None, min_length=1, max_length=80, pattern=r"^[\w-]+$")
    fromTime: datetime
    toTime: datetime
    issueDescription: str = Field("Investigate the transaction outcome.", max_length=2000)

    @field_validator("fromTime", "toTime")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def window(self):
        if not self.fromTime < self.toTime:
            raise ValueError("fromTime must precede toTime")
        if self.toTime - self.fromTime > timedelta(days=1):
            raise ValueError("Investigation window must not exceed 24 hours")
        return self


class Event(StrictModel):
    eventId: str = Field(min_length=1, max_length=128)
    customerId: str
    transactionId: str
    traceId: str | None
    attemptId: str | None
    timestamp: datetime
    service: str = Field(min_length=1, max_length=100)
    eventType: str = Field(min_length=1, max_length=100)
    message: str = Field(max_length=2000)
    attributes: dict[str, Any] = Field(default_factory=dict)
    spanId: str | None = None
    parentSpanId: str | None = None

    @field_validator("timestamp")
    @classmethod
    def zoned(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Event timestamp requires timezone")
        return value.astimezone(timezone.utc)


class RootCause(StrictModel):
    status: Literal["identified", "suspected", "insufficient_evidence", "no_failure"]
    summary: str = Field(min_length=1, max_length=6000)
    evidenceIds: list[str]
    limitations: list[str]


class FlowStep(StrictModel):
    step: int = Field(ge=1)
    timestamp: str | None
    service: str
    event: str
    evidenceIds: list[str] = Field(min_length=1)


class Evidence(StrictModel):
    evidenceId: str
    source: Literal["file", "api", "database"]
    locator: str
    traceId: str | None
    timestamp: str | None
    excerpt: str


class Recommendation(StrictModel):
    action: str
    reason: str
    evidenceIds: list[str]


class RCA(StrictModel):
    customerId: str
    transactionId: str
    rootCause: RootCause
    failureFlow: list[FlowStep]
    evidence: list[Evidence]
    recommendation: list[Recommendation]


class QueryArgs(StrictModel):
    # Nullable fields are required in the tool schema for strict function calling.
    traceId: str | None
    attemptId: str | None
    cursor: int = Field(ge=0, le=100000)


class EvidenceArgs(StrictModel):
    evidenceIds: list[str] = Field(min_length=1, max_length=20)
