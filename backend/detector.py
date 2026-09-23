"""Backend 3 Part 1: synthetic voice detection over ``ProcessedSpeechChunk``.

Pipeline position::

    ProcessedSpeechChunk (Backend 2, see backend/b2_contract.py)
            v
    SyntheticVoiceDetector (this module: validate -> infer -> format)
            v
    model adapter (backend/models/base.py: SyntheticVoiceModel)
            v
    DetectionResult (backend/schemas.py, consumed by Backend 4)

Model status: DEVELOPMENT / MOCK ONLY.
    The only adapter shipping with this repo is
    ``MockHeuristicModel`` (``backend/models/mock_model.py``): a
    deterministic RMS / zero-crossing / crest heuristic with NO
    spoof-detection validity. Its scores must never drive real security
    decisions; ``DetectionResult.is_mock`` is always True until a real
    adapter lands. A real adapter (e.g. a trained countermeasure plugged
    into ``backend/models/registry.py``) replaces the mock behind the
    unchanged ``SyntheticVoiceModel`` interface -- no pipeline change needed.

Missing for real inference (explicitly out of scope here):
    1. Trained countermeasure weights + adapter (e.g. AASIST / wav2vec2
       based CM implementing ``SyntheticVoiceModel``).
    2. Learned feature frontend (filterbanks / self-supervised encoder)
       replacing raw-sample heuristics.
    3. Score calibration on in-domain data (thresholds are placeholders).
    4. Evaluation protocol on spoof corpora (see future evaluation module).

Separation of concerns:
    * input validation .... ``validate_chunk`` / ``from_dict`` (b2_contract)
    * model loading ........ process-wide singleton via ``models.registry``
    * inference ............. ``SyntheticVoiceModel.predict_proba``
    * result formatting ..... ``DetectionResult`` (+ thresholds in service)

    No inference lives in a WebSocket handler; this module has no web
    dependency.

VAD policy:
    Chunks flagged ``is_speech=False`` by Backend 2 VAD are declined with
    ``ValidationError`` (a per-chunk structured error, HTTP 422) so the
    caller skips inference without re-running VAD. The contract still
    carries such chunks -- declining them here is not a pipeline crash.

Example (how Backend 2 calls the detector)::

    from backend.detector import SyntheticVoiceDetector

    detector = SyntheticVoiceDetector()   # reuse: loads model once
    try:
        result = detector.detect_chunk(chunk_or_wire_dict)
    except ValidationError as exc:        # bad chunk: log + continue call
        ...
    except ModelError as exc:             # model failure: log + continue call
        ...
    backend4.consume(result.to_dict())
"""
from __future__ import annotations

import logging
import threading
from typing import Union

from backend.b2_contract import ProcessedSpeechChunk, from_dict, validate_chunk
from backend.config import Settings, get_settings
from backend.models.base import SyntheticVoiceModel
from backend.schemas import DetectionResult, ModelError, ValidationError
from backend.service import SyntheticVoiceDetectionService

log = logging.getLogger(__name__)

ChunkInput = Union[ProcessedSpeechChunk, dict]

_detector_lock = threading.Lock()
_detector_instance: "SyntheticVoiceDetector | None" = None


class SyntheticVoiceDetector:
    """Reusable chunk-level synthetic-voice detector.

    A thin orchestration layer over ``SyntheticVoiceDetectionService`` that
    speaks the Backend 2 chunk contract. Holds no per-chunk state; the
    underlying model is a process-wide singleton (see ``models.registry``),
    so constructing detectors is cheap and inference never reloads weights.
    Reuse one instance for the lifetime of the process / call handler.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        # Composition, not duplication: validation/inference/thresholding
        # stay in the existing, tested service layer.
        self._service = SyntheticVoiceDetectionService(self.settings)

    @property
    def model(self) -> SyntheticVoiceModel:
        """The loaded model adapter (singleton, loaded once per process)."""
        return self._service.model

    @property
    def model_version(self) -> str:
        return self.model.version

    @property
    def is_mock(self) -> bool:
        """True while the development stand-in is wired. Surface to callers
        so mock scores can never be mistaken for real detector output."""
        return self.model.is_mock

    def detect_chunk(self, chunk: ChunkInput) -> DetectionResult:
        """Score one Backend 2 chunk; return a Backend 4-ready result.

        Raises:
            ValidationError: malformed chunk, invalid audio, empty audio,
                unsupported encoding/sample rate, too-short/too-long
                speech, bad session/chunk IDs, or VAD-flagged non-speech.
            ModelError: model failed to load or infer.
        """
        if isinstance(chunk, dict):
            chunk = from_dict(chunk, self.settings)
        validated = validate_chunk(chunk, self.settings)
        if not validated.is_speech:
            raise ValidationError(
                "Chunk flagged non-speech by VAD (is_speech=False); "
                "skipping inference. (session=%s chunk=%s)"
                % (validated.session_id, validated.chunk_id)
            )
        result = self._service.detect(**validated.to_detect_kwargs())
        log.info(
            "chunk session=%s chunk=%s label=%s p=%.4f mock=%s",
            result.session_id, result.chunk_id,
            result.label, result.synthetic_probability, result.is_mock,
        )
        return result


def get_detector() -> SyntheticVoiceDetector:
    """Return the process-wide reusable detector (creates it on first use)."""
    global _detector_instance
    if _detector_instance is not None:
        return _detector_instance
    with _detector_lock:
        if _detector_instance is not None:
            return _detector_instance
        _detector_instance = SyntheticVoiceDetector()
        log.info(
            "SyntheticVoiceDetector ready: model=%s mock=%s",
            _detector_instance.model_version, _detector_instance.is_mock,
        )
        return _detector_instance


def reset_detector() -> None:
    """Test helper: drop the cached process-wide detector."""
    global _detector_instance
    with _detector_lock:
        _detector_instance = None


# Convenience functional entry point (uses the process-wide detector).
def detect_chunk(chunk: ChunkInput) -> DetectionResult:
    return get_detector().detect_chunk(chunk)
