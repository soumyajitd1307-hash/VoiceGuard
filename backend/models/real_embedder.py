"""Real speaker-embedding adapter (weights-supplied, NOT mock).

``RealEmbedderAdapter`` implements ``SpeakerEmbeddingModel`` with
``is_mock=False``. It projects the shared v1 feature descriptor
(``backend/models/features.py``) through a matrix loaded from a JSON
weights file, then L2-normalises::

    {"format": "voiceguard-embedder-v1",
     "model": "<human-readable model name>",
     "version": "<weights version, e.g. enc-lin-v1>",
     "feature": "heuristic-32-v1",
     "input_dim": 32,
     "output_dim": <D>,
     "matrix": [[<32 floats>] x D],
     "bias": [<D floats>]}

``embedding_dim`` is the file's ``output_dim`` -- derived from the actual
weights, never hardcoded. A zero-norm projection raises ``ModelError``
(degenerate weights) rather than returning a fake uniform vector.

Status discipline mirrors ``real_detector.py``: ``is_mock=False`` marks a
real scoring path, NOT validated recognition. Missing/malformed weights
raise ``ModelError``; never silently falls back to mock. Production
readiness additionally requires Part 9. ``repr()`` carries version,
dimension and loaded state only.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from typing import Sequence

from backend.models.features import DESCRIPTOR_DIM, FEATURE_TAG, spectral_descriptor_32
from backend.models.speaker_base import SpeakerEmbeddingModel
from backend.schemas import ModelError

log = logging.getLogger(__name__)

WEIGHTS_FORMAT = "voiceguard-embedder-v1"


def _read_weights_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise ModelError(f"Embedder weights not found: {path!r}. "
                         "Supply VG_EMBEDDER_MODEL.") from exc
    except (OSError, ValueError) as exc:
        raise ModelError(f"Embedder weights unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModelError("Embedder weights file must contain a JSON object.")
    return payload


def _is_number(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


class RealEmbedderAdapter(SpeakerEmbeddingModel):
    """File-backed encoder behind the production ``is_mock=False`` flag."""

    def __init__(self, weights_path: str, version: str) -> None:
        if not isinstance(weights_path, str) or not weights_path.strip():
            raise ModelError("Real embedder requires a VG_EMBEDDER_MODEL weights path.")
        if not isinstance(version, str) or not version.strip():
            raise ModelError("Real embedder requires an expected VG_EMBEDDER_VERSION.")
        self._weights_path = weights_path
        self._expected_version = version
        self._matrix: tuple | None = None
        self._bias: tuple | None = None
        self._output_dim = 0
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
    def embedding_dim(self) -> int:
        if not self._loaded:
            raise RuntimeError("embedding_dim unavailable before load().")
        return self._output_dim

    @property
    def load_count(self) -> int:
        return self._load_count

    def __repr__(self) -> str:  # no path: locations may be sensitive
        return (f"RealEmbedderAdapter(version={self._expected_version!r}, "
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
                    f"Unsupported embedder weights format {payload.get('format')!r} "
                    f"(expected {WEIGHTS_FORMAT!r}).")
            if payload.get("feature") != FEATURE_TAG:
                raise ModelError(
                    f"Weights feature tag {payload.get('feature')!r} != adapter {FEATURE_TAG!r}.")
            file_version = payload.get("version")
            if file_version != self._expected_version:
                raise ModelError(
                    f"Weights version {file_version!r} != expected {self._expected_version!r}.")
            if payload.get("input_dim") != DESCRIPTOR_DIM:
                raise ModelError(
                    f"Weights input_dim {payload.get('input_dim')!r} != {DESCRIPTOR_DIM}.")
            output_dim = payload.get("output_dim")
            matrix = payload.get("matrix")
            bias = payload.get("bias", [])
            if (not isinstance(output_dim, int) or isinstance(output_dim, bool)
                    or output_dim <= 0):
                raise ModelError("Weights output_dim must be a positive integer.")
            if (not isinstance(matrix, list) or len(matrix) != output_dim
                    or any(not isinstance(row, list) or len(row) != DESCRIPTOR_DIM
                           or not all(_is_number(v) for v in row) for row in matrix)):
                raise ModelError(
                    f"Weights matrix must be {output_dim}x{DESCRIPTOR_DIM} finite numbers.")
            if (not isinstance(bias, list) or len(bias) != output_dim
                    or not all(_is_number(v) for v in bias)):
                raise ModelError(
                    f"Weights bias must be {output_dim} finite numbers.")
            self._matrix = tuple(tuple(float(v) for v in row) for row in matrix)
            self._bias = tuple(float(v) for v in bias)
            self._output_dim = output_dim
            self._loaded = True
            self._load_count += 1
            log.info("RealEmbedderAdapter loaded (version=%s dim=%d).",
                     self._expected_version, output_dim)

    def _check_input(self, audio: Sequence[float], sample_rate: int) -> list:
        if not self._loaded or self._matrix is None or self._bias is None:
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

    def embed(self, audio: Sequence[float], sample_rate: int) -> tuple:
        samples = self._check_input(audio, sample_rate)
        assert self._matrix is not None and self._bias is not None
        feats = spectral_descriptor_32(samples, sample_rate)
        projected = [
            sum(row[j] * feats[j] for j in range(DESCRIPTOR_DIM)) + self._bias[i]
            for i, row in enumerate(self._matrix)
        ]
        norm = math.sqrt(sum(v * v for v in projected))
        if norm == 0.0:
            raise ModelError("Embedder projection degenerated to zero (check weights).")
        if not math.isfinite(norm):
            raise ModelError("Embedder projection is non-finite (check weights).")
        return tuple(v / norm for v in projected)
