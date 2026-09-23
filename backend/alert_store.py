"""Backend 4 Part 6: security alert domain (in-memory, development only).

Alerts are application-level observations built from an ALREADY-COMPUTED
``RiskAssessment`` -- this module never recalculates risk and never touches
ML. Vocabulary stays observational ("elevated risk", "signal"); words like
"fraud confirmed" or "deepfake confirmed" never appear here.

Generation rule (deterministic): only HIGH (risk >= 70) assessments yield
an alert; MEDIUM/LOW/UNKNOWN yield None. Deduplication: same call +
same alert type within ``cooldown_s`` (default 30s, constructor value)
reuses the existing alert instead of creating a duplicate. Cooldown uses
call-relative chunk timestamps (deterministic), never wall-clock, audio
or embeddings.

Mock gate: ``is_mock`` and provenance copy straight from the assessment.
Mock alerts are fully usable for UI development but stay flagged and must
never be presented as production-confirmed fraud.

Stored per alert (and nothing else): IDs, call-relative timestamp, risk
snapshot, title/message, reason dicts, provenance dict, acknowledged
flag, ISO created_at. No audio, embeddings, phone numbers, names,
profiles, owners or frontend objects.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from backend.b4_schemas import RiskAssessment
from backend.schemas import ValidationError

log = logging.getLogger(__name__)

ALERT_TYPE_ELEVATED_RISK = "elevated_risk"
DEFAULT_COOLDOWN_S = 30.0


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SecurityAlert:
    """One elevated-risk alert. Mutable only via ``acknowledged``."""

    alert_id: str
    call_id: str
    timestamp: float
    risk: float
    risk_level: str
    alert_type: str
    title: str
    message: str
    reasons: list
    is_mock: bool
    provenance: dict
    acknowledged: bool = False
    created_at: str = ""

    def to_dict(self) -> dict:
        import copy

        return copy.deepcopy(asdict(self))


def build_alert(assessment: RiskAssessment, timestamp: float) -> SecurityAlert | None:
    """Build an alert for a HIGH assessment, else None (no invention).

    Uses ``risk_score`` verbatim -- no recalculation. Raises
    ``ValidationError`` for wrong input types or bad timestamps.
    """
    if not isinstance(assessment, RiskAssessment):
        raise ValidationError(
            f"Expected RiskAssessment (got {type(assessment).__name__}).")
    if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
            or not 0.0 <= float(timestamp) < 1e9):
        raise ValidationError("timestamp must be call-relative seconds >= 0.")
    if assessment.risk_score is None or assessment.risk_level != "HIGH":
        return None
    score = float(assessment.risk_score)
    mock_note = (" Development/mock result: not production evidence."
                 if assessment.is_mock else "")
    return SecurityAlert(
        alert_id=uuid.uuid4().hex[:12],
        call_id=assessment.session_id,
        timestamp=float(timestamp),
        risk=score,
        risk_level="HIGH",
        alert_type=ALERT_TYPE_ELEVATED_RISK,
        title="Elevated voice-authenticity risk",
        message=(f"Call risk {score:.1f}/100 (HIGH) at {float(timestamp):.1f}s. "
                 f"Observed signals warrant review.{mock_note}"),
        reasons=[dict(reason) if isinstance(reason, dict) else reason.to_dict()
                 for reason in assessment.reasons],
        is_mock=assessment.is_mock,
        provenance=dict(assessment.provenance.to_dict()),
        created_at=_utcnow_iso(),
    )


class AlertStore:
    """Thread-safe in-memory alerts with cooldown deduplication."""

    def __init__(self, cooldown_s: float = DEFAULT_COOLDOWN_S) -> None:
        if (isinstance(cooldown_s, bool) or not isinstance(cooldown_s, (int, float))
                or float(cooldown_s) < 0):
            raise ValidationError("cooldown_s must be a number >= 0.")
        self.cooldown_s = float(cooldown_s)
        self._lock = threading.RLock()
        self._alerts: dict[str, SecurityAlert] = {}

    def __len__(self) -> int:
        with self._lock:
            return len(self._alerts)

    def create_if_new(self, assessment: RiskAssessment,
                      timestamp: float) -> SecurityAlert | None:
        """Build (HIGH only) and store, unless cooldown dedup hits.

        Returns the new or deduplicated alert, or None when no alert is
        warranted. Never raises for below-threshold assessments."""
        candidate = build_alert(assessment, timestamp)
        if candidate is None:
            return None
        with self._lock:
            for existing in self._alerts.values():
                if (existing.call_id == candidate.call_id
                        and existing.alert_type == candidate.alert_type
                        and abs(existing.timestamp - candidate.timestamp) <= self.cooldown_s):
                    log.info("alert dedup call=%s type=%s",
                             candidate.call_id, candidate.alert_type)
                    return existing
            self._alerts[candidate.alert_id] = candidate
            log.info("alert created id=%s call=%s risk=%.1f mock=%s",
                     candidate.alert_id, candidate.call_id,
                     candidate.risk, candidate.is_mock)
            return candidate

    def get(self, alert_id: str) -> SecurityAlert:
        with self._lock:
            alert = self._alerts.get(alert_id)
        if alert is None:
            raise ValidationError(f"alert {alert_id!r} not found.")
        return alert

    def list_for_call(self, call_id: str) -> list[SecurityAlert]:
        with self._lock:
            return [a for a in self._alerts.values() if a.call_id == call_id]

    def list_active(self) -> list[SecurityAlert]:
        """Unacknowledged alerts (active = needs attention)."""
        with self._lock:
            return [a for a in self._alerts.values() if not a.acknowledged]

    def acknowledge(self, alert_id: str) -> SecurityAlert:
        """Mark acknowledged (idempotent); history retained, never deleted."""
        with self._lock:
            alert = self._alerts.get(alert_id)
            if alert is None:
                raise ValidationError(f"alert {alert_id!r} not found.")
            alert.acknowledged = True
            log.info("alert acknowledged id=%s", alert_id)
            return alert

    def clear(self) -> None:
        """Remove all alerts (tests / controlled reset)."""
        with self._lock:
            self._alerts.clear()
