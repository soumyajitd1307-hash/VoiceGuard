"""Backend 2 — Audio Preprocessing, Buffering, and Feature Pipeline.

This package manages audio ingestion buffering, stream segmentation,
voice activity detection (VAD), and speech-ready handoff to Backend 3.
"""

from backend2.buffer import (
    AudioBufferError,
    BufferOverflowError,
    InvalidSessionError,
    SessionAudioBuffer,
    SessionBufferManager,
    get_buffer_manager,
    reset_buffer_manager,
)
from backend2.packaging import build_processed_speech_chunk
from backend2.preprocessing import (
    AudioValidationError,
    PreprocessedAudioWindow,
    extract_audio_window,
    preprocess_pcm16,
    validate_pcm16_audio,
)
from backend2.vad import (
    VADResult,
    compute_frame_rms,
    compute_vad,
)

__all__ = [
    "AudioBufferError",
    "InvalidSessionError",
    "BufferOverflowError",
    "SessionAudioBuffer",
    "SessionBufferManager",
    "get_buffer_manager",
    "reset_buffer_manager",
    "AudioValidationError",
    "PreprocessedAudioWindow",
    "extract_audio_window",
    "preprocess_pcm16",
    "validate_pcm16_audio",
    "VADResult",
    "compute_frame_rms",
    "compute_vad",
    "build_processed_speech_chunk",
]
