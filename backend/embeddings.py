"""Backend 3 Part 2: speaker embeddings over ``ProcessedSpeechChunk``.

Pipeline position::

    ProcessedSpeechChunk (Backend 2, see backend/b2_contract.py)
            v
    SpeakerEmbeddingService (this module: validate -> infer -> format)
            v
    SpeakerEmbeddingModel adapter (backend/models/speaker_base.py)
            v
    SpeakerEmbeddingResult (backend/schemas.py, future Backend 4 voice profiles)

Model status: DEVELOPMENT / MOCK ONLY.
    The only adapter shipping with this repo is ``MockSpectralEmbedder``
    (``backend/models/mock_embedder.py``): a deterministic time-domain
    descriptor with NO speaker-recognition validity. Its vectors must
    never drive verification decisions; ``SpeakerEmbeddingResult.is_mock``
    is always True until a real encoder lands. A real encoder (e.g.
    ECAPA-TDNN ONNX plugged into ``backend/models/embed_registry.py``)
    replaces the mock behind the unchanged ``SpeakerEmbeddingModel``
    interface -- no pipeline change needed.

Missing for production-quality speaker verification:
    1. Trained encoder weights + adapter (ECAPA-TDNN / x-vector / etc.).
    2. Learned frontend (filterbanks / SSL encoder) replacing statistics.
    3. Calibration + evaluation on speaker-verification corpora
       (VoxCeleb-style trials, EER/minDCF reporting).
    4. Backend 4 voice-profile storage + Part 3 similarity (explicitly
       out of scope here).

Separation of concerns:
    * input validation .... ``validate_chunk`` / ``from_dict`` (b2_contract)
    * audio normalisation .. ``normalise_audio`` (backend/audio.py, shared
      with the detection path -- one format, no duplication)
    * model loading ........ process-wide singleton via embed_registry
    * embedding inference ... ``SpeakerEmbeddingModel.embed``
    * output formatting ..... ``SpeakerEmbeddingResult``

    No inference lives in a WebSocket handler; this module has no web
    dependency.

Audio policy:
    * VAD-flagged non-speech (``is_speech=False``) is declined with
      ``ValidationError`` (per-chunk structured error, HTTP 422).
    * Chunks shorter than ``min_speech_s`` (default:
      ``Settings.min_duration_s``) are declined as insufficient speech --
      embeddings from unusably short audio are never silently returned.
      A real encoder typically wants ~1s+; raise ``min_speech_s`` when
      one lands, with no code change.
    * Output vectors are L2 unit-norm (mock normalises; the service
      verifies norm ~= 1.0) so Part 3 cosine similarity is well-defined.

Example (how Backend 2 will call the service)::

    from backend.embeddings import SpeakerEmbeddingService

    service = SpeakerEmbeddingService()   # reuse: loads encoder once
    try:
        result = service.embed(chunk_or_wire_dict)
    except ValidationError as exc:        # bad/short/non-speech: skip chunk
        ...
    except ModelError as exc:             # encoder failure: log + continue
        ...
    # Backend 4 (future): store/match result.to_dict()["embedding"]
"""
from __future__ import annotations

import logging
import math
import threading
import time
from typing import Union

from backend.audio import normalise_audio
from backend.b2_contract import ProcessedSpeechChunk, from_dict, validate_chunk
from backend.config import Settings, get_settings
from backend.models import embed_registry
from backend.models.speaker_base import SpeakerEmbeddingModel
from backend.schemas import ModelError, SpeakerEmbeddingResult, ValidationError

log = logging.getLogger(__name__)

EmbedInput = Union[ProcessedSpeechChunk, dict]

_service_lock = threading.Lock()
_service_instance: "SpeakerEmbeddingService | None" = None


