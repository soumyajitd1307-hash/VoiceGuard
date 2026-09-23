"""Backend 3 runtime orchestration: one chunk in, one signal bundle out.

Flow::

    B2: ProcessedSpeechChunk (or equivalent dict)
            |
            +--> SyntheticVoiceDetector.detect_chunk      (always)
            |
            +--> SpeakerEmbeddingService.embed            (always)
            |
            +--> SpeakerSimilarityService.compare        (ONLY when a
                 reference embedding is explicitly supplied)
            |
            v
    build_backend3_signals(...) -> Backend3Signals -> Backend 4

"Backend 3 produces ML signals. It does not calculate application risk."

This layer orchestrates existing components only. It duplicates no
validation, audio normalisation, cosine math, model loading, schemas or
error classes: every step delegates to the tested Part 1-4 modules, whose
``ValidationError`` / ``ModelError`` propagate to the caller untouched.
No ML error is swallowed and no fake result is ever returned.

Reference-embedding rule:
    Similarity is computed if and ONLY if ``reference_embedding`` is
    explicitly supplied. Without it the bundle carries
    ``similarity=None``. The pipeline never compares against a zero
    vector, never compares the chunk against itself, never invents a
    reference, never fabricates a ``reference_id`` and never assumes the
    caller is any particular speaker. ``reference_id`` is opaque metadata
    passed through to the similarity result; enrollment and profile
    lifecycle belong to Backend 4.

Timing and provenance:
    Processing times are reused from the nested result objects and
    aggregated by ``build_backend3_signals``; no second timing system
    exists here and timing is never treated as a risk signal. ``is_mock``,
    ``model_version``, ``reference_id``, ``session_id`` and ``chunk_id``
    pass through unchanged; mock outputs are never made to look like
    production evidence.

Privacy:
    Raw embedding vectors are never logged or printed here (only
    session/chunk IDs, dimensions and match labels). Nothing is persisted.

Example::

    from backend.pipeline import Backend3Pipeline

    pipeline = Backend3Pipeline()  # reuse: models load once per process
    signals = pipeline.process_chunk(chunk)  # detection + embedding
    with_reference = pipeline.process_chunk(
        chunk,
        reference_embedding=enrolled_vector,  # explicit profile vector
        reference_id="usr-1042",
    )
"""
from __future__ import annotations

import logging
import threading
from typing import Union

from backend.b2_contract import ProcessedSpeechChunk
from backend.config import Settings, get_settings
from backend.detector import SyntheticVoiceDetector
from backend.embeddings import SpeakerEmbeddingService
from backend.schemas import Backend3Signals
from backend.signals import build_backend3_signals
from backend.similarity import SpeakerSimilarityService, VectorInput

log = logging.getLogger(__name__)

ChunkInput = Union[ProcessedSpeechChunk, dict]

_pipeline_lock = threading.Lock()
_pipeline_instance: "Backend3Pipeline | None" = None


class Backend3Pipeline:
    """Small orchestration layer over the existing B3 components.

    Holds reusable sub-service instances (whose models are process-wide
    singletons, so construction is cheap and weights load once). Accepts
    injected sub-services for tests; otherwise builds them from settings.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        detector: SyntheticVoiceDetector | None = None,
        embedding_service: SpeakerEmbeddingService | None = None,
        similarity_service: SpeakerSimilarityService | None = None,
        min_speech_s: float | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._detector = detector or SyntheticVoiceDetector(self.settings)
        self._embedder = embedding_service or SpeakerEmbeddingService(
            self.settings, min_speech_s=min_speech_s
        )
        self._similarity = similarity_service or SpeakerSimilarityService(self.settings)

    def process_chunk(
        self,
        chunk: ChunkInput,
        reference_embedding: VectorInput | None = None,
        reference_id: str | None = None,
    ) -> Backend3Signals:
        """Run detection + embedding (+ optional similarity) for one chunk.

        Args:
            chunk: ``ProcessedSpeechChunk`` or equivalent wire dict.
            reference_embedding: explicitly supplied enrolment vector
                (``SpeakerEmbeddingResult``, embedding dict or raw
                sequence). None (default) means NO similarity is computed.
            reference_id: opaque voice-profile key, passed through only.

        Returns:
            ``Backend3Signals`` bundle for Backend 4.

        Raises:
            ValidationError: malformed chunk, VAD non-speech, insufficient
                speech, invalid reference embedding, session/chunk mismatch.
            ModelError: detector/encoder inference failure.
        """
        detection = self._detector.detect_chunk(chunk)
        embedding = self._embedder.embed(chunk)
        similarity = None
        if reference_embedding is not None:
            similarity = self._similarity.compare(
                reference=reference_embedding,
                current=embedding,
                reference_id=reference_id,
            )
        bundle = build_backend3_signals(
            detection_result=detection,
            embedding_result=embedding,
            similarity_result=similarity,
        )
        log.info(
            "pipeline session=%s chunk=%s label=%s similarity=%s",
            bundle.session_id, bundle.chunk_id,
            bundle.synthetic.label if bundle.synthetic else "-",
            bundle.similarity.match if bundle.similarity else "-",
        )
        return bundle


def get_pipeline() -> Backend3Pipeline:
    """Return the process-wide reusable pipeline (creates it on first use)."""
    global _pipeline_instance
    if _pipeline_instance is not None:
        return _pipeline_instance
    with _pipeline_lock:
        if _pipeline_instance is not None:
            return _pipeline_instance
        _pipeline_instance = Backend3Pipeline()
        log.info("Backend3Pipeline ready.")
        return _pipeline_instance


def reset_pipeline() -> None:
    """Test helper: drop the cached process-wide pipeline."""
    global _pipeline_instance
    with _pipeline_lock:
        _pipeline_instance = None


# Convenience functional entry point (uses the process-wide pipeline).
def process_chunk(
    chunk: ChunkInput,
    reference_embedding: VectorInput | None = None,
    reference_id: str | None = None,
) -> Backend3Signals:
    return get_pipeline().process_chunk(
        chunk, reference_embedding=reference_embedding, reference_id=reference_id
    )
