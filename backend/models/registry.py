"""Model registry — guarantees model weights/setup load exactly once per process."""
from __future__ import annotations

import logging
import threading

from backend.config import Settings, get_settings
from backend.models.base import SyntheticVoiceModel
from backend.models.mock_model import MockHeuristicModel
from backend.schemas import ModelError

log = logging.getLogger(__name__)

_lock = threading.Lock()
_instance: SyntheticVoiceModel | None = None


def get_model(settings: Settings | None = None) -> SyntheticVoiceModel:
    """Return the process-wide model singleton, loading it on first use."""
    global _instance
    if _instance is not None:
        return _instance
    with _lock:
        if _instance is not None:  # double-checked under lock
            return _instance
        cfg = settings or get_settings()
        name = (cfg.model_name or "mock").strip().lower()
        if name == "mock":
            model: SyntheticVoiceModel = MockHeuristicModel(version=cfg.model_version)
        else:
            raise ModelError(
                f"Unknown VG_MODEL_NAME={name!r}. Only 'mock' ships with this repo. "
                "Add a real adapter implementing SyntheticVoiceModel and register it here."
            )
        try:
            model.load()
        except Exception as exc:
            raise ModelError(f"Model load failed: {exc}") from exc
        _instance = model
        log.info("Model loaded once: %s (mock=%s)", model.version, model.is_mock)
        return _instance


def reset_model_registry() -> None:
    """Test helper: drop the cached singleton so tests can re-initialise."""
    global _instance
    with _lock:
        _instance = None
