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

__all__ = [
    "AudioBufferError",
    "InvalidSessionError",
    "BufferOverflowError",
    "SessionAudioBuffer",
    "SessionBufferManager",
    "get_buffer_manager",
    "reset_buffer_manager",
]
