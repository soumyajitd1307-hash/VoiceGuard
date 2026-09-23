"""Modular synthetic-voice detection service (Backend 3 ML layer).

Backend 2 calls :func:`detect_synthetic_voice` (or the
:class:`SyntheticVoiceDetectionService` class) with one processed speech
chunk. The service validates input, runs the configured
:class:`SyntheticVoiceModel` adapter, applies thresholds, and returns a
:class:`DetectionResult` for Backend 4.

Accepted audio forms (``audio`` parameter):
    * ``bytes`` / ``bytearray`` — 16-bit little-endian PCM mono.
    * base64 ``str`` of the above (set ``audio_encoding="pcm16_base64"``).
    * sequence of ``float``/``int`` mono samples in [-1.0, 1.0].

Only stdlib is used so this module has zero heavy ML dependencies; a future
real adapter (ONNX/torch) lives behind the same interface.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Union

from backend.audio import AudioInput, normalise_audio
from backend.config import Settings, get_settings
from backend.models import registry
from backend.models.base import SyntheticVoiceModel
from backend.schemas import DetectionLabel, DetectionResult, ModelError, ValidationError

log = logging.getLogger(__name__)


def _validate_id(value: Any, field: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string.")
    cleaned = value.strip()
    if not cleaned:
        raise ValidationError(f"{field} must be a non-empty string.")
    if len(cleaned) > max_len:
        raise ValidationError(f"{field} exceeds max length {max_len}.")
    return cleaned


class SyntheticVoiceDetectionService:
    """Thin orchestration layer: validate -> infer -> threshold -> result."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        level = getattr(logging, self.settings.log_level.upper(), logging.INFO)
        logging.basicConfig(level=level, force=False)

    @property
    def model(self) -> SyntheticVoiceModel:
        # Singleton: weights/setup load exactly once per process.
        return registry.get_model(self.settings)

    def _prepare_audio(self, audio: AudioInput, audio_encoding: str = "auto") -> tuple:
        # Shared Backend 3 normalisation (backend/audio.py); behaviour unchanged.
        return normalise_audio(audio, audio_encoding)

    def detect(
        self,
        audio: AudioInput,
        sample_rate: int,
        session_id: str,
        chunk_id: str,
        audio_encoding: str = "auto",
    ) -> DetectionResult:
        start = time.perf_counter()
        cfg = self.settings

        session_id = _validate_id(session_id, "session_id", cfg.max_id_length)
        chunk_id = _validate_id(chunk_id, "chunk_id", cfg.max_id_length)

        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int):
            raise ValidationError("sample_rate must be an integer (Hz).")
        if sample_rate not in cfg.supported_sample_rates:
            raise ValidationError(
                f"Unsupported sample_rate={sample_rate}. "
                f"Supported: {list(cfg.supported_sample_rates)}."
            )

        samples = self._prepare_audio(audio, audio_encoding)
        duration_s = len(samples) / sample_rate
        if duration_s < cfg.min_duration_s:
            raise ValidationError(
                f"Audio too short: {duration_s:.3f}s < minimum {cfg.min_duration_s}s."
            )
        if duration_s > cfg.max_duration_s:
            raise ValidationError(
                f"Audio too long: {duration_s:.3f}s > maximum {cfg.max_duration_s}s."
            )

        try:
            probability = float(self.model.predict_proba(samples, sample_rate))
        except (ValidationError, ModelError):
            raise
        except Exception as exc:
            log.exception("Model inference failed (session=%s chunk=%s)", session_id, chunk_id)
            raise ModelError(f"Model inference failed: {exc}") from exc

        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise ModelError(f"Model returned invalid probability {probability!r}.")

        label: DetectionLabel
        if probability >= cfg.synthetic_threshold:
            label = "synthetic"
        elif probability <= cfg.real_threshold:
            label = "real"
        else:
            label = "uncertain"

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        result = DetectionResult(
            label=label,
            synthetic_probability=round(probability, 4),
            model_version=self.model.version,
            processing_time_ms=round(elapsed_ms, 3),
            session_id=session_id,
            chunk_id=chunk_id,
            is_mock=self.model.is_mock,
        )
        log.info(
            "detect session=%s chunk=%s sr=%d n=%d label=%s p=%.4f ms=%.2f mock=%s",
            session_id, chunk_id, sample_rate, len(samples),
            label, probability, elapsed_ms, result.is_mock,
        )
        return result


# Convenience functional entry point (uses process-wide settings + model).
def detect_synthetic_voice(
    audio: AudioInput,
    sample_rate: int,
    session_id: str,
    chunk_id: str,
    audio_encoding: str = "auto",
) -> DetectionResult:
    return SyntheticVoiceDetectionService().detect(
        audio=audio,
        sample_rate=sample_rate,
        session_id=session_id,
        chunk_id=chunk_id,
        audio_encoding=audio_encoding,
    )
