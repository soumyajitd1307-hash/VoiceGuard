"""Backend 3 configuration — environment variables only, with safe defaults.

All values can be overridden via environment variables (or a ``.env`` file
loaded by the host application). No secrets are required for the mock model.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_str(name: str, default: str) -> str:
    value = os.getenv(name, default)
    return value if value is not None else default


def _get_optional_float(name: str) -> float | None:
    """Read an optional float env var; missing/empty/invalid means unset (None)."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the synthetic-voice detection service."""

    # Which model adapter to load. Only "mock" ships with this repo.
    # A future real model (e.g. "onnx", "torch") plugs in via models/registry.py.
    model_name: str = field(default_factory=lambda: _get_str("VG_MODEL_NAME", "mock"))
    model_version: str = field(
        default_factory=lambda: _get_str("VG_MODEL_VERSION", "mock-heuristic-v0.1.0")
    )

    # Which speaker-embedding adapter to load. Only "mock" ships with this repo.
    # A future real encoder (e.g. ECAPA-TDNN ONNX) plugs in via
    # models/embed_registry.py.
    embedder_name: str = field(default_factory=lambda: _get_str("VG_EMBEDDER_NAME", "mock"))
    embedder_version: str = field(
        default_factory=lambda: _get_str("VG_EMBEDDER_VERSION", "mock-spectral-v0.1.0")
    )

    # Decision thresholds applied to synthetic_probability (0..1).
    synthetic_threshold: float = field(
        default_factory=lambda: _get_float("VG_SYNTHETIC_THRESHOLD", 0.70)
    )
    real_threshold: float = field(
        default_factory=lambda: _get_float("VG_REAL_THRESHOLD", 0.30)
    )

    # Operating point for speaker similarity (cosine, -1..1). Unset (None)
    # by default: with mock embeddings no validated threshold exists, so
    # the similarity service returns match="uncertain" until evaluation
    # (Part 4) selects one. Set VG_SIMILARITY_THRESHOLD explicitly to
    # request match/non_match decisions.
    similarity_threshold: float | None = field(
        default_factory=lambda: _get_optional_float("VG_SIMILARITY_THRESHOLD")
    )

    # Audio constraints (post-Backend-2 processed speech).
    supported_sample_rates: tuple = (8000, 16000, 22050, 32000, 44100, 48000)
    min_duration_s: float = field(
        default_factory=lambda: _get_float("VG_MIN_DURATION_S", 0.25)
    )
    max_duration_s: float = field(
        default_factory=lambda: _get_float("VG_MAX_DURATION_S", 30.0)
    )
    max_id_length: int = field(default_factory=lambda: _get_int("VG_MAX_ID_LENGTH", 128))

    log_level: str = field(default_factory=lambda: _get_str("VG_LOG_LEVEL", "INFO"))

    def __post_init__(self) -> None:
        if not 0.0 < self.real_threshold < self.synthetic_threshold < 1.0:
            raise ValueError(
                "Require 0 < VG_REAL_THRESHOLD < VG_SYNTHETIC_THRESHOLD < 1 "
                f"(got {self.real_threshold}, {self.synthetic_threshold})"
            )
        if self.min_duration_s <= 0 or self.max_duration_s <= 0:
            raise ValueError("Durations must be positive")
        if self.min_duration_s > self.max_duration_s:
            raise ValueError("VG_MIN_DURATION_S must be <= VG_MAX_DURATION_S")
        if self.similarity_threshold is not None and not -1.0 <= self.similarity_threshold <= 1.0:
            raise ValueError(
                "VG_SIMILARITY_THRESHOLD must lie in [-1.0, 1.0] "
                f"(got {self.similarity_threshold})"
            )


_settings: Settings | None = None


def get_settings(refresh: bool = False) -> Settings:
    """Return cached settings (re-read env when refresh=True, e.g. in tests)."""
    global _settings
    if _settings is None or refresh:
        _settings = Settings()
    return _settings
