"""Backend 4 risk fusion: Backend3Signals -> RiskAssessment (in-process only).

DEVELOPMENT HEURISTICS ONLY. Nothing here is production-calibrated:
weights, mappings and boundaries are explicit, documented placeholders
to be replaced with evaluated values (B3 Part 4 framework) before any
production use. No output of this module is validated ML evidence while
``is_mock`` is True.

Fusion formula (deterministic):
    synthetic_risk = synthetic_probability * 100            (0..100)
    speaker_risk   = (1 - similarity) / 2 * 100            (0..100)
        Higher similarity -> lower impersonation risk; lower similarity
        -> higher risk. Similarity itself is NOT a risk score; this linear
        map is the documented transformation, nothing more.
    risk_score = sum(weight_i * risk_i) / sum(weights of PRESENT signals)
        Weights renormalize over available signals, so a missing signal
        contributes nothing (it is NOT treated as zero). Result clamped
        to [0, 100] and rounded to 2 decimals. No usable signal ->
        risk_score None, risk_level "UNKNOWN".

Risk levels mirror the confirmed frontend boundaries (utils/risk.ts):
    0-39 LOW, 40-69 MEDIUM, 70-100 HIGH (score None -> "UNKNOWN").
    Reimplemented here as a pure backend function; no frontend import.

Fusion confidence (metadata, NOT model accuracy):
    no usable signals -> None; one signal -> 0.5; two signals -> 0.8.

Mock gate (``is_mock_bundle``): True when ANY present nested B3 signal
has ``is_mock`` True. The gate does not suppress development output --
the assessment is still calculated -- but it stays flagged ``is_mock``
and must never become a production alert or evidence.

Reason codes emitted: SYNTHETIC_VOICE_SIGNAL, SPEAKER_MISMATCH,
SPEAKER_MATCH, SPEAKER_UNCERTAIN, MISSING_SPEAKER_REFERENCE,
MISSING_SYNTHETIC_SIGNAL, MOCK_MODEL_SIGNAL, NO_USABLE_SIGNALS.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from backend.b4_schemas import (
    RiskAssessment,
    RiskLevel,
    RiskProvenance,
    RiskReason,
)
from backend.schemas import Backend3Signals, ValidationError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RiskWeights:
    """Fusion weights. DEVELOPMENT HEURISTICS ONLY -- not validated.

    Replace with evaluated values before production use.
    """

    synthetic: float = 0.6
    speaker: float = 0.4

    def __post_init__(self) -> None:
        for name in ("synthetic", "speaker"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValidationError(f"RiskWeights.{name} must be a number.")
            if value < 0:
                raise ValidationError(f"RiskWeights.{name} must be >= 0.")
        if self.synthetic + self.speaker <= 0:
            raise ValidationError("At least one RiskWeights value must be > 0.")


def is_mock_bundle(signals: Backend3Signals) -> bool:
    """True when ANY present nested B3 signal came from a mock model."""
    if not isinstance(signals, Backend3Signals):
        raise ValidationError(
            f"Expected Backend3Signals (got {type(signals).__name__})."
        )
    return any(
        part is not None and part.is_mock
        for part in (signals.synthetic, signals.speaker, signals.similarity)
    )


def synthetic_risk_contribution(synthetic_probability: float) -> float:
    """Map P(synthetic) in [0, 1] to a 0..100 risk contribution."""
    return synthetic_probability * 100.0


def speaker_risk_contribution(similarity: float) -> float:
    """Map cosine similarity in [-1, 1] to a 0..100 impersonation-risk
    contribution: 1 -> 0, 0 -> 50, -1 -> 100."""
    return (1.0 - similarity) / 2.0 * 100.0


def speaker_consistency(similarity: float) -> float:
    """Map cosine similarity in [-1, 1] to a 0..100 consistency percent."""
    return (similarity + 1.0) / 2.0 * 100.0


def risk_level_for(score: float | None) -> RiskLevel:
    """Pure backend mapping; mirrors the frontend 0-39/40-69/70-100 bands."""
    if score is None:
        return "UNKNOWN"
    if score < 40:
        return "LOW"
    if score < 70:
        return "MEDIUM"
    return "HIGH"


class RiskFusionEngine:
    """Deterministic in-process fusion of B3 signals into risk."""

    def __init__(self, weights: RiskWeights | None = None) -> None:
        self.weights = weights or RiskWeights()

    def assess(
        self,
        signals: Backend3Signals,
        context_risk: float | None = None,
    ) -> RiskAssessment:
        """Fuse one signal bundle into a RiskAssessment.

        Args:
            signals: validated ``Backend3Signals`` from B3.
            context_risk: optional 0..100 passthrough, recorded but NOT
                fused (no context model exists yet).

        Raises:
            ValidationError: wrong input type, bad context_risk value.
        """
        start = time.perf_counter()
        if not isinstance(signals, Backend3Signals):
            raise ValidationError(
                f"Expected Backend3Signals (got {type(signals).__name__})."
            )
        if context_risk is not None:
            if (
                isinstance(context_risk, bool)
                or not isinstance(context_risk, (int, float))
                or not 0.0 <= float(context_risk) <= 100.0
            ):
                raise ValidationError("context_risk must lie in [0, 100].")
            context_risk = float(context_risk)

        synthetic_probability = (
            signals.synthetic.synthetic_probability if signals.synthetic else None
        )
        similarity_value = (
            signals.similarity.similarity if signals.similarity else None
        )
        consistency = (
            round(speaker_consistency(similarity_value), 2)
            if similarity_value is not None
            else None
        )

        contributions: list[tuple[float, float]] = []  # (weight, risk)
        reasons: list[RiskReason] = []
        if synthetic_probability is not None:
            contributions.append(
                (self.weights.synthetic,
                 synthetic_risk_contribution(synthetic_probability))
            )
            reasons.append(RiskReason(
                code="SYNTHETIC_VOICE_SIGNAL",
                message=f"Synthetic-voice probability {synthetic_probability:.2f} "
                        f"(model {signals.synthetic.model_version}).",
                severity="warning" if synthetic_probability >= 0.5 else "info",
                source="synthetic_detection",
            ))
        else:
            reasons.append(RiskReason(
                code="MISSING_SYNTHETIC_SIGNAL",
                message="No synthetic-voice signal present; risk uses speaker data only.",
                severity="info",
                source="fusion",
            ))
        if similarity_value is not None:
            contributions.append(
                (self.weights.speaker, speaker_risk_contribution(similarity_value))
            )
            match = signals.similarity.match if signals.similarity else "uncertain"
            if match == "match":
                reasons.append(RiskReason(
                    code="SPEAKER_MATCH",
                    message=f"Speaker similarity {similarity_value:.3f} at/above "
                            f"threshold for reference "
                            f"'{signals.similarity.reference_id}'.",
                    severity="info",
                    source="speaker_similarity",
                ))
            elif match == "non_match":
                reasons.append(RiskReason(
                    code="SPEAKER_MISMATCH",
                    message=f"Speaker similarity {similarity_value:.3f} below threshold "
                            f"for reference '{signals.similarity.reference_id}'.",
                    severity="warning",
                    source="speaker_similarity",
                ))
            else:
                reasons.append(RiskReason(
                    code="SPEAKER_UNCERTAIN",
                    message=f"Speaker similarity {similarity_value:.3f} with no "
                            "configured threshold; no speaker decision.",
                    severity="info",
                    source="speaker_similarity",
                ))
        else:
            reasons.append(RiskReason(
                code="MISSING_SPEAKER_REFERENCE",
                message="No speaker similarity present; risk uses synthetic data only.",
                severity="info",
                source="fusion",
            ))

        mock = is_mock_bundle(signals)
        if mock:
            reasons.append(RiskReason(
                code="MOCK_MODEL_SIGNAL",
                message="One or more inputs came from development/mock models; "
                        "this assessment is not production evidence.",
                severity="warning",
                source="provenance",
            ))
        if not contributions:
            reasons.append(RiskReason(
                code="NO_USABLE_SIGNALS",
                message="Bundle carries no synthetic or speaker signal; no score computed.",
                severity="warning",
                source="fusion",
            ))
            risk_score = None
            confidence = None
        else:
            total_weight = sum(weight for weight, _ in contributions)
            risk_score = round(
                max(0.0, min(100.0,
                    sum(weight * risk for weight, risk in contributions) / total_weight
                )),
                2,
            )
            confidence = 0.8 if len(contributions) == 2 else 0.5

        assessment = RiskAssessment(
            session_id=signals.session_id,
            chunk_id=signals.chunk_id,
            risk_score=risk_score,
            risk_level=risk_level_for(risk_score),
            confidence=confidence,
            synthetic_probability=synthetic_probability,
            speaker_consistency=consistency,
            context_risk=context_risk,
            reasons=tuple(reasons),
            provenance=RiskProvenance(
                detector_version=signals.synthetic.model_version
                    if signals.synthetic else None,
                embedder_version=signals.speaker.model_version
                    if signals.speaker else None,
                similarity_version=signals.similarity.model_version
                    if signals.similarity else None,
                reference_id=signals.similarity.reference_id
                    if signals.similarity else "",
                is_mock=mock,
            ),
            is_mock=mock,
            processing_time_ms=round((time.perf_counter() - start) * 1000.0, 3),
        )
        log.info(
            "assess session=%s chunk=%s score=%s level=%s mock=%s",
            assessment.session_id, assessment.chunk_id,
            assessment.risk_score, assessment.risk_level, mock,
        )
        return assessment
