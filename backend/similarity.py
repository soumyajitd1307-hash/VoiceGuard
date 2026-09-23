"""Backend 3 Part 3: speaker similarity over embedding vectors.

Pipeline position::

    reference embedding (Backend 4 voice profile, future)
            +
    current embedding (SpeakerEmbeddingResult from backend/embeddings.py)
            v
    SpeakerSimilarityService.compare (this module: pure cosine math)
            v
    SimilarityResult (backend/schemas.py, consumed by Backend 4)

Metric: cosine similarity, general formula::

    cosine(A, B) = dot(A, B) / (norm(A) * norm(B))

    The embedding service emits L2 unit-norm vectors, for which this is
    numerically equivalent to the dot product; the general formula is
    implemented (not the shortcut) so non-unit inputs score correctly.
    Zero vectors are rejected (no division by zero); inputs are never
    silently renormalised -- malformed vectors raise, bad model output
    is never hidden.

MOCK LIMITATION (do not ignore):
    The wired encoder is ``MockSpectralEmbedder`` -- explicitly NOT a real
    speaker encoder. Therefore mock-embedding similarity is NOT speaker
    verification: it must never be read as "same person" / "verified".
    ``SimilarityResult.is_mock`` is True whenever either input is mock
    (or of unknown provenance), and ``match`` is only an operating-point
    comparison, never a validated identity decision. Real verification
    requires a trained encoder + Part 4 threshold evaluation.

Threshold behaviour (no hardcoded "scientific" threshold):
    * Threshold resolution: explicit ``compare(threshold=...)`` argument,
      else the service default (constructor arg, else
      ``Settings.similarity_threshold`` / ``VG_SIMILARITY_THRESHOLD``),
      else None.
    * None -> ``match="uncertain"`` (raw score preserved, no decision).
    * Set -> ``similarity >= threshold`` is "match" (inclusive boundary),
      else "non_match". The threshold is an unevaluated operating
      parameter until Part 4 selects it.

Version handling:
    Dimension equality is the hard compatibility gate (mismatch raises).
    If both inputs carry embedding model versions and they differ, the
    comparison still runs -- this repo has no cross-version compatibility
    registry -- and the CURRENT embedding's version is recorded. Treat
    cross-version scores as non-comparable; this limitation is documented
    rather than silently resolved.

Reference IDs are caller-supplied metadata (future Backend 4 voice-profile
keys). No profile storage, enrollment, database or risk logic lives here.

This service is stateless pure math: no model to load, no registry, no
weights. Instances are cheap; reuse is optional, not required.

Example (how Backend 4 will eventually consume it)::

    from backend.similarity import SpeakerSimilarityService

    service = SpeakerSimilarityService()  # threshold from VG_SIMILARITY_THRESHOLD
    result = service.compare(
        reference=profile_embedding,   # stored voice-profile vector
        current=current_result,        # SpeakerEmbeddingResult for this chunk
        reference_id="usr-1042",
    )
    if not result.is_mock and result.match == "non_match":
        ...  # Backend 4 risk logic (NOT here)
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Sequence
from typing import Any, Union

from backend.config import Settings, get_settings
from backend.schemas import MatchLabel, SimilarityResult, SpeakerEmbeddingResult, ValidationError

log = logging.getLogger(__name__)

VectorInput = Union[SpeakerEmbeddingResult, Sequence[Any], dict]


class SpeakerSimilarityService:
    """Stateless cosine-similarity comparison for speaker embeddings."""

    def __init__(self, settings: Settings | None = None, threshold: float | None = None) -> None:
        self.settings = settings or get_settings()
        # Explicit arg wins; else configured default; else None (= uncertain).
        self.default_threshold = (
            threshold if threshold is not None else self.settings.similarity_threshold
        )
        if self.default_threshold is not None and not -1.0 <= self.default_threshold <= 1.0:
            raise ValueError(
                f"similarity threshold must lie in [-1.0, 1.0] (got {self.default_threshold})"
            )

    def compare(
        self,
        reference: VectorInput,
        current: VectorInput,
        reference_id: str | None = None,
        session_id: str | None = None,
        chunk_id: str | None = None,
        threshold: float | None = None,
        model_version: str | None = None,
        is_mock: bool | None = None,
    ) -> SimilarityResult:
        """Compare a reference vector against the current chunk vector.

        Args:
            reference: enrolment vector (raw sequence, ``{"embedding": [...]}``
                dict, or ``SpeakerEmbeddingResult``).
            current: live-chunk vector (same accepted forms).
            reference_id: voice-profile key (metadata only). Defaults to "".
            session_id/chunk_id: default to the CURRENT result's IDs when it
                is a ``SpeakerEmbeddingResult``, else "".
            threshold: operating point override; None falls back to the
                service default; still None -> ``match="uncertain"``.
            model_version: override; defaults to the CURRENT result's
                version, else the reference's, else "unknown".
            is_mock: override; defaults to True if either input result is
                mock, True for raw/provenance-unknown inputs.

        Raises:
            ValidationError: missing/empty/mismatched/non-numeric vectors,
                NaN/inf values, zero vectors, bad IDs, bad threshold.
        """
        start = time.perf_counter()
        ref_vec, ref_meta = _coerce_vector(reference, "reference")
        cur_vec, cur_meta = _coerce_vector(current, "current")
        if len(ref_vec) != len(cur_vec):
            raise ValidationError(
                f"Embedding dim mismatch: reference={len(ref_vec)} current={len(cur_vec)}."
            )
        similarity = _cosine(ref_vec, cur_vec)

        active_threshold = threshold if threshold is not None else self.default_threshold
        if active_threshold is not None and not -1.0 <= active_threshold <= 1.0:
            raise ValidationError(
                f"threshold must lie in [-1.0, 1.0] (got {active_threshold})."
            )
        match: MatchLabel
        if active_threshold is None:
            match = "uncertain"
        elif similarity >= active_threshold:
            match = "match"
        else:
            match = "non_match"

        resolved_ref_id = _clean_optional_id(reference_id, "reference_id", self.settings.max_id_length)
        resolved_session = session_id if session_id is not None else cur_meta[0]
        resolved_chunk = chunk_id if chunk_id is not None else cur_meta[1]
        resolved_version = model_version or cur_meta[2] or ref_meta[2] or "unknown"
        if ref_meta[2] and cur_meta[2] and ref_meta[2] != cur_meta[2]:
            log.warning(
                "Cross-version similarity: reference=%s current=%s; "
                "scores are not validated as comparable.",
                ref_meta[2], cur_meta[2],
            )
        if is_mock is None:
            is_mock = ref_meta[3] or cur_meta[3]

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        result = SimilarityResult(
            reference_id=resolved_ref_id,
            session_id=resolved_session,
            chunk_id=resolved_chunk,
            similarity=round(similarity, 6),
            threshold=active_threshold,
            match=match,
            model_version=resolved_version,
            is_mock=is_mock,
            processing_time_ms=round(elapsed_ms, 3),
        )
        log.info(
            "compare ref=%s session=%s chunk=%s sim=%.4f match=%s mock=%s",
            result.reference_id or "-", result.session_id, result.chunk_id,
            similarity, match, is_mock,
        )
        return result


def _coerce_vector(value: VectorInput, role: str) -> tuple[tuple, tuple]:
    """Return (floats tuple, (session_id, chunk_id, version, is_mock))."""
    if isinstance(value, SpeakerEmbeddingResult):
        raw: Any = value.embedding
        meta = (value.session_id, value.chunk_id, value.model_version, bool(value.is_mock))
    elif isinstance(value, dict):
        if "embedding" not in value:
            raise ValidationError(f"{role} dict must contain an 'embedding' key.")
        raw = value["embedding"]
        meta = (
            str(value.get("session_id", "") or ""),
            str(value.get("chunk_id", "") or ""),
            str(value.get("model_version", "") or ""),
            bool(value.get("is_mock", True)),
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        raw = value
        meta = ("", "", "", True)  # raw vectors: provenance unknown -> mock
    else:
        raise ValidationError(
            f"{role} must be a SpeakerEmbeddingResult, embedding dict, or float sequence "
            f"(got {type(value).__name__})."
        )
    try:
        items = list(raw)
    except TypeError:
        raise ValidationError(f"{role} embedding is not a sequence.") from None
    if len(items) == 0:
        raise ValidationError(f"{role} embedding must contain at least one value.")
    out = []
    for idx, item in enumerate(items):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValidationError(f"{role} embedding[{idx}] must be a number.")
        f = float(item)
        if math.isnan(f):
            raise ValidationError(f"{role} embedding[{idx}] is NaN.")
        if math.isinf(f):
            raise ValidationError(f"{role} embedding[{idx}] is infinite.")
        out.append(f)
    return tuple(out), meta


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        raise ValidationError("Cannot score a zero embedding vector (zero norm).")
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


def _clean_optional_id(value: str | None, field: str, max_len: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string.")
    cleaned = value.strip()
    if len(cleaned) > max_len:
        raise ValidationError(f"{field} exceeds max length {max_len}.")
    return cleaned


# Convenience functional entry point (stateless; no singleton required).
def compare_similarity(
    reference: VectorInput,
    current: VectorInput,
    reference_id: str | None = None,
    session_id: str | None = None,
    chunk_id: str | None = None,
    threshold: float | None = None,
) -> SimilarityResult:
    return SpeakerSimilarityService().compare(
        reference=reference,
        current=current,
        reference_id=reference_id,
        session_id=session_id,
        chunk_id=chunk_id,
        threshold=threshold,
    )
