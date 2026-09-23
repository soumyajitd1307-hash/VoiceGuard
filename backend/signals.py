"""Backend 3 -> Backend 4 signal boundary (passive evidence carrier, no risk logic).

Backend 3 provides ML signals; Backend 4 consumes them. This module builds
the single stable bundle -- ``Backend3Signals`` (see backend/schemas.py) --
from the existing Part 1-3 result objects:

    DetectionResult          (synthetic voice detection)
    SpeakerEmbeddingResult   (speaker embedding)
    SimilarityResult         (reference comparison)

WHAT THIS MODULE DOES NOT DO (Backend 4 owns all of it):
    risk scores, risk levels, scam/impersonation/trust verdicts, combining
    ``synthetic_probability`` and ``similarity`` into any new number,
    profile storage, enrollment, alerts, evidence, persistence.

Session/chunk integrity:
    The B2 identifiers travel through untouched. Results from different
    sessions (or chunks) are never merged -- mismatches raise
    ``ValidationError`` instead of producing a corrupt bundle.

Optional signals:
    Any subset may be present (detection-only, embedding-only,
    similarity-only, or all three). Absent signals are None, never
    fabricated zeros. At least one signal is required.

Provenance and mock safety:
    Every nested signal keeps its own ``model_version`` and ``is_mock``;
    mock inputs can never leave this module looking like production
    evidence. ``metadata.processing_time_ms`` is the SUM of the nested
    per-signal timings (provenance bookkeeping, not a risk feature).

Embedding privacy:
    Embeddings are biometric-derived and sensitive. The bundle never logs
    vector contents (only session/chunk IDs and dimensions), nothing here
    persists anything, and ``to_dict(include_embedding=False)`` withholds
    the raw vector (flagged ``embedding_withheld: True``) for consumers
    that only need similarity. Backend 4 must not log or store embeddings
    casually either.

Example (how Backend 4 consumes the contract)::

    from backend.signals import build_backend3_signals

    signals = build_backend3_signals(
        detection_result=detector.detect_chunk(chunk),   # or None
        embedding_result=embedder.embed(chunk),          # or None
        similarity_result=similarity.compare(ref, cur),  # or None
    )
    payload = signals.to_dict(include_embedding=False)  # similarity-only path
    assert payload["synthetic"]["is_mock"] is True       # mock visible to B4
    risk = backend4_score(payload)  # Backend 4's logic, NOT here.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Union

from backend.schemas import (
    Backend3Signals,
    DetectionResult,
    SimilarityResult,
    SpeakerEmbeddingResult,
    ValidationError,
)

log = logging.getLogger(__name__)

DetectionInput = Union[DetectionResult, dict, None]
EmbeddingInput = Union[SpeakerEmbeddingResult, dict, None]
SimilarityInput = Union[SimilarityResult, dict, None]

_VALID_LABELS = ("real", "synthetic", "uncertain")
_VALID_MATCHES = ("match", "non_match", "uncertain")


def build_backend3_signals(
    detection_result: DetectionInput = None,
    embedding_result: EmbeddingInput = None,
    similarity_result: SimilarityInput = None,
) -> Backend3Signals:
    """Combine Backend 3 results into one validated, serializable bundle.

    Raises:
        ValidationError: no signals supplied, wrong object types, malformed
            dicts, session/chunk mismatch, dimension mismatch, out-of-range
            probability/similarity, non-boolean mock flags.
    """
    synthetic = _coerce_detection(detection_result)
    speaker = _coerce_embedding(embedding_result)
    similarity = _coerce_similarity(similarity_result)
    if synthetic is None and speaker is None and similarity is None:
        raise ValidationError("At least one signal result is required.")
    parts = [part for part in (synthetic, speaker, similarity) if part is not None]
    session_ids = {part.session_id for part in parts}
    if len(session_ids) != 1:
        raise ValidationError(
            f"Refusing to merge signals from different sessions: {sorted(session_ids)}."
        )
    chunk_ids = {part.chunk_id for part in parts}
    if len(chunk_ids) != 1:
        raise ValidationError(
            f"Refusing to merge signals from different chunks: {sorted(chunk_ids)}."
        )
    bundle = Backend3Signals(
        session_id=parts[0].session_id,
        chunk_id=parts[0].chunk_id,
        synthetic=synthetic,
        speaker=speaker,
        similarity=similarity,
    )
    log.info(
        "signals session=%s chunk=%s synthetic=%s speaker=%s similarity=%s",
        bundle.session_id, bundle.chunk_id,
        synthetic.label if synthetic else "-",
        f"dim={speaker.dimension}" if speaker else "-",
        similarity.match if similarity else "-",
    )
    return bundle


def _require_type(value: Any, role: str, expected: type) -> dict:
    if isinstance(value, expected):
        return value.to_dict()
    if isinstance(value, dict):
        return value
    raise ValidationError(
        f"{role} must be a {expected.__name__} or dict (got {type(value).__name__})."
    )


def _check_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.")
    return value.strip()


def _check_probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("synthetic_probability must be a number.")
    f = float(value)
    if math.isnan(f) or math.isinf(f) or not 0.0 <= f <= 1.0:
        raise ValidationError(f"synthetic_probability={value!r} must lie in [0.0, 1.0].")
    return f


def _check_similarity(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("similarity must be a number.")
    f = float(value)
    if math.isnan(f) or math.isinf(f) or not -1.0 <= f <= 1.0:
        raise ValidationError(f"similarity={value!r} must lie in [-1.0, 1.0].")
    return f


def _check_mock(value: Any, role: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{role}.is_mock must be a boolean.")
    return value


def _check_number(value: Any, field: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field} must be a number.")
    f = float(value)
    if math.isnan(f) or math.isinf(f):
        raise ValidationError(f"{field} must be finite.")
    if minimum is not None and f < minimum:
        raise ValidationError(f"{field} must be >= {minimum}.")
    return f


def _coerce_detection(value: DetectionInput) -> DetectionResult | None:
    if value is None:
        return None
    payload = _require_type(value, "detection_result", DetectionResult)
    for key in ("label", "synthetic_probability", "model_version",
                "processing_time_ms", "session_id", "chunk_id", "is_mock"):
        if key not in payload:
            raise ValidationError(f"detection_result dict is missing '{key}'.")
    if payload["label"] not in _VALID_LABELS:
        raise ValidationError(f"Invalid detection label {payload['label']!r}.")
    return DetectionResult(
        label=payload["label"],
        synthetic_probability=_check_probability(payload["synthetic_probability"]),
        model_version=_check_id(payload["model_version"], "detection model_version"),
        processing_time_ms=_check_number(payload["processing_time_ms"], "processing_time_ms", 0.0),
        session_id=_check_id(payload["session_id"], "session_id"),
        chunk_id=_check_id(payload["chunk_id"], "chunk_id"),
        is_mock=_check_mock(payload["is_mock"], "detection_result"),
    )


def _coerce_embedding(value: EmbeddingInput) -> SpeakerEmbeddingResult | None:
    if value is None:
        return None
    payload = _require_type(value, "embedding_result", SpeakerEmbeddingResult)
    for key in ("session_id", "chunk_id", "embedding", "dimension",
                "model_version", "is_mock", "processing_time_ms"):
        if key not in payload:
            raise ValidationError(f"embedding_result dict is missing '{key}'.")
    raw = payload["embedding"]
    if not isinstance(raw, (tuple, list)) or len(raw) == 0:
        raise ValidationError("embedding must be a non-empty sequence.")
    vector = []
    for idx, item in enumerate(raw):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValidationError(f"embedding[{idx}] must be a number.")
        f = float(item)
        if math.isnan(f) or math.isinf(f):
            raise ValidationError(f"embedding[{idx}] must be finite.")
        vector.append(f)
    dimension = payload["dimension"]
    if not isinstance(dimension, int) or isinstance(dimension, bool):
        raise ValidationError("dimension must be an integer.")
    if dimension != len(vector):
        raise ValidationError(
            f"Embedding dim mismatch: dimension={dimension} but len={len(vector)}."
        )
    return SpeakerEmbeddingResult(
        session_id=_check_id(payload["session_id"], "session_id"),
        chunk_id=_check_id(payload["chunk_id"], "chunk_id"),
        embedding=tuple(vector),
        dimension=dimension,
        model_version=_check_id(payload["model_version"], "embedding model_version"),
        is_mock=_check_mock(payload["is_mock"], "embedding_result"),
        processing_time_ms=_check_number(payload["processing_time_ms"], "processing_time_ms", 0.0),
    )


def _coerce_similarity(value: SimilarityInput) -> SimilarityResult | None:
    if value is None:
        return None
    payload = _require_type(value, "similarity_result", SimilarityResult)
    for key in ("reference_id", "session_id", "chunk_id", "similarity",
                "threshold", "match", "model_version", "is_mock", "processing_time_ms"):
        if key not in payload:
            raise ValidationError(f"similarity_result dict is missing '{key}'.")
    if payload["match"] not in _VALID_MATCHES:
        raise ValidationError(f"Invalid match label {payload['match']!r}.")
    threshold = payload["threshold"]
    if threshold is not None:
        threshold = _check_similarity(threshold)
    reference_id = payload["reference_id"]
    if reference_id is not None and not isinstance(reference_id, str):
        raise ValidationError("reference_id must be a string or null.")
    return SimilarityResult(
        reference_id=(reference_id or ""),
        session_id=_check_id(payload["session_id"], "session_id"),
        chunk_id=_check_id(payload["chunk_id"], "chunk_id"),
        similarity=_check_similarity(payload["similarity"]),
        threshold=threshold,
        match=payload["match"],
        model_version=_check_id(payload["model_version"], "similarity model_version"),
        is_mock=_check_mock(payload["is_mock"], "similarity_result"),
        processing_time_ms=_check_number(payload["processing_time_ms"], "processing_time_ms", 0.0),
    )
