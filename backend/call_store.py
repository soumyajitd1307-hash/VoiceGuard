"""Backend 4 Part 5: in-memory call/session store (development only).

Holds call-session state for the transport layer: which calls exist, who
owns them, which enrolled reference they use, and their latest safe
application-level outputs. Thread-safe via RLock; replaceable by a
DB-backed repository later (no persistence here).

Stored per call (and nothing else):
    * IDs and ownership: ``call_id``, ``owner_id``, ``reference_id``.
    * Lifecycle: ISO ``started_at`` / ``ended_at``, ``monitoring_state``.
    * Safe outputs only: latest ``RiskUpdate`` dict, latest
      ``RiskAssessment`` object (contains no vectors by construction),
      capped ``risk_history`` of past RiskUpdate dicts.

Never stored: raw audio, embeddings, phone numbers, contact names,
ProfileReference internals, frontend objects. Risk history entries are
copies, so later caller mutation cannot rewrite history.

Ownership: ``owner_id``-scoped lookups treat wrong-owner exactly like
missing (same "not found" error) so callers cannot probe other owners'
calls. External transport MUST eventually enforce authenticated identity;
``owner_id=None`` means trusted-internal access.
"""
from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.b4_schemas import RiskAssessment
from backend.schemas import ValidationError

MAX_HISTORY = 200
MAX_ID_LENGTH = 128


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_id(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string.")
    if not value or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    if len(value) > MAX_ID_LENGTH:
        raise ValidationError(f"{field_name} exceeds max length {MAX_ID_LENGTH}.")
    return value  # stored verbatim once validated


@dataclass
class CallSession:
    """One monitored call. Mutable lifecycle, safe payloads only."""

    call_id: str
    owner_id: str
    reference_id: str = ""
    started_at: str = field(default_factory=_utcnow_iso)
    ended_at: str | None = None
    monitoring_state: str = "MONITORING_ACTIVE"
    latest_risk_update: dict | None = None
    latest_assessment: RiskAssessment | None = None
    risk_history: list = field(default_factory=list)
    _seq: int = 0  # internal insertion order (deterministic history sorting)

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    @property
    def status(self) -> str:
        return "ACTIVE" if self.is_active else "ENDED"

    def to_frontend_dict(self) -> dict:
        """Frontend-compatible ``Call`` shape (see src/types/index.ts).

        Only measured/stored values are filled; everything unknown is an
        explicit null (never fabricated). The frontend already renders
        nulls safely (gauges coerce to 0, labels use ``||`` fallbacks);
        Part 5 must not invent trust scores, protocols or measurements.
        """
        latest = self.latest_risk_update or {}
        return {
            "id": self.call_id,
            "caller": {
                # NOTE: caller.id is the call's own slot, NOT the owner_id:
                # owner identity must never leak into frontend payloads.
                "id": self.call_id,
                "name": "Unknown caller",
                "phone": "",
                "trustScore": None,
                "language": "",
                "isKnownContact": False,
            },
            "receiver": "",
            "startTime": self.started_at,
            "durationSeconds": latest.get("timestamp", 0) or 0,
            "currentRisk": latest.get("risk"),
            "currentRiskLevel": _level_for(latest.get("risk")),
            "syntheticProbability": latest.get("syntheticProbability"),
            "speakerConsistency": latest.get("speakerConsistency"),
            "contextRisk": latest.get("contextRisk"),
            "confidence": latest.get("confidence", "LOW"),
            "status": self.status,
            "monitoringState": latest.get("monitoringState", self.monitoring_state),
            "detectionEvents": [],
            "riskHistory": [
                {
                    "timestamp": entry.get("timestamp"),
                    "risk": entry.get("risk"),
                    "syntheticProbability": entry.get("syntheticProbability"),
                }
                for entry in self.risk_history
            ],
            "evidence": None,
            "protocol": None,
            "codec": None,
            "packetLoss": None,
            "latencyMs": None,
        }


def _level_for(risk: object) -> str | None:
    if not isinstance(risk, (int, float)) or isinstance(risk, bool):
        return None
    if risk < 40:
        return "LOW"
    if risk < 70:
        return "MEDIUM"
    return "HIGH"


class CallStore:
    """Thread-safe in-memory call sessions (development only)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._calls: dict[str, CallSession] = {}
        self._seq = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._calls)

    def create_call(
        self,
        owner_id: str,
        reference_id: str = "",
        call_id: str | None = None,
    ) -> CallSession:
        """Create a session. Generates a UUID-based ID unless one is given
        (supplied IDs are validated and rejected on collision, including
        terminated calls, so history can never be ambiguated)."""
        owner = _check_id(owner_id, "owner_id")
        if not isinstance(reference_id, str):
            raise ValidationError("reference_id must be a string.")
        resolved_id = (
            _check_id(call_id, "call_id") if call_id is not None
            else uuid.uuid4().hex[:12]
        )
        with self._lock:
            if resolved_id in self._calls:
                raise ValidationError(f"call_id {resolved_id!r} already exists.")
            self._seq += 1
            session = CallSession(
                call_id=resolved_id, owner_id=owner,
                reference_id=reference_id, _seq=self._seq)
            self._calls[resolved_id] = session
            return session

    def get_call(self, call_id: str, owner_id: str | None = None) -> CallSession:
        """Fetch a session. Wrong owner behaves exactly like missing."""
        cleaned_id = _check_id(call_id, "call_id")
        if owner_id is not None:
            _check_id(owner_id, "owner_id")
        with self._lock:
            session = self._calls.get(cleaned_id)
        if session is None:
            raise ValidationError(f"call {cleaned_id!r} not found.")
        if owner_id is not None and session.owner_id != owner_id:
            raise ValidationError(f"call {cleaned_id!r} not found.")
        return session

    def list_active(self, owner_id: str | None = None) -> list[CallSession]:
        with self._lock:
            sessions = [s for s in self._calls.values() if s.is_active]
        if owner_id is not None:
            sessions = [s for s in sessions if s.owner_id == owner_id]
        return sorted(sessions, key=lambda s: (s.started_at, s._seq))

    def list_history(self, owner_id: str | None = None) -> list[CallSession]:
        """Terminated calls, newest first (deterministic via seq tiebreak)."""
        with self._lock:
            sessions = [s for s in self._calls.values() if not s.is_active]
        if owner_id is not None:
            sessions = [s for s in sessions if s.owner_id == owner_id]
        return sorted(sessions, key=lambda s: (s.started_at, s._seq), reverse=True)

    def update_latest(
        self,
        call_id: str,
        risk_update: dict,
        assessment: RiskAssessment | None = None,
        owner_id: str | None = None,
    ) -> CallSession:
        """Record a processed chunk's outputs (deep copies; history capped)."""
        if not isinstance(risk_update, dict):
            raise ValidationError("risk_update must be a dict.")
        session = self.get_call(call_id, owner_id)
        if not session.is_active:
            raise ValidationError(f"call {session.call_id!r} is terminated.")
        with self._lock:
            snapshot = copy.deepcopy(risk_update)
            session.latest_risk_update = snapshot
            session.latest_assessment = assessment
            session.risk_history.append(snapshot)
            del session.risk_history[:-MAX_HISTORY]
            state = snapshot.get("monitoringState")
            if isinstance(state, str) and state:
                session.monitoring_state = state
            return session

    def terminate_call(
        self, call_id: str, owner_id: str | None = None
    ) -> CallSession:
        """Mark terminated (idempotent: repeat calls return current state).
        This ends backend session tracking only -- not a real phone call."""
        session = self.get_call(call_id, owner_id)
        with self._lock:
            if session.ended_at is None:
                session.ended_at = _utcnow_iso()
                session.monitoring_state = "COMPLETED"
            return session

    def clear(self) -> None:
        """Remove all sessions (tests / controlled reset)."""
        with self._lock:
            self._calls.clear()
