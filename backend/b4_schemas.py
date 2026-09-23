"""Backend 4 domain schemas: risk assessment and its supporting types.

B4 consumes ``Backend3Signals`` and produces application-level risk.
B4 never reimplements detection, embeddings or cosine similarity, and
never invents ML results. Missing B3 signals stay None -- never 0.

Scales (documented once, used everywhere):
    * ``synthetic_probability``: 0..1, verbatim from B3 (audit-friendly).
    * ``speaker_consistency``: 0..100 %, derived from cosine similarity
      (consistency = (similarity + 1) / 2 * 100). Matches the frontend
      ``RiskUpdate.speakerConsistency`` percent scale.
    * ``context_risk``: 0..100 % or None. No context model exists yet, so
      this is normally None (unknown), never a measured value.
    * ``risk_score``: 0..100 or None (None only when no usable signal).
    * ``confidence``: fusion confidence in [0, 1] or None. This reflects
      signal AVAILABILITY only ("fusion confidence, not model accuracy"):
      no usable signals -> None; one signal -> limited; two -> higher.
      It is NOT calibrated and must never be read as model accuracy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
ReasonSeverity = Literal["info", "warning", "critical"]
ReasonSource = Literal[
    "synthetic_detection", "speaker_similarity", "context", "fusion", "provenance"
]


@dataclass(frozen=True)
class RiskReason:
    """One machine-readable observation behind an assessment.

    Reasons describe observations in plain language (no sensational
    wording). ``code`` values are stable identifiers; see
    backend/risk_engine.py for the emitted set.
    """

    code: str
    message: str
    severity: ReasonSeverity
    source: ReasonSource

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RiskProvenance:
    """B3 model provenance preserved per component (never merged/faked).

    Each version is the exact string from the corresponding B3 result, or
    None when that signal was absent. ``is_mock`` is True when ANY present
    signal came from a development/mock model.
    """

    detector_version: str | None
    embedder_version: str | None
    similarity_version: str | None
    reference_id: str
    is_mock: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RiskAssessment:
    """Application-level risk for one call chunk (Backend 4 output).

    Contains NO raw embeddings, NO audio, NO voice profile -- only fused
    numbers, reasons and provenance. ``risk_score``/``risk_level`` are
    DEVELOPMENT HEURISTICS (see backend/risk_engine.py), not validated
    decisions; ``is_mock=true`` assessments must never become production
    alerts or evidence.
    """

    session_id: str
    chunk_id: str
    risk_score: float | None
    risk_level: RiskLevel
    confidence: float | None
    synthetic_probability: float | None
    speaker_consistency: float | None
    context_risk: float | None
    reasons: tuple
    provenance: RiskProvenance
    is_mock: bool
    processing_time_ms: float

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["reasons"] = [reason.to_dict() for reason in self.reasons]
        payload["provenance"] = self.provenance.to_dict()
        return payload
