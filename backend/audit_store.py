"""Backend 4 Part 6: append-only audit trail (in-memory, development only).

Records call-lifecycle facts: ``call_started``, ``risk_update``,
``evidence_created``, ``alert_created``, ``alert_acknowledged``,
``call_terminated``. Events are immutable and append-only -- no edit or
delete API exists (``clear()`` is test/reset-only and never exposed over
REST). Summaries are short application-level strings; actor is
``"system"`` for pipeline events or ``"development"`` for manual
operations (no authenticated identity exists yet, and none is pretended).

Stored per event (and nothing else): IDs, call-relative timestamp, type,
actor, summary, mock flag, ISO created_at. No audio, embeddings, secrets,
owner PII or internal objects.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from backend.schemas import ValidationError

log = logging.getLogger(__name__)

EVENT_CALL_STARTED = "call_started"
EVENT_RISK_UPDATE = "risk_update"
EVENT_EVIDENCE_CREATED = "evidence_created"
EVENT_ALERT_CREATED = "alert_created"
EVENT_ALERT_ACKNOWLEDGED = "alert_acknowledged"
EVENT_CALL_TERMINATED = "call_terminated"

_VALID_EVENTS = (
    EVENT_CALL_STARTED, EVENT_RISK_UPDATE, EVENT_EVIDENCE_CREATED,
    EVENT_ALERT_CREATED, EVENT_ALERT_ACKNOWLEDGED, EVENT_CALL_TERMINATED,
)
_VALID_ACTORS = ("system", "development")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AuditEvent:
    """One immutable audit fact."""

    event_id: str
    call_id: str
    timestamp: float
    event_type: str
    actor: str
    summary: str
    is_mock: bool
    created_at: str

    def to_dict(self) -> dict:
        import copy

        return copy.deepcopy(asdict(self))


class AuditStore:
    """Thread-safe append-only audit events."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: dict[str, AuditEvent] = {}
        self._order: list[str] = []

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    def append(
        self,
        event_type: str,
        call_id: str,
        summary: str,
        actor: str = "system",
        is_mock: bool = True,
        timestamp: float = 0.0,
    ) -> AuditEvent:
        """Append one event. All fields validated; vectors/PII rejected by
        construction (only plain strings/numbers accepted)."""
        if event_type not in _VALID_EVENTS:
            raise ValidationError(f"Unknown audit event type {event_type!r}.")
        for field_name, value in (("call_id", call_id), ("summary", summary)):
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"{field_name} must be a non-empty string.")
        if actor not in _VALID_ACTORS:
            raise ValidationError(f"actor must be one of {list(_VALID_ACTORS)}.")
        if not isinstance(is_mock, bool):
            raise ValidationError("is_mock must be a boolean.")
        if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                or not 0.0 <= float(timestamp) < 1e9):
            raise ValidationError("timestamp must be call-relative seconds >= 0.")
        event = AuditEvent(
            event_id=uuid.uuid4().hex[:12],
            call_id=call_id,
            timestamp=float(timestamp),
            event_type=event_type,
            actor=actor,
            summary=summary,
            is_mock=is_mock,
            created_at=_utcnow_iso(),
        )
        with self._lock:
            self._events[event.event_id] = event
            self._order.append(event.event_id)
        log.info("audit %s call=%s", event_type, call_id)
        return event

    def get(self, event_id: str) -> AuditEvent:
        with self._lock:
            event = self._events.get(event_id)
        if event is None:
            raise ValidationError(f"audit event {event_id!r} not found.")
        return event

    def list_for_call(self, call_id: str) -> list[AuditEvent]:
        with self._lock:
            return [self._events[event_id] for event_id in self._order
                    if self._events[event_id].call_id == call_id]

    def clear(self) -> None:
        """Remove all events (tests / controlled reset only)."""
        with self._lock:
            self._events.clear()
            self._order.clear()


def summarize_assessment(assessment: Any) -> str:
    """One-line audit summary for a risk assessment (no vectors, no PII)."""
    return (f"risk {assessment.risk_score}/100 ({assessment.risk_level}); "
            f"synthetic={assessment.synthetic_probability}; "
            f"consistency={assessment.speaker_consistency}")
