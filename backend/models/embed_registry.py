"""Embedder registry — guarantees the speaker encoder loads exactly once per process.

Mirrors backend/models/registry.py (detection side). A real encoder
(e.g. ECAPA-TDNN ONNX) registers here behind SpeakerEmbeddingModel with
no service-layer change.
"""
from __future__ import annotations

import logging
import threading

from backend.config import Settings, get_settings
from backend.models.mock_embedder import MockSpectralEmbedder
from backend.models.speaker_base import SpeakerEmbeddingModel
from backend.schemas import ModelError

log = logging.getLogger(__name__)

_lock = threading.Lock()
_instance: SpeakerEmbeddingModel | None = None


def get_embedder(settings: Settings | None = None) -> SpeakerEmbeddingModel:
    """Return the process-wide embedder singleton, loading it on first use."""
    global _instance
    if _instance is not None:
        return _instance
    with _lock:
        if _instance is not None:  # double-checked under lock
            return _instance
        cfg = settings or get_settings()
        name = (cfg.embedder_name or "mock").strip().lower()
        if name == "mock":
            model: SpeakerEmbeddingModel = MockSpectralEmbedder(version=cfg.embedder_version)
        elif name == "real":
            # Lazy import: keeps the mock path dependency-free.
            from backend.models.real_embedder import RealEmbedderAdapter

            model = RealEmbedderAdapter(
                weights_path=cfg.embedder_model, version=cfg.embedder_version)
        else:
            raise ModelError(
                f"Unknown VG_EMBEDDER_NAME={name!r}. Expected 'mock' or 'real'."
            )
        try:
            model.load()
        except Exception as exc:
            raise ModelError(f"Embedder load failed: {exc}") from exc
        _instance = model
        log.info("Embedder loaded once: %s (mock=%s)", model.version, model.is_mock)
        return _instance


def reset_embedder_registry() -> None:
    """Test helper: drop the cached singleton so tests can re-initialise."""
    global _instance
    with _lock:
        _instance = None
