"""Development/mock speaker embedder.

WARNING: This is NOT a real speaker embedding model. It computes a
deterministic, L2-normalised descriptor from time-domain statistics
(frame RMS/ZCR/peak distribution, segment energies) solely so
Backend 2 -> Backend 3 -> Backend 4 plumbing, contracts and voice-profile
wiring can be developed and tested before a trained encoder lands.
Its vectors carry NO real speaker identity and must never drive
verification decisions.

Dimension note: 32 is an arbitrary property of THIS mock implementation,
not a claim about ECAPA-TDNN (192), x-vector (512) or any real encoder.
Consumers read ``embedding_dim`` / ``len(vector)``; a real adapter
reports its own dimension with no pipeline change.
"""
from __future__ import annotations

import logging
import math
from typing import Sequence

from backend.models.speaker_base import SpeakerEmbeddingModel

log = logging.getLogger(__name__)

MOCK_EMBEDDING_DIM = 32


def _frame_stats(samples: Sequence[float], frame_len: int) -> tuple[list, list, list]:
    rms_frames, zcr_frames, peak_frames = [], [], []
    n = len(samples)
    for start in range(0, n, frame_len):
        frame = samples[start : start + frame_len]
        if not frame:
            continue
        m = len(frame)
        mean_sq = sum(float(x) * float(x) for x in frame) / m
        rms = math.sqrt(max(mean_sq, 0.0))
        zc = sum(1 for i in range(1, m) if (frame[i - 1] < 0) != (frame[i] < 0))
        rms_frames.append(rms)
        zcr_frames.append(zc / max(m - 1, 1))
        peak_frames.append(max(abs(float(x)) for x in frame))
    return rms_frames, zcr_frames, peak_frames


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: Sequence[float], mean: float) -> float:
    if not values:
        return 0.0
    return math.sqrt(max(sum((v - mean) ** 2 for v in values) / len(values), 0.0))


class MockSpectralEmbedder(SpeakerEmbeddingModel):
    """Deterministic placeholder behind the real-encoder interface."""

    def __init__(self, version: str = "mock-spectral-v0.1.0") -> None:
        self._version = version
        self._loaded = False
        self._load_count = 0  # observable for tests: loading happens once

    @property
    def version(self) -> str:
        return self._version

    @property
    def is_mock(self) -> bool:
        return True

    @property
    def embedding_dim(self) -> int:
        return MOCK_EMBEDDING_DIM

    @property
    def load_count(self) -> int:
        return self._load_count

    def load(self) -> None:
        if self._loaded:
            return
        # Simulate one-time setup work (no weights -- nothing to load).
        self._loaded = True
        self._load_count += 1
        log.info("MockSpectralEmbedder initialised (version=%s). NOT a real encoder.", self._version)

    def embed(self, audio: Sequence[float], sample_rate: int) -> tuple:
        if not self._loaded:
            raise RuntimeError("Model used before load(). Call load() first.")
        samples = [float(x) for x in audio]
        n = len(samples)
        if n == 0:
            raise ValueError("Empty audio passed to model.")

        frame_len = max(sample_rate // 50, 1)  # ~20ms frames at any supported rate
        rms_f, zcr_f, peak_f = _frame_stats(samples, frame_len)

        mean_rms = _mean(rms_f)
        std_rms = _std(rms_f, mean_rms)
        mean_zcr = _mean(zcr_f)
        std_zcr = _std(zcr_f, mean_zcr)
        overall_rms = math.sqrt(max(sum(x * x for x in samples) / n, 0.0))
        overall_zc = sum(1 for i in range(1, n) if (samples[i - 1] < 0) != (samples[i] < 0))
        overall_zcr = overall_zc / max(n - 1, 1)
        peak = max(abs(x) for x in samples)
        mean_abs = sum(abs(x) for x in samples) / n
        mean_diff = sum(abs(samples[i] - samples[i - 1]) for i in range(1, n)) / max(n - 1, 1)
        crest = min(peak / (overall_rms + 1e-6), 10.0) / 10.0
        dyn_range = (max(rms_f) - min(rms_f)) if rms_f else 0.0
        silence_ratio = sum(1 for r in rms_f if r < 0.1 * (overall_rms + 1e-9)) / max(len(rms_f), 1)
        skew = sum(x**3 for x in samples) / n
        kurt = sum(x**4 for x in samples) / n

        feats = [
            mean_rms, std_rms, max(rms_f) if rms_f else 0.0, min(rms_f) if rms_f else 0.0,
            mean_zcr, std_zcr, max(zcr_f) if zcr_f else 0.0,
            _mean(peak_f), overall_rms, overall_zcr, peak, mean_abs,
            mean_diff, crest, dyn_range, silence_ratio, skew, kurt,
        ]
        # 8 segment energies + 6 segment ZCRs -> 14 more (total 18 + 14 = 32).
        n_seg = 8
        seg_len = max(n // n_seg, 1)
        for s in range(n_seg):
            seg = samples[s * seg_len : (s + 1) * seg_len] or [0.0]
            feats.append(math.sqrt(max(sum(x * x for x in seg) / len(seg), 0.0)))
        for s in range(6):
            seg = samples[s * seg_len : (s + 1) * seg_len] or [0.0]
            m = len(seg)
            zc = sum(1 for i in range(1, m) if (seg[i - 1] < 0) != (seg[i] < 0))
            feats.append(zc / max(m - 1, 1))

        assert len(feats) == MOCK_EMBEDDING_DIM, f"mock dim drift: {len(feats)}"
        norm = math.sqrt(sum(f * f for f in feats))
        if norm == 0.0:
            # Digital silence: fall back to a uniform unit vector (documented).
            uniform = 1.0 / math.sqrt(MOCK_EMBEDDING_DIM)
            return tuple([uniform] * MOCK_EMBEDDING_DIM)
        # L2-normalise: unit norm, cosine-similarity ready for Part 3.
        return tuple(f / norm for f in feats)
