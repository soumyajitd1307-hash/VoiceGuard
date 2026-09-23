"""Packaging layer for Backend 2.

Combines PreprocessedAudioWindow, VADResult, and chunk metadata into
the existing Backend 3 ProcessedSpeechChunk handoff contract.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from backend.b2_contract import ProcessedSpeechChunk, validate_chunk
from backend.config import Settings
from backend2.preprocessing import PreprocessedAudioWindow
from backend2.vad import VADResult

if TYPE_CHECKING:
    pass


def build_processed_speech_chunk(
    window: PreprocessedAudioWindow,
    vad_result: VADResult,
    chunk_id: str,
    timestamp_s: float | None = None,
    language: str | None = None,
    audio_encoding: str = "auto",
    validate: bool = True,
    settings: Settings | None = None,
) -> ProcessedSpeechChunk:
    """Package a preprocessed window and VAD result into a ProcessedSpeechChunk.

    Args:
        window: Validated audio window containing normalized float samples and session_id.
        vad_result: Voice Activity Detection result providing is_speech and speech_ratio.
        chunk_id: Explicit chunk identifier within the session (e.g. 'c0001').
        timestamp_s: Optional call-relative start time in seconds (>= 0.0).
        language: Optional language label (e.g. 'en').
        audio_encoding: Audio encoding format ('auto' for normalized float sequences or PCM16 bytes).
        validate: Whether to run B3's validate_chunk on the created chunk (default True).
        settings: Optional custom Settings instance for validation.

    Returns:
        Validated ProcessedSpeechChunk ready for handoff to Backend 3.

    Raises:
        ValidationError: If any field violates the Backend 3 contract.
        TypeError: If window or vad_result are of incorrect types.
    """
    if not isinstance(window, PreprocessedAudioWindow):
        raise TypeError(
            f"window must be a PreprocessedAudioWindow, got {type(window).__name__}."
        )
    if not isinstance(vad_result, VADResult):
        raise TypeError(
            f"vad_result must be a VADResult, got {type(vad_result).__name__}."
        )

    chunk = ProcessedSpeechChunk(
        audio=window.samples,
        sample_rate=window.sample_rate,
        session_id=window.session_id,
        chunk_id=chunk_id,
        audio_encoding=audio_encoding,
        timestamp_s=timestamp_s,
        language=language,
        is_speech=vad_result.is_speech,
        speech_ratio=vad_result.speech_ratio,
    )

    if validate:
        return validate_chunk(chunk, settings=settings)
    return chunk
