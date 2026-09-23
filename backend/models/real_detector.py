"""Real synthetic-voice detector adapter (weights-supplied, NOT mock).

``RealDetectorAdapter`` implements ``SyntheticVoiceModel`` with
``is_mock=False``. It scores the shared v1 feature descriptor
(``backend/models/features.py``) through parameters loaded from a JSON
weights file::

    {"format": "voiceguard-detector-v1",
     "model": "<human-readable model name>",
     "version": "<weights version, e.g. cm-lr-v1>",
     "feature": "heuristic-32-v1",
     "input_dim": 32,
     "weights": [<32 floats>],
     "bias": <float>}

Status discipline (read carefully):
    * ``is_mock`` is False because the SCORING PATH is real (loaded
      parameters, deterministic inference) -- NOT because the parameters
      are validated. Test-fixture weights exercise plumbing only.
    * Requesting ``real`` without a weights path, with a missing file, or
      with malformed/version-mismatched weights raises ``ModelError``.
      NEVER silently falls back to mock (that would be false confidence).
    * Production readiness additionally requires Part 9 (representative
      data, calibration, evaluation). This adapter is step A/B only.

Lifecycle: lazy ``load()`` (idempotent, thread-safe, once per instance;
once per process via ``models/registry.py``). ``repr()`` carries version
and loaded state only -- never the weights path, audio, or scores.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from typing import Sequence

from backend.models.base import SyntheticVoiceModel
from backend.models.features import DESCRIPTOR_DIM, FEATURE_TAG, sigmoid, spectral_descriptor_32
from backend.schemas import ModelError

log = logging.getLogger(__name__)

WEIGHTS_FORMAT = "voiceguard-detector-v1"


def _read_weights_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise ModelError(f"Detector weights not found: {path!r}. "
                         "Supply VG_DETECTOR_MODEL.") from exc
    except (OSError, ValueError) as exc:
        raise ModelError(f"Detector weights unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModelError("Detector weights file must contain a JSON object.")
    return payload


class RealDetectorAdapter(SyntheticVoiceModel):
    """File-backed detector behind the production ``is_mock=False`` flag."""

    def __init__(self, weights_path: str, version: str) -> None:
        if not isinstance(weights_path, str) or not weights_path.strip():
            raise ModelError("Real detector requires a VG_DETECTOR_MODEL weights path.")
        if not isinstance(version, str) or not version.strip():
            raise ModelError("Real detector requires an expected VG_DETECTOR_VERSION.")
        self._weights_path = weights_path
        self._expected_version = version
        self._weights: tuple | None = None
        self._bias = 0.0
        self._loaded = False
        self._load_count = 0  # observable for tests: loading happens once
        self._lock = threading.Lock()

    @property
    def version(self) -> str:
        # Configured expectation; verified equal to the file's version on load.
        return self._expected_version

    @property
    def is_mock(self) -> bool:
        return False

    @property
    def load_count(self) -> int:
        return self._load_count

    def __repr__(self) -> str:  # no path: locations may be sensitive
        return (f"RealDetectorAdapter(version={self._expected_version!r}, "
                f"loaded={self._loaded})")

    def load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            payload = _read_weights_file(self._weights_path)
            if payload.get("format") != WEIGHTS_FORMAT:
                raise ModelError(
                    f"Unsupported detector weights format {payload.get('format')!r} "
                    f"(expected {WEIGHTS_FORMAT!r}).")
            if payload.get("feature") != FEATURE_TAG:
                raise ModelError(
                    f"Weights feature tag {payload.get('feature')!r} != adapter {FEATURE_TAG!r}.")
            file_version = payload.get("version")
            if file_version != self._expected_version:
                raise ModelError(
                    f"Weights version {file_version!r} != expected {self._expected_version!r}.")
            weights = payload.get("weights")
            if (not isinstance(weights, list) or len(weights) != DESCRIPTOR_DIM
                    or any(isinstance(w, bool) or not isinstance(w, (int, float))
                           or not math.isfinite(float(w)) for w in weights)):
                raise ModelError(
                    f"Weights must be {DESCRIPTOR_DIM} finite numbers.")
            bias = payload.get("bias", 0.0)
            if (isinstance(bias, bool) or not isinstance(bias, (int, float))
                    or not math.isfinite(float(bias))):
                raise ModelError("Weights bias must be a finite number.")
            self._weights = tuple(float(w) for w in weights)
            self._bias = float(bias)
            self._loaded = True
            self._load_count += 1
            log.info("RealDetectorAdapter loaded (version=%s).", self._expected_version)

    def _check_input(self, audio: Sequence[float], sample_rate: int) -> list:
        if not self._loaded or self._weights is None:
            raise RuntimeError("Model used before load(). Call load() first.")
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int):
            raise ValueError("sample_rate must be an integer (Hz).")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive.")
        try:
            samples = [float(x) for x in audio]
        except TypeError:
            raise ValueError("audio must be a sequence of numbers.") from None
        if len(samples) == 0:
            raise ValueError("Empty audio passed to model.")
        for value in samples:
            if not math.isfinite(value):
                raise ValueError("audio must contain only finite samples.")
            if value < -1.0 - 1e-6 or value > 1.0 + 1e-6:
                raise ValueError("audio samples must lie in [-1.0, 1.0].")
        return samples

    def predict_proba(self, audio: Sequence[float], sample_rate: int) -> float:
        samples = self._check_input(audio, sample_rate)
        assert self._weights is not None
        feats = spectral_descriptor_32(samples, sample_rate)
        logit = sum(w * f for w, f in zip(self._weights, feats)) + self._bias
        return max(0.0, min(1.0, sigmoid(logit)))
