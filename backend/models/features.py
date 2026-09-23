"""Shared feature contract v1 for real (non-mock) adapters (stdlib only).

``spectral_descriptor_32`` turns normalised mono samples into the fixed
32-float descriptor consumed by the JSON weight files of
``RealDetectorAdapter`` and ``RealEmbedderAdapter``. It is deterministic
(pure function of the samples + sample rate) and deliberately stable:
changing it invalidates every v1 weights file, so it is versioned by the
``"feature": "heuristic-32-v1"`` tag those files carry.

This is NOT a learned frontend -- it is a documented, auditable
time-domain descriptor that lets the weight-loading / scoring / plumbing
path be implemented and tested before trained parameters exist. Real
discriminative power arrives with real weights (Part 9: calibration and
evaluation on representative data).
"""
from __future__ import annotations

import math
from typing import Sequence

FEATURE_TAG = "heuristic-32-v1"
DESCRIPTOR_DIM = 32


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: Sequence[float], mean: float) -> float:
    if not values:
        return 0.0
    return math.sqrt(max(sum((v - mean) ** 2 for v in values) / len(values), 0.0))


def spectral_descriptor_32(audio: Sequence[float], sample_rate: int) -> tuple:
    """Compute the 32-dim v1 descriptor. Input must already be normalised
    mono floats; raises ``ValueError`` on empty input."""
    samples = [float(x) for x in audio]
    n = len(samples)
    if n == 0:
        raise ValueError("Empty audio passed to feature extraction.")
    frame_len = max(int(sample_rate) // 50, 1)  # ~20ms frames at any rate

    rms_frames: list[float] = []
    zcr_frames: list[float] = []
    peak_frames: list[float] = []
    for start in range(0, n, frame_len):
        frame = samples[start:start + frame_len]
        m = len(frame)
        if m == 0:
            continue
        mean_sq = sum(x * x for x in frame) / m
        rms_frames.append(math.sqrt(max(mean_sq, 0.0)))
        zc = sum(1 for i in range(1, m) if (frame[i - 1] < 0) != (frame[i] < 0))
        zcr_frames.append(zc / max(m - 1, 1))
        peak_frames.append(max(abs(x) for x in frame))

    mean_rms = _mean(rms_frames)
    mean_zcr = _mean(zcr_frames)
    overall_rms = math.sqrt(max(sum(x * x for x in samples) / n, 0.0))
    overall_zc = sum(1 for i in range(1, n) if (samples[i - 1] < 0) != (samples[i] < 0))
    peak = max(abs(x) for x in samples)

    feats = [
        mean_rms,
        _std(rms_frames, mean_rms),
        max(rms_frames) if rms_frames else 0.0,
        min(rms_frames) if rms_frames else 0.0,
        mean_zcr,
        _std(zcr_frames, mean_zcr),
        max(zcr_frames) if zcr_frames else 0.0,
        _mean(peak_frames),
        overall_rms,
        overall_zc / max(n - 1, 1),
        peak,
        sum(abs(x) for x in samples) / n,
        sum(abs(samples[i] - samples[i - 1]) for i in range(1, n)) / max(n - 1, 1),
        min(peak / (overall_rms + 1e-6), 10.0) / 10.0,
        (max(rms_frames) - min(rms_frames)) if rms_frames else 0.0,
        sum(1 for r in rms_frames if r < 0.1 * (overall_rms + 1e-9)) / max(len(rms_frames), 1),
        sum(x ** 3 for x in samples) / n,
        sum(x ** 4 for x in samples) / n,
    ]
    n_seg = 8
    seg_len = max(n // n_seg, 1)
    for s in range(n_seg):
        seg = samples[s * seg_len:(s + 1) * seg_len] or [0.0]
        feats.append(math.sqrt(max(sum(x * x for x in seg) / len(seg), 0.0)))
    for s in range(6):
        seg = samples[s * seg_len:(s + 1) * seg_len] or [0.0]
        m = len(seg)
        zc = sum(1 for i in range(1, m) if (seg[i - 1] < 0) != (seg[i] < 0))
        feats.append(zc / max(m - 1, 1))

    assert len(feats) == DESCRIPTOR_DIM, f"feature dim drift: {len(feats)}"
    return tuple(feats)


def sigmoid(value: float) -> float:
    """Numerically guarded logistic function."""
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    shifted = math.exp(value)
    return shifted / (1.0 + shifted)
