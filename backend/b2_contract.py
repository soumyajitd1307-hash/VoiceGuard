"""Backend 2 -> Backend 3 integration contract (speech-ready handoff).

Backend 2 owns the audio pipeline (preprocessing, VAD, language ID,
segmentation). Backend 3 owns ML inference (NOT implemented here).
This module is the single, model-independent boundary between them.

Pipeline -> contract field mapping::

    B2 preprocessing (resample/mono/normalise) -> ``audio`` + ``sample_rate``
    B2 VAD (speech / non-speech)               -> ``is_speech`` + ``speech_ratio``
    B2 language ID                             -> ``language`` (passthrough)
    B2 segmentation (session/chunking)         -> ``session_id`` + ``chunk_id``
                                                  + ``timestamp_s``

Audio format policy (no duplicate format):
    ``audio`` reuses the exact forms accepted by
    ``SyntheticVoiceDetectionService.detect`` (``backend/service.py``):

    * ``bytes`` / ``bytearray`` -- 16-bit little-endian PCM mono.
    * base64 ``str`` of the above (set ``audio_encoding="pcm16_base64"``).
    * sequence of ``float``/``int`` mono samples in [-1.0, 1.0].

    Backend 3 must receive speech-ready audio (VAD-filtered) whenever
    possible; ``is_speech``/``speech_ratio`` are carried so B3 can
    skip or deprioritise non-speech without re-running VAD.

Model independence:
    This module imports only ``backend.config`` and ``backend.schemas``
    (``Settings``, ``ValidationError``). It never imports a model,
    never scores audio, and never decides real vs. synthetic.

Example (JSON transport dict, what B2 sends / B3 accepts)::

    {
        "audio_base64": "<base64 of PCM16LE mono speech>",
        "audio_encoding": "pcm16_base64",
        "sample_rate": 16000,
        "session_id": "1042",
        "chunk_id": "c0018",
        "timestamp_s": 18.0,
        "language": "en",
        "is_speech": True,
        "speech_ratio": 0.92
    }

Example (in-process use)::

    from backend.b2_contract import ProcessedSpeechChunk, from_dict

    chunk = from_dict(payload)          # validates, raises ValidationError
    kwargs = chunk.to_detect_kwargs()   # -> service.detect(**kwargs)
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any, Union

from backend.config import Settings, get_settings
from backend.schemas import ValidationError

# Same accepted forms as service.AudioInput (type alias only, not a new format).
AudioPayload = Union[bytes, bytearray, str, Any]

_VALID_ENCODINGS = ("auto", "pcm16_base64")
_MAX_LANGUAGE_LENGTH = 32


def _clean_id(value: Any, field: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string.")
    cleaned = value.strip()
    if not cleaned:
        raise ValidationError(f"{field} must be a non-empty string.")
    if len(cleaned) > max_len:
        raise ValidationError(f"{field} exceeds max length {max_len}.")
    return cleaned


def _clean_timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("timestamp_s must be a number of seconds or null.")
    seconds = float(value)
    if seconds != seconds or seconds == float("inf") or seconds == float("-inf"):
        raise ValidationError("timestamp_s must be finite.")
    if seconds < 0:
        raise ValidationError("timestamp_s must be >= 0.")
    return seconds


def _clean_language(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("language must be a string or null.")
    cleaned = value.strip()
    if not cleaned:
        return None  # empty label == unknown, not an error
    if len(cleaned) > _MAX_LANGUAGE_LENGTH:
        raise ValidationError(f"language exceeds max length {_MAX_LANGUAGE_LENGTH}.")
    return cleaned


def _clean_speech_flags(is_speech: Any, speech_ratio: Any) -> tuple[bool, float | None]:
    if not isinstance(is_speech, bool):
        raise ValidationError("is_speech must be a boolean.")
    if speech_ratio is None:
        return is_speech, None
    if isinstance(speech_ratio, bool) or not isinstance(speech_ratio, (int, float)):
        raise ValidationError("speech_ratio must be a number in [0.0, 1.0] or null.")
    ratio = float(speech_ratio)
    if not 0.0 <= ratio <= 1.0:
        raise ValidationError(f"speech_ratio={ratio!r} out of range [0.0, 1.0].")
    return is_speech, ratio


@dataclass(frozen=True)
class ProcessedSpeechChunk:
    """One VAD-filtered, speech-ready segment from Backend 2.

    Attributes:
        audio: speech-ready samples (PCM16 bytes / base64 str / float
            sequence -- same forms as ``service.detect``).
        audio_encoding: "auto" or "pcm16_base64" (required for ``str``).
        sample_rate: Hz; must be in ``Settings.supported_sample_rates``.
        session_id: B2 call/session identifier (opaque, preserved end-to-end).
        chunk_id: B2 chunk identifier within the session (opaque, preserved).
        timestamp_s: call-relative start time in seconds, if known.
        language: B2 language label (e.g. "en"); passthrough, optional.
        is_speech: B2 VAD verdict. False chunks are carried (not dropped)
            so B3 can skip inference without re-running VAD.
        speech_ratio: fraction of frames flagged speech, if known.
    """

    audio: AudioPayload
    sample_rate: int
    session_id: str
    chunk_id: str
    audio_encoding: str = "auto"
    timestamp_s: float | None = None
    language: str | None = None
    is_speech: bool = True
    speech_ratio: float | None = None

    @property
    def is_speech_ready(self) -> bool:
        """True when B3 should run inference (VAD says speech)."""
        return self.is_speech

    def duration_s(self) -> float:
        """Duration in seconds derived from payload length (not trusted input)."""
        length = _payload_length(self.audio, self.audio_encoding)
        return length / self.sample_rate

    def to_detect_kwargs(self) -> dict:
        """Adapter to the existing B3 entrypoint: ``service.detect(**kwargs)``.

        Keeps this contract decoupled from any model implementation.
        """
        return {
            "audio": self.audio,
            "sample_rate": self.sample_rate,
            "session_id": self.session_id,
            "chunk_id": self.chunk_id,
            "audio_encoding": self.audio_encoding,
        }

    def to_dict(self) -> dict:
        """JSON-safe transport form (bytes are base64-encoded)."""
        if isinstance(self.audio, (bytes, bytearray)):
            audio_b64 = base64.b64encode(bytes(self.audio)).decode("ascii")
            return {
                "audio_base64": audio_b64,
                "audio_encoding": "pcm16_base64",
                "sample_rate": self.sample_rate,
                "session_id": self.session_id,
                "chunk_id": self.chunk_id,
                "timestamp_s": self.timestamp_s,
                "language": self.language,
                "is_speech": self.is_speech,
                "speech_ratio": self.speech_ratio,
            }
        if isinstance(self.audio, str):
            return {
                "audio_base64": self.audio,
                "audio_encoding": self.audio_encoding,
                "sample_rate": self.sample_rate,
                "session_id": self.session_id,
                "chunk_id": self.chunk_id,
                "timestamp_s": self.timestamp_s,
                "language": self.language,
                "is_speech": self.is_speech,
                "speech_ratio": self.speech_ratio,
            }
        return {
            "audio": list(self.audio),
            "audio_encoding": self.audio_encoding,
            "sample_rate": self.sample_rate,
            "session_id": self.session_id,
            "chunk_id": self.chunk_id,
            "timestamp_s": self.timestamp_s,
            "language": self.language,
            "is_speech": self.is_speech,
            "speech_ratio": self.speech_ratio,
        }


def _payload_length(audio: AudioPayload, audio_encoding: str) -> int:
    if isinstance(audio, (bytes, bytearray)):
        raw = bytes(audio)
        if len(raw) % 2 != 0:
            raise ValidationError("PCM16 audio byte length must be even (2 bytes/sample).")
        return len(raw) // 2
    if isinstance(audio, str):
        if audio_encoding not in ("auto", "pcm16_base64"):
            raise ValidationError("String audio requires audio_encoding='pcm16_base64'.")
        try:
            raw = base64.b64decode(audio, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValidationError(f"Invalid base64 PCM16 audio: {exc}") from exc
        if len(raw) % 2 != 0:
            raise ValidationError("PCM16 audio byte length must be even (2 bytes/sample).")
        return len(raw) // 2
    try:
        return len(audio)  # type: ignore[arg-type]
    except TypeError:
        raise ValidationError(
            "audio must be PCM16 bytes, base64 str, or float sequence "
            f"(got {type(audio).__name__})."
        ) from None


def validate_chunk(chunk: ProcessedSpeechChunk, settings: Settings | None = None) -> ProcessedSpeechChunk:
    """Validate a chunk against ``Settings``; return a normalised copy."""
    cfg = settings or get_settings()
    if not isinstance(chunk, ProcessedSpeechChunk):
        raise ValidationError("chunk must be a ProcessedSpeechChunk.")
    if chunk.audio_encoding not in _VALID_ENCODINGS:
        raise ValidationError(
            f"audio_encoding must be one of {list(_VALID_ENCODINGS)} "
            f"(got {chunk.audio_encoding!r})."
        )
    if isinstance(chunk.sample_rate, bool) or not isinstance(chunk.sample_rate, int):
        raise ValidationError("sample_rate must be an integer (Hz).")
    if chunk.sample_rate not in cfg.supported_sample_rates:
        raise ValidationError(
            f"Unsupported sample_rate={chunk.sample_rate}. "
            f"Supported: {list(cfg.supported_sample_rates)}."
        )
    session_id = _clean_id(chunk.session_id, "session_id", cfg.max_id_length)
    chunk_id = _clean_id(chunk.chunk_id, "chunk_id", cfg.max_id_length)
    timestamp_s = _clean_timestamp(chunk.timestamp_s)
    language = _clean_language(chunk.language)
    is_speech, speech_ratio = _clean_speech_flags(chunk.is_speech, chunk.speech_ratio)

    length = _payload_length(chunk.audio, chunk.audio_encoding)
    if length == 0:
        raise ValidationError("audio must contain at least one sample.")
    duration = length / chunk.sample_rate
    if duration < cfg.min_duration_s:
        raise ValidationError(
            f"Audio too short: {duration:.3f}s < minimum {cfg.min_duration_s}s."
        )
    if duration > cfg.max_duration_s:
        raise ValidationError(
            f"Audio too long: {duration:.3f}s > maximum {cfg.max_duration_s}s."
        )
    return ProcessedSpeechChunk(
        audio=chunk.audio,
        sample_rate=chunk.sample_rate,
        session_id=session_id,
        chunk_id=chunk_id,
        audio_encoding=chunk.audio_encoding,
        timestamp_s=timestamp_s,
        language=language,
        is_speech=is_speech,
        speech_ratio=speech_ratio,
    )


def from_dict(payload: dict, settings: Settings | None = None) -> ProcessedSpeechChunk:
    """Build a validated chunk from a JSON transport dict (B2 -> B3 wire form).

    Accepts either ``audio_base64`` (preferred for bytes) or ``audio``
    (float list for in-process callers).
    """
    if not isinstance(payload, dict):
        raise ValidationError("B2 payload must be an object.")
    if "audio_base64" in payload:
        audio: AudioPayload = payload["audio_base64"]
        encoding = payload.get("audio_encoding", "pcm16_base64")
    else:
        audio = payload.get("audio")
        encoding = payload.get("audio_encoding", "auto")
    chunk = ProcessedSpeechChunk(
        audio=audio,
        sample_rate=payload.get("sample_rate"),
        session_id=payload.get("session_id"),
        chunk_id=payload.get("chunk_id"),
        audio_encoding=encoding,
        timestamp_s=payload.get("timestamp_s"),
        language=payload.get("language"),
        is_speech=payload.get("is_speech", True),
        speech_ratio=payload.get("speech_ratio"),
    )
    return validate_chunk(chunk, settings)
