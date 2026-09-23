"""Backend 4 Part 4: application / orchestration service (in-process only).

Connects the existing layers into one call::

    B2 chunk
        |
        v
    ProfileStore            (reference lookup, owner-aware when owner given)
        |
        v
    Backend3Pipeline        (detection + embedding + optional similarity)
        |
        v
    RiskFusionEngine        (Backend3Signals -> RiskAssessment)
        |
        v
    to_risk_update          (RiskAssessment -> frontend-compatible dict)

"Backend 3 produces ML signals. Backend 4 decides application risk."
This service orchestrates; it implements no detection, embedding,
similarity, fusion or transport math itself. No REST, WebSocket,
database or auth here -- those are later transport concerns.

Reference semantics (exactly three cases):
    A. ``reference_id`` given and resolvable -> its embedding and ID flow
       into B3; similarity participates in fusion.
    B. ``reference_id`` given but unresolvable (missing OR wrong owner,
       indistinguishable by design) -> controlled ``ValidationError``;
       never silently degraded to case C.
    C. ``reference_id`` omitted -> B3 runs without a reference; similarity
       stays None and fusion renormalizes over usable signals.

Owner semantics: an explicit ``owner_id`` selects owner-aware lookup.
Without it, internal lookup applies -- which matches current trusted
in-process use, but external transport MUST eventually require an
authenticated owner identity. ``owner_id`` never appears in results.

Provenance and mock handling:
    The B3 similarity result stays authoritative for similarity scores and
    the current encoder version; the profile store stays authoritative for
    the reference's embedder version and mock flag. When a reference is
    used, a ``REFERENCE_PROVENANCE`` reason records both sides explicitly.
    Final ``is_mock`` = B3 bundle mock state OR reference mock state: a
    mock reference can never vanish behind non-mock current signals. Mock
    outputs are development-only and must never reach production alerting.

Timestamps: explicit ``timestamp`` wins; otherwise the chunk's own
``timestamp_s`` (dict key or attribute) is reused -- never invented.
Without either, a ``ValidationError`` is raised rather than fabricating
call timing.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Union

from backend.b4_schemas import RiskAssessment, RiskReason
from backend.config import Settings, get_settings
from backend.pipeline import Backend3Pipeline
from backend.profile_store import ProfileStore, ReferenceVector
from backend.risk_engine import RiskFusionEngine
from backend.risk_update import to_risk_update
from backend.schemas import ValidationError

log = logging.getLogger(__name__)

ChunkInput = Union[Any, dict]


@dataclass(frozen=True)
class Backend4Result:
    """Public application result: assessment + wire dict + provenance.

    Contains no audio, no embeddings, no profile records and no owner
    identity; fully JSON-serializable via ``to_dict()``.

    ``signals`` carries the source ``Backend3Signals`` for internal
    consumers (e.g. evidence builders needing raw similarity values).
    It is deliberately excluded from ``to_dict()`` and ``repr()`` so the
    public representation can never leak vectors.
    """

    assessment: RiskAssessment
    risk_update: dict
    provenance: Any
    signals: Any = None

    def to_dict(self) -> dict:
        return {
            "assessment": self.assessment.to_dict(),
            "risk_update": dict(self.risk_update),
            "provenance": self.provenance.to_dict(),
        }

    def __repr__(self) -> str:  # privacy: never render nested signals/vectors
        return (
            f"Backend4Result(session={self.assessment.session_id!r}, "
            f"chunk={self.assessment.chunk_id!r}, "
            f"score={self.assessment.risk_score}, "
            f"level={self.assessment.risk_level!r}, "
            f"mock={self.assessment.is_mock})"
        )


class Backend4Service:
    """Thin orchestration over B3 pipeline + profile store + risk engine."""

    def __init__(
        self,
        settings: Settings | None = None,
        pipeline: Backend3Pipeline | None = None,
        profile_store: ProfileStore | None = None,
        risk_engine: RiskFusionEngine | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        # NOTE: explicit None checks (never `or`): injected fakes/doubles
        # may define __len__/__bool__ and must never be replaced.
        self._pipeline = pipeline if pipeline is not None else Backend3Pipeline(self.settings)
        self._profiles = profile_store if profile_store is not None else ProfileStore()
        self._risk_engine = risk_engine if risk_engine is not None else RiskFusionEngine()

    # -- enrollment delegation (domain only; no audio, no analysis) --

    def enroll_reference(self, reference_id: str, owner_id: str,
                         embedding: Any, embedder_version: str,
                         is_mock: bool):
        """Delegate enrollment to the profile store (validation inside)."""
        return self._profiles.enroll_reference(
            reference_id=reference_id, owner_id=owner_id,
            embedding=embedding, embedder_version=embedder_version,
            is_mock=is_mock)

    def get_reference_metadata(self, reference_id: str, owner_id: str | None = None):
        """Delegate metadata lookup (owner-aware when owner_id is given)."""
        if owner_id is not None:
            return self._profiles.get_metadata_for_owner(reference_id, owner_id)
        return self._profiles.get_metadata(reference_id)

    def delete_reference(self, reference_id: str) -> bool:
        """Delegate deletion to the profile store."""
        return self._profiles.delete_reference(reference_id)

    # -- main flow --

    def process_chunk(
        self,
        chunk: ChunkInput,
        owner_id: str | None = None,
        reference_id: str | None = None,
        timestamp: float | None = None,
    ) -> Backend4Result:
        """Run one chunk end to end and return the application result.

        Raises:
            ValidationError: unresolvable reference, malformed chunk,
                scoreless bundle, missing/unusable timestamp.
            ModelError: B3 inference failure (propagated untouched).
        """
        reference = self._resolve_reference(reference_id, owner_id)
        signals = self._pipeline.process_chunk(
            chunk,
            reference_embedding=reference.embedding if reference else None,
            reference_id=reference.reference_id if reference else None,
        )
        assessment = self._risk_engine.assess(signals)
        assessment = self._apply_reference_provenance(assessment, reference)
        update = to_risk_update(
            assessment, timestamp=self._resolve_timestamp(chunk, timestamp))
        result = Backend4Result(
            assessment=assessment, risk_update=update,
            provenance=assessment.provenance, signals=signals)
        log.info(
            "b4 session=%s chunk=%s score=%s level=%s mock=%s",
            assessment.session_id, assessment.chunk_id,
            assessment.risk_score, assessment.risk_level, assessment.is_mock)
        return result

    def _resolve_reference(
        self, reference_id: str | None, owner_id: str | None
    ) -> ReferenceVector | None:
        if reference_id is None:
            return None
        if owner_id is not None:
            return self._profiles.get_reference_vector_for_owner(reference_id, owner_id)
        # Internal/trusted lookup. External transport MUST require owner_id;
        # see module docstring. Store errors stay controlled ValidationErrors
        # with no embedding or owner details.
        return self._profiles.get_reference_vector(reference_id)

    def _apply_reference_provenance(
        self, assessment: RiskAssessment, reference: ReferenceVector | None
    ) -> RiskAssessment:
        if reference is None:
            return assessment
        reasons = list(assessment.reasons) + [RiskReason(
            code="REFERENCE_PROVENANCE",
            message=f"Reference '{reference.reference_id}' enrolled with "
                    f"{reference.embedder_version} (mock={reference.is_mock}).",
            severity="info",
            source="provenance",
        )]
        if reference.is_mock and not assessment.is_mock:
            # A mock reference must taint the final assessment even when the
            # current B3 signals are non-mock. Reuse the existing reason code.
            reasons.append(RiskReason(
                code="MOCK_MODEL_SIGNAL",
                message="The enrolled reference came from a development/mock "
                        "model; this assessment is not production evidence.",
                severity="warning",
                source="provenance",
            ))
            return RiskAssessment(
                session_id=assessment.session_id, chunk_id=assessment.chunk_id,
                risk_score=assessment.risk_score, risk_level=assessment.risk_level,
                confidence=assessment.confidence,
                synthetic_probability=assessment.synthetic_probability,
                speaker_consistency=assessment.speaker_consistency,
                context_risk=assessment.context_risk,
                reasons=tuple(reasons), provenance=assessment.provenance,
                is_mock=True, processing_time_ms=assessment.processing_time_ms)
        return RiskAssessment(
            session_id=assessment.session_id, chunk_id=assessment.chunk_id,
            risk_score=assessment.risk_score, risk_level=assessment.risk_level,
            confidence=assessment.confidence,
            synthetic_probability=assessment.synthetic_probability,
            speaker_consistency=assessment.speaker_consistency,
            context_risk=assessment.context_risk,
            reasons=tuple(reasons), provenance=assessment.provenance,
            is_mock=assessment.is_mock,
            processing_time_ms=assessment.processing_time_ms)

    @staticmethod
    def _resolve_timestamp(chunk: ChunkInput, timestamp: float | None) -> float:
        if timestamp is not None:
            return timestamp
        if isinstance(chunk, dict):
            candidate = chunk.get("timestamp_s")
        else:
            candidate = getattr(chunk, "timestamp_s", None)
        if candidate is None:
            raise ValidationError(
                "No timestamp supplied and chunk carries no timestamp_s; "
                "refusing to fabricate call timing.")
        return candidate


# Convenience functional entry point (uses process-wide singletons).
_service_lock = threading.Lock()
_service_instance: "Backend4Service | None" = None


def get_b4_service() -> Backend4Service:
    """Return the process-wide reusable service (creates it on first use)."""
    global _service_instance
    if _service_instance is not None:
        return _service_instance
    with _service_lock:
        if _service_instance is not None:
            return _service_instance
        _service_instance = Backend4Service()
        log.info("Backend4Service ready.")
        return _service_instance


def reset_b4_service() -> None:
    """Test helper: drop the cached process-wide service."""
    global _service_instance
    with _service_lock:
        _service_instance = None
