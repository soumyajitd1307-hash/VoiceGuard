"""Audio preprocessing and window extraction for Backend 2.

Validates raw PCM16 audio, normalizes samples to floats using Backend 3's
shared normalizer, and extracts fixed-duration audio windows from SessionBufferManager.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.audio import normalise_pcm16
from backend.config import Settings, get_settings
from backend.schemas import ValidationError as B3ValidationError
from backend2.buffer import (
    SessionBufferManager,
    _validate_session_id,
)

if TYPE_CHECKING:
    pass

DEFAULT_WINDOW_DURATION_S = 1.0
DEFAULT_SAMPLE_RATE = 16000
BYTES_PER_PCM16_SAMPLE = 2


class AudioValidationError(Exception):
    """Raised when an audio payload fails PCM16 validation or duration bounds."""


@dataclass(frozen=True)
class PreprocessedAudioWindow:
    """Immutable preprocessed audio window ready for downstream feature extraction.

    Attributes:
        session_id: Associated session identifier.
        raw_bytes: Original unmodified 16-bit little-endian PCM bytes.
        samples: Normalized float samples in [-1.0, 1.0] (shared B3 format).
        sample_rate: Sample rate in Hz.
        duration_s: Duration of the audio window in seconds.
        num_samples: Total number of audio samples.
    """

    session_id: str
    raw_bytes: bytes
    samples: tuple[float, ...]
    sample_rate: int
    duration_s: float
    num_samples: int


def validate_pcm16_audio(
    raw_bytes: bytes | bytearray,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    settings: Settings | None = None,
) -> tuple[int, float]:
    """Validate PCM16 bytes, sample rate, and duration bounds against B3 settings.

    Args:
        raw_bytes: Raw bytes or bytearray to validate.
        sample_rate: Audio sample rate in Hz.
        settings: Optional custom Settings instance; defaults to B3 get_settings().

    Returns:
        Tuple of (num_samples, duration_seconds).

    Raises:
        AudioValidationError: If input is not bytes, byte length is odd,
            sample rate is unsupported, or duration violates B3 limits.
    """
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise AudioValidationError(
            f"raw_bytes must be bytes or bytearray, got {type(raw_bytes).__name__}."
        )

    byte_len = len(raw_bytes)
    if byte_len == 0:
        raise AudioValidationError("Audio payload must not be empty.")

    if byte_len % BYTES_PER_PCM16_SAMPLE != 0:
        raise AudioValidationError(
            f"PCM16 byte length must be even (got {byte_len} bytes)."
        )

    cfg = settings or get_settings()

    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int):
        raise AudioValidationError("sample_rate must be an integer (Hz).")

    if sample_rate not in cfg.supported_sample_rates:
        raise AudioValidationError(
            f"Unsupported sample_rate={sample_rate}. "
            f"Supported: {list(cfg.supported_sample_rates)}."
        )

    num_samples = byte_len // BYTES_PER_PCM16_SAMPLE
    duration_s = num_samples / sample_rate

    if duration_s < cfg.min_duration_s:
        raise AudioValidationError(
            f"Audio too short: {duration_s:.3f}s < minimum {cfg.min_duration_s}s."
        )

    if duration_s > cfg.max_duration_s:
        raise AudioValidationError(
            f"Audio too long: {duration_s:.3f}s > maximum {cfg.max_duration_s}s."
        )

    return num_samples, duration_s


def preprocess_pcm16(
    raw_bytes: bytes | bytearray,
    session_id: str,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    settings: Settings | None = None,
) -> PreprocessedAudioWindow:
    """Validate and convert raw PCM16 bytes into a PreprocessedAudioWindow.

    Reuses `backend.audio.normalise_pcm16` to ensure 100% parity with B3 normalisation.

    Args:
        raw_bytes: PCM16 little-endian mono audio bytes.
        session_id: Associated session identifier.
        sample_rate: Sample rate in Hz (default 16000).
        settings: Optional custom Settings instance.

    Returns:
        PreprocessedAudioWindow instance with both raw_bytes and float samples.
    """
    clean_session_id = _validate_session_id(session_id)
    num_samples, duration_s = validate_pcm16_audio(
        raw_bytes=raw_bytes,
        sample_rate=sample_rate,
        settings=settings,
    )

    pcm_bytes = bytes(raw_bytes)

    try:
        samples = normalise_pcm16(pcm_bytes)
    except B3ValidationError as exc:
        raise AudioValidationError(f"PCM16 normalisation failed: {exc}") from exc

    return PreprocessedAudioWindow(
        session_id=clean_session_id,
        raw_bytes=pcm_bytes,
        samples=samples,
        sample_rate=sample_rate,
        duration_s=round(duration_s, 6),
        num_samples=num_samples,
    )


def extract_audio_window(
    buffer_manager: SessionBufferManager,
    session_id: str,
    window_duration_s: float = DEFAULT_WINDOW_DURATION_S,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    settings: Settings | None = None,
) -> PreprocessedAudioWindow | None:
    """Extract a complete fixed-duration audio window from the session buffer.

    Verifies buffer capacity prior to extraction. If insufficient data exists,
    returns None and leaves all buffered audio untouched.

    Args:
        buffer_manager: The SessionBufferManager instance managing the buffers.
        session_id: The session ID to extract from.
        window_duration_s: Desired window length in seconds (default 1.0s).
        sample_rate: Expected sample rate in Hz (default 16000).
        settings: Optional custom Settings instance.

    Returns:
        PreprocessedAudioWindow if sufficient audio is buffered, else None.
    """
    clean_session_id = _validate_session_id(session_id)

    if window_duration_s <= 0:
        raise AudioValidationError(
            f"window_duration_s must be positive, got {window_duration_s}."
        )

    required_samples = int(round(window_duration_s * sample_rate))
    required_bytes = required_samples * BYTES_PER_PCM16_SAMPLE

    current_size = buffer_manager.get_size(clean_session_id)
    if current_size < required_bytes:
        return None

    raw_chunk = buffer_manager.extract(clean_session_id, required_bytes, exact=True)

    return preprocess_pcm16(
        raw_bytes=raw_chunk,
        session_id=clean_session_id,
        sample_rate=sample_rate,
        settings=settings,
    )
