"""Voice Activity Detection (VAD) for Backend 2.

Deterministic, standard-library-only sub-frame RMS energy speech detector.
Computes speech_ratio and is_speech flags for preprocessed audio windows.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

DEFAULT_FRAME_DURATION_MS = 25  # 25 ms sub-frame = 400 samples at 16 kHz
DEFAULT_ENERGY_THRESHOLD = 0.015  # ~ -36.5 dBFS RMS
DEFAULT_MIN_SPEECH_RATIO = 0.25  # 25% active speech required in window


@dataclass(frozen=True)
class VADResult:
    """Immutable result of Voice Activity Detection over an audio window.

    Attributes:
        is_speech: True if speech_ratio >= min_speech_ratio.
        speech_ratio: Fraction of sub-frames flagged as speech in [0.0, 1.0].
        speech_frames: Number of sub-frames exceeding the energy threshold.
        total_frames: Total number of sub-frames analyzed.
    """

    is_speech: bool
    speech_ratio: float
    speech_frames: int
    total_frames: int


def compute_frame_rms(frame: Sequence[float]) -> float:
    """Compute the Root Mean Square (RMS) energy of a sequence of float samples.

    Args:
        frame: Sequence of normalized float samples in [-1.0, 1.0].

    Returns:
        RMS energy as a float in [0.0, 1.0].
    """
    n = len(frame)
    if n == 0:
        return 0.0
    mean_sq = sum(float(x) * float(x) for x in frame) / n
    return math.sqrt(max(mean_sq, 0.0))


def compute_vad(
    samples: Sequence[float],
    sample_rate: int = 16000,
    frame_duration_ms: int = DEFAULT_FRAME_DURATION_MS,
    energy_threshold: float = DEFAULT_ENERGY_THRESHOLD,
    min_speech_ratio: float = DEFAULT_MIN_SPEECH_RATIO,
) -> VADResult:
    """Analyze audio samples in sub-frames to detect speech presence.

    Divides the input samples into non-overlapping sub-frames, evaluates the RMS
    energy of each sub-frame against energy_threshold, and computes the fraction
    of active speech frames.

    Args:
        samples: Sequence of float samples in [-1.0, 1.0].
        sample_rate: Sample rate in Hz (default 16000).
        frame_duration_ms: Duration of each analysis sub-frame in ms (default 25 ms).
        energy_threshold: Minimum sub-frame RMS to classify as speech (default 0.015).
        min_speech_ratio: Minimum speech_ratio to set is_speech=True (default 0.25).

    Returns:
        VADResult with is_speech, speech_ratio, speech_frames, and total_frames.
    """
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be positive, got {sample_rate}.")
    if frame_duration_ms <= 0:
        raise ValueError(f"frame_duration_ms must be positive, got {frame_duration_ms}.")
    if energy_threshold < 0:
        raise ValueError(f"energy_threshold must be non-negative, got {energy_threshold}.")
    if not (0.0 <= min_speech_ratio <= 1.0):
        raise ValueError(f"min_speech_ratio must be in [0.0, 1.0], got {min_speech_ratio}.")

    frame_size = int(round((frame_duration_ms / 1000.0) * sample_rate))
    if frame_size <= 0:
        frame_size = 1

    n_samples = len(samples)
    if n_samples == 0:
        return VADResult(
            is_speech=False,
            speech_ratio=0.0,
            speech_frames=0,
            total_frames=0,
        )

    speech_frames = 0
    total_frames = 0

    for start in range(0, n_samples, frame_size):
        frame = samples[start : start + frame_size]
        if not frame:
            continue
        total_frames += 1
        rms = compute_frame_rms(frame)
        if rms >= energy_threshold:
            speech_frames += 1

    if total_frames == 0:
        ratio = 0.0
    else:
        ratio = round(speech_frames / total_frames, 4)

    is_speech = ratio >= min_speech_ratio

    return VADResult(
        is_speech=is_speech,
        speech_ratio=ratio,
        speech_frames=speech_frames,
        total_frames=total_frames,
    )
