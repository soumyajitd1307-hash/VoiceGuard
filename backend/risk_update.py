"""RiskAssessment -> frontend-compatible RiskUpdate dict (no transport yet).

Produces the EXISTING frontend shape (``src/types/index.ts``)::

    {type, callId, timestamp, risk, syntheticProbability, speakerConsistency,
     contextRisk, confidence, monitoringState}

Rules (no fabrication):
    * ``risk_score`` None -> raise ``ValidationError`` (B4 does not emit
      updates for scoreless bundles; it never invents a number).
    * Present components map verbatim (synthetic 0..1 -> percent,
      consistency already percent). ABSENT components are OMITTED, never
      zero-filled -- Part 5 will make them explicitly optional in the
      transport/type contract.
    * ``timestamp`` is caller-supplied (chunk ``timestamp_s`` or call
      clock); this adapter never invents call timing.
    * ``confidence``: None/<0.5 -> LOW, <0.75 -> MEDIUM, else HIGH
      (documented heuristic, not calibration).
    * ``monitoringState`` from score bands only (>=70 ALERT_TRIGGERED,
      >=40 SUSPICIOUS, else MONITORING_ACTIVE). For ``is_mock`` outputs
      this is display state, NOT a production alert -- B4 must not route
      mock updates into alerting.
    * B3-only metrics (frequencyArtifacts/prosodyAnomaly/spectralFlux) are
      omitted: B3 emits no such signals and they are not invented here.

MOCK SAFETY: the frontend ``RiskUpdate`` type has no provenance field, so
mock visibility lives on ``RiskAssessment`` (``is_mock``/``provenance``).
This adapter is deliberately lossy about provenance; Part 5 must add an
additive provenance field to the transport contract. No raw embeddings,
audio or profiles ever appear here.
"""
from __future__ import annotations

from typing import Any

from backend.b4_schemas import RiskAssessment
from backend.schemas import ValidationError


def to_risk_update(
    assessment: RiskAssessment,
    timestamp: float,
    context_risk: float | None = None,
) -> dict:
    """Convert an assessment to a frontend-compatible RiskUpdate dict.

    Args:
        assessment: fused B4 assessment (must carry a risk score).
        timestamp: call-relative seconds for this chunk (caller-supplied).
        context_risk: explicit override for ``contextRisk``; defaults to
            the assessment's value, then to 0.0 (neutral baseline -- B4
            has no context model yet; documented, not measured).

    Raises:
        ValidationError: unscored assessment, bad timestamp/context types.
    """
    if not isinstance(assessment, RiskAssessment):
        raise ValidationError(
            f"Expected RiskAssessment (got {type(assessment).__name__})."
        )
    if assessment.risk_score is None:
        raise ValidationError("Cannot emit RiskUpdate without a risk score.")
    if (
        isinstance(timestamp, bool)
        or not isinstance(timestamp, (int, float))
        or not 0.0 <= float(timestamp) < 1e9
    ):
        raise ValidationError("timestamp must be call-relative seconds >= 0.")
    resolved_context = (
        assessment.context_risk if assessment.context_risk is not None
        else context_risk
    )
    if resolved_context is None:
        resolved_context = 0.0  # neutral baseline; no context model exists yet
    if (
        isinstance(resolved_context, bool)
        or not isinstance(resolved_context, (int, float))
        or not 0.0 <= float(resolved_context) <= 100.0
    ):
        raise ValidationError("context_risk must lie in [0, 100].")

    score = float(assessment.risk_score)
    confidence = assessment.confidence
    if confidence is None or confidence < 0.5:
        confidence_label = "LOW"
    elif confidence < 0.75:
        confidence_label = "MEDIUM"
    else:
        confidence_label = "HIGH"
    if score >= 70:
        monitoring_state = "ALERT_TRIGGERED"
    elif score >= 40:
        monitoring_state = "SUSPICIOUS"
    else:
        monitoring_state = "MONITORING_ACTIVE"

    update: dict[str, Any] = {
        "type": "risk_update",
        "callId": assessment.session_id,
        "timestamp": float(timestamp),
        "risk": round(score, 2),
        "confidence": confidence_label,
        "monitoringState": monitoring_state,
        "contextRisk": round(float(resolved_context), 2),
    }
    if assessment.synthetic_probability is not None:
        update["syntheticProbability"] = round(assessment.synthetic_probability * 100.0, 2)
    if assessment.speaker_consistency is not None:
        update["speakerConsistency"] = round(assessment.speaker_consistency, 2)
    return update
