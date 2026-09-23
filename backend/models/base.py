"""Clean model interface. Swap in a trained model without touching service code."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence


class SyntheticVoiceModel(ABC):
    """Interface every Backend 3 model adapter must implement.

    Contract:
        * ``load()`` is idempotent — safe to call multiple times, must only
          perform expensive work once per instance.
        * ``predict_proba()`` takes normalised mono float samples in
          [-1.0, 1.0] and returns P(synthetic) in [0.0, 1.0].
        * ``version`` identifies the model weights/code for audit trails.
        * ``is_mock`` is True ONLY for development stand-ins.
    """

    @property
    @abstractmethod
    def version(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def is_mock(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def load(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def predict_proba(self, audio: Sequence[float], sample_rate: int) -> float:
        raise NotImplementedError
