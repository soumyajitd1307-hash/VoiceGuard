"""Backend 2 -> Backend 3 handoff adapter.

Invokes Backend 3's in-process ML pipeline or detector using
the validated ProcessedSpeechChunk produced by Backend 2.
"""
from __future__ import annotations

from typing import Union

from backend.b2_contract import ProcessedSpeechChunk, validate_chunk
from backend.config import Settings
from backend.detector import SyntheticVoiceDetector, detect_chunk, get_detector
from backend.pipeline import Backend3Pipeline, get_pipeline, process_chunk
from backend.schemas import Backend3Signals, DetectionResult
from backend.similarity import VectorInput

HandoffResult = Union[Backend3Signals, DetectionResult]


def handoff_to_b3(
    chunk: ProcessedSpeechChunk,
    reference_embedding: VectorInput | None = None,
    reference_id: str | None = None,
    pipeline: Backend3Pipeline | None = None,
    settings: Settings | None = None,
) -> Backend3Signals:
    """Forward a ProcessedSpeechChunk to Backend 3's runtime pipeline.

    Invokes Backend 3's process_chunk in-process, returning the complete
    Backend3Signals bundle containing detection, speaker embedding, and
    optional similarity results for Backend 4.

    Args:
        chunk: Validated ProcessedSpeechChunk from Backend 2.
        reference_embedding: Optional enrolled speaker vector for similarity comparison.
        reference_id: Optional voice-profile key for the reference embedding.
        pipeline: Optional injected Backend3Pipeline instance (uses process-wide default if None).
        settings: Optional Settings instance used if pre-validating the chunk.

    Returns:
        Backend3Signals bundle produced by Backend 3.

    Raises:
        TypeError: If chunk is not a ProcessedSpeechChunk.
        ValidationError: If chunk fails B3 validation or VAD is_speech=False.
        ModelError: If Backend 3 ML model inference fails.
    """
    if not isinstance(chunk, ProcessedSpeechChunk):
        raise TypeError(
            f"chunk must be a ProcessedSpeechChunk, got {type(chunk).__name__}."
        )

    validated = validate_chunk(chunk, settings=settings)

    if pipeline is not None:
        return pipeline.process_chunk(
            validated,
            reference_embedding=reference_embedding,
            reference_id=reference_id,
        )

    return process_chunk(
        validated,
        reference_embedding=reference_embedding,
        reference_id=reference_id,
    )


def detect_with_b3(
    chunk: ProcessedSpeechChunk,
    detector: SyntheticVoiceDetector | None = None,
    settings: Settings | None = None,
) -> DetectionResult:
    """Forward a ProcessedSpeechChunk directly to Backend 3's synthetic voice detector.

    Convenience adapter when only synthetic voice detection (DetectionResult)
    is required rather than the full Backend3Signals bundle.

    Args:
        chunk: Validated ProcessedSpeechChunk from Backend 2.
        detector: Optional injected SyntheticVoiceDetector instance.
        settings: Optional Settings instance used if pre-validating the chunk.

    Returns:
        DetectionResult containing label, synthetic_probability, and metadata.

    Raises:
        TypeError: If chunk is not a ProcessedSpeechChunk.
        ValidationError: If chunk fails B3 validation or VAD is_speech=False.
        ModelError: If Backend 3 ML model inference fails.
    """
    if not isinstance(chunk, ProcessedSpeechChunk):
        raise TypeError(
            f"chunk must be a ProcessedSpeechChunk, got {type(chunk).__name__}."
        )

    validated = validate_chunk(chunk, settings=settings)

    if detector is not None:
        return detector.detect_chunk(validated)

    return detect_chunk(validated)
