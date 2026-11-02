from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)

from .classify import diagnosis_for_kind
from .config import get_settings
from .security import DROPPED_HEADERS, redact_headers

Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class RequestCreate(BaseModel):
    method: Method = "GET"
    url: str = Field(min_length=1, max_length=2048)
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    timeout_s: float = Field(10.0, ge=0.1, le=30)
    max_attempts: int = Field(4, ge=1, le=10)
    backoff_base_s: float = Field(1.0, ge=0.05, le=60)
    backoff_max_s: float = Field(60.0, ge=0.1, le=3600)

    @field_validator("headers")
    @classmethod
    def _headers(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 50:
            raise ValueError("at most 50 headers")
        clean = {}
        for name, val in value.items():
            if not name or any(c in name for c in " \t\r\n:") or any(c in val for c in "\r\n"):
                raise ValueError(f"invalid header {name!r}")
            if name.lower() not in DROPPED_HEADERS:
                clean[name] = val
        return clean

    @field_validator("body")
    @classmethod
    def _body(cls, value: str | None) -> str | None:
        if value is not None and len(value.encode()) > get_settings().max_body_bytes:
            raise ValueError("body too large")
        return value

    @model_validator(mode="after")
    def _backoff(self):
        if self.backoff_max_s < self.backoff_base_s:
            raise ValueError("backoff_max_s must be >= backoff_base_s")
        return self


class RequeueBody(BaseModel):
    extra_attempts: int = Field(3, ge=1, le=10)


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    number: int
    started_at: datetime
    finished_at: datetime
    latency_ms: float
    outcome: str
    status_code: int | None
    error_kind: str | None
    error_message: str | None
    retryable: bool
    will_retry: bool
    retry_in_s: float | None
    response_headers: dict
    response_body: str | None
    response_bytes: int | None

    @field_serializer("response_headers")
    def _redact(self, value: dict):
        return redact_headers(value)


class Diagnosis(BaseModel):
    kind: str
    retryable: bool
    explanation: str
    suggestion: str


class RequestSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    method: str
    url: str
    host: str
    status: str
    attempt_count: int
    max_attempts: int
    next_run_at: datetime
    last_status_code: int | None
    last_error_kind: str | None
    last_latency_ms: float | None
    replay_of: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def state(self) -> str:
        """`status` plus a `retrying` state for queued requests that already failed once."""
        return "retrying" if self.status == "queued" and self.attempt_count > 0 else self.status


class RequestDetail(RequestSummary):
    headers: dict
    body: str | None
    timeout_s: float
    backoff_base_s: float
    backoff_max_s: float
    idempotency_key: str | None
    attempts: list[AttemptOut]

    @field_serializer("headers")
    def _redact(self, value: dict):
        return redact_headers(value)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def diagnosis(self) -> Diagnosis | None:
        """Why the request failed, taken from its most recent failed attempt."""
        for attempt in reversed(self.attempts):
            d = diagnosis_for_kind(attempt.error_kind)
            if d:
                return Diagnosis(kind=d.kind, retryable=d.retryable, explanation=d.explanation,
                                 suggestion=d.suggestion)
        return None


class Page(BaseModel):
    items: list[RequestSummary]
    total: int
    limit: int
    offset: int
