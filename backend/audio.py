"""Shared audio payload helpers for Backend 3 (stdlib only).

Single home for the Backend 3 audio format so detection, embedding and
future components never duplicate normalisation/validation:

    * ``bytes`` / ``bytearray`` -- 16-bit little-endian PCM mono.
    * base64 ``str`` of the above (``audio_encoding="pcm16_base64"``).
    * sequence of ``float``/``int`` mono samples in [-1.0, 1.0].

``normalise_audio`` returns normalised mono float samples in [-1.0, 1.0]
and raises ``ValidationError`` (HTTP 422) for malformed payloads.
"""
from __future__ import annotations

import base64
import binascii
import math
from collections.abc import Sequence
from typing import Any, Union

from backend.schemas import ValidationError

AudioInput = Union[bytes, bytearray, str, Sequence[Any]]

_PCM16_MAX = 32768.0


def normalise_pcm16(raw: bytes) -> tuple:
    if len(raw) % 2 != 0:
        raise ValidationError("PCM16 audio byte length must be even (2 bytes/sample).")
    out = []
    for i in range(0, len(raw), 2):
        value = int.from_bytes(raw[i : i + 2], byteorder="little", signed=True)
        out.append(value / _PCM16_MAX)  # 32767 -> ~0.99997, -32768 -> -1.0
    return tuple(out)


def normalise_floats(samples: Sequence[Any]) -> tuple:
    out = []
    for idx, value in enumerate(samples):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(f"audio[{idx}] must be a number, got {type(value).__name__}.")
        f = float(value)
        if not math.isfinite(f):
            raise ValidationError(f"audio[{idx}] must be finite (got {value!r}).")
        if f < -1.0 - 1e-6 or f > 1.0 + 1e-6:
            raise ValidationError(f"audio[{idx}]={f!r} out of range [-1.0, 1.0].")
        out.append(max(-1.0, min(1.0, f)))
    return tuple(out)


def normalise_audio(audio: AudioInput, audio_encoding: str = "auto") -> tuple:
    """Convert any accepted audio form to normalised float samples."""
    if isinstance(audio, (bytes, bytearray)):
        samples = normalise_pcm16(bytes(audio))
    elif isinstance(audio, str):
        if audio_encoding not in ("auto", "pcm16_base64"):
            raise ValidationError("String audio requires audio_encoding='pcm16_base64'.")
        try:
            samples = normalise_pcm16(base64.b64decode(audio, validate=True))
        except (binascii.Error, ValueError) as exc:
            raise ValidationError(f"Invalid base64 PCM16 audio: {exc}") from exc
    elif isinstance(audio, Sequence):
        samples = normalise_floats(audio)
    else:
        raise ValidationError(
            f"audio must be PCM16 bytes, base64 str, or float sequence (got {type(audio).__name__})."
        )
    if len(samples) == 0:
        raise ValidationError("audio must contain at least one sample.")
    return samples
