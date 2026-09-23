"""Development/mock adapter.

WARNING: This is NOT a real synthetic-voice detector. It computes a
deterministic, lightweight heuristic (energy / zero-crossing / flatness
proxy) solely so Backend 2 -> Backend 3 -> Backend 4 plumbing, contracts,
latency budgets and UI wiring can be developed and tested before a trained
model lands. Do not use its scores for real security decisions.
"""
from __future__ import annotations

import logging
import math
from typing import Sequence

from backend.models.base import SyntheticVoiceModel

log = logging.getLogger(__name__)


class MockHeuristicModel(SyntheticVoiceModel):
    """Deterministic placeholder behind the real-model interface."""

    def __init__(self, version: str = "mock-heuristic-v0.1.0") -> None:
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
    def load_count(self) -> int:
        return self._load_count

    def load(self) -> None:
        if self._loaded:
            return
        # Simulate one-time setup work (no weights — nothing to load).
        self._loaded = True
        self._load_count += 1
        log.info("MockHeuristicModel initialised (version=%s). NOT a real detector.", self._version)

    def predict_proba(self, audio: Sequence[float], sample_rate: int) -> float:
        if not self._loaded:
            raise RuntimeError("Model used before load(). Call load() first.")
        n = len(audio)
        if n == 0:
            raise ValueError("Empty audio passed to model.")
        # RMS energy in [0, 1].
        mean_sq = sum(float(x) * float(x) for x in audio) / n
        rms = math.sqrt(max(mean_sq, 0.0))
        # Zero-crossing rate in [0, 1].
        zc = sum(1 for i in range(1, n) if (audio[i - 1] < 0) != (audio[i] < 0))
        zcr = zc / max(n - 1, 1)
        # Peak-to-RMS (crest) proxy, normalised.
        peak = max(abs(float(x)) for x in audio)
        crest = min(peak / (rms + 1e-6), 10.0) / 10.0
        # Fixed illustrative blend — has no spoof-detection validity.
        score = 0.45 * min(rms * 2.0, 1.0) + 0.35 * zcr + 0.20 * crest
        return max(0.0, min(1.0, score))
