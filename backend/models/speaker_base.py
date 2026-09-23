"""Speaker embedding model interface. Swap in a trained encoder without touching service code."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence


class SpeakerEmbeddingModel(ABC):
    """Interface every Backend 3 speaker-embedding adapter must implement.

    Contract:
        * ``load()`` is idempotent -- safe to call multiple times, must only
          perform expensive work once per instance.
        * ``embed()`` takes normalised mono float samples in [-1.0, 1.0]
          and returns a fixed-length embedding vector (tuple of floats).
          Output SHOULD be L2-normalised (unit norm) so the future
          similarity component can rely on consistent geometry.
        * ``embedding_dim`` is the vector length this adapter produces.
          Consumers must read it from here (or ``len(vector)``), never
          assume a hardcoded 192/256/512.
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

    @property
    @abstractmethod
    def embedding_dim(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def load(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def embed(self, audio: Sequence[float], sample_rate: int) -> tuple:
        raise NotImplementedError