class SpeakerEmbeddingService:
    """Reusable chunk-level speaker embedding service.

    Holds no per-chunk state; the underlying encoder is a process-wide
    singleton, so constructing services is cheap and inference never
    reloads weights. Reuse one instance per process / call handler.
    """

    def __init__(self, settings: Settings | None = None, min_speech_s: float | None = None) -> None:
        self.settings = settings or get_settings()
        # Minimum speech worth embedding. Defaults to the contract minimum;
        # raise (e.g. to ~1.0) when a real encoder lands.
        self.min_speech_s = (
            self.settings.min_duration_s if min_speech_s is None else min_speech_s
        )
        if self.min_speech_s <= 0:
            raise ValueError("min_speech_s must be positive.")
        level = getattr(logging, self.settings.log_level.upper(), logging.INFO)
        logging.basicConfig(level=level, force=False)

    @property
    def model(self) -> SpeakerEmbeddingModel:
        """The loaded encoder adapter (singleton, loaded once per process)."""
        return embed_registry.get_embedder(self.settings)

    @property
    def model_version(self) -> str:
        return self.model.version

    @property
    def embedding_dim(self) -> int:
        """Dimension produced by the wired encoder (never hardcoded)."""
        return self.model.embedding_dim

    @property
    def is_mock(self) -> bool:
        """True while the development stand-in is wired. Surface to callers
        so mock vectors can never be mistaken for real speaker embeddings."""
        return self.model.is_mock

    def embed(self, chunk: EmbedInput) -> SpeakerEmbeddingResult:
        """Embed one Backend 2 chunk; return a Backend 4-ready result.

        Raises:
            ValidationError: malformed chunk, invalid/empty audio,
                unsupported encoding/sample rate, bad session/chunk IDs,
                VAD-flagged non-speech, or insufficient speech duration.
            ModelError: encoder failed to load or infer, or returned a
                malformed vector.
        """
        start = time.perf_counter()
        if isinstance(chunk, dict):
            chunk = from_dict(chunk, self.settings)
        validated = validate_chunk(chunk, self.settings)
        if not validated.is_speech:
            raise ValidationError(
                "Chunk flagged non-speech by VAD (is_speech=False); "
                "skipping embedding. (session=%s chunk=%s)"
                % (validated.session_id, validated.chunk_id)
            )
        samples = normalise_audio(validated.audio, validated.audio_encoding)
        duration_s = len(samples) / validated.sample_rate
        if duration_s < self.min_speech_s:
            raise ValidationError(
                f"Insufficient speech for embedding: {duration_s:.3f}s "
                f"< minimum {self.min_speech_s:.3f}s. (session={validated.session_id} "
                f"chunk={validated.chunk_id})"
            )
        try:
            vector = self.model.embed(samples, validated.sample_rate)
        except (ValidationError, ModelError):
            raise
        except Exception as exc:
            log.exception(
                "Embedder inference failed (session=%s chunk=%s)",
                validated.session_id, validated.chunk_id,
            )
            raise ModelError(f"Embedder inference failed: {exc}") from exc
        embedding = _check_vector(vector, self.model.embedding_dim)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        result = SpeakerEmbeddingResult(
            session_id=validated.session_id,
            chunk_id=validated.chunk_id,
            embedding=embedding,
            dimension=len(embedding),  # derived from actual output
            model_version=self.model.version,
            is_mock=self.model.is_mock,
            processing_time_ms=round(elapsed_ms, 3),
        )
        log.info(
            "embed session=%s chunk=%s dim=%d ms=%.2f mock=%s",
            result.session_id, result.chunk_id, result.dimension,
            elapsed_ms, result.is_mock,
        )
        return result


def _check_vector(vector: object, expected_dim: int) -> tuple:
    if not isinstance(vector, (tuple, list)):
        raise ModelError(f"Embedder returned non-sequence vector ({type(vector).__name__}).")
    if len(vector) != expected_dim:
        raise ModelError(
            f"Embedder dim mismatch: got {len(vector)}, expected {expected_dim}."
        )
    out = []
    for idx, value in enumerate(vector):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ModelError(f"embedding[{idx}] must be a number.")
        f = float(value)
        if not math.isfinite(f):
            raise ModelError(f"embedding[{idx}] must be finite.")
        out.append(f)
    norm = math.sqrt(sum(v * v for v in out))
    if abs(norm - 1.0) > 1e-3:
        raise ModelError(f"Embedder vector not L2-normalised (norm={norm:.4f}).")
    return tuple(out)


def get_embedding_service() -> SpeakerEmbeddingService:
    """Return the process-wide reusable service (creates it on first use)."""
    global _service_instance
    if _service_instance is not None:
        return _service_instance
    with _service_lock:
        if _service_instance is not None:
            return _service_instance
        _service_instance = SpeakerEmbeddingService()
        log.info(
            "SpeakerEmbeddingService ready: model=%s dim=%d mock=%s",
            _service_instance.model_version,
            _service_instance.embedding_dim,
            _service_instance.is_mock,
        )
        return _service_instance


def reset_embedding_service() -> None:
    """Test helper: drop the cached process-wide service."""
    global _service_instance
    with _service_lock:
        _service_instance = None


# Convenience functional entry point (uses the process-wide service).
def embed_chunk(chunk: EmbedInput) -> SpeakerEmbeddingResult:
    return get_embedding_service().embed(chunk)
