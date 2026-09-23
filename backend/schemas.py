"""Input/output schemas for Backend 3 synthetic voice detection."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

DetectionLabel = Literal["real", "synthetic", "uncertain"]
MatchLabel = Literal["match", "non_match", "uncertain"]


@dataclass(frozen=True)
class DetectionRequest:
    """Validated detection input.

    Attributes:
        audio: normalised mono samples in [-1.0, 1.0] (converted from
            PCM16 bytes or float sequences by the service layer).
        sample_rate: sample rate in Hz of ``audio``.
        session_id: Backend 2 call/session identifier (opaque string).
        chunk_id: Backend 2 chunk identifier within the session.
    """

    audio: tuple
    sample_rate: int
    session_id: str
    chunk_id: str


@dataclass(frozen=True)
class DetectionResult:
    """Validated detection output consumed by Backend 4."""

    label: DetectionLabel
    synthetic_probability: float
    model_version: str
    processing_time_ms: float
    session_id: str
    chunk_id: str
    # Always True for the dev/mock adapter. Present so no consumer can
    # mistake mock output for a real detector. Future real adapters set False.
    is_mock: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SpeakerEmbeddingResult:
    """Structured speaker embedding output (future voice-profile input for Backend 4).

    Attributes:
        embedding: L2-normalised unit-norm vector (tuple of floats).
            Development/mock vectors carry NO speaker identity.
        dimension: vector length, derived from the actual model output
            (``len(embedding)``); never a hardcoded assumption.
    """

    session_id: str
    chunk_id: str
    embedding: tuple
    dimension: int
    model_version: str
    is_mock: bool
    processing_time_ms: float

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["embedding"] = list(self.embedding)
        return payload


@dataclass(frozen=True)
class SimilarityResult:
    """Structured speaker-similarity output for Backend 4 impersonation/risk logic.

    Attributes:
        similarity: cosine similarity in [-1.0, 1.0]; higher means more alike.
            With mock embeddings this number has NO speaker-verification
            meaning -- it only exercises the plumbing.
        threshold: operating point used for ``match``, or None when no
            decision was requested (then ``match`` is "uncertain").
        match: "match" / "non_match" only when a threshold is configured;
            otherwise "uncertain". Never a validated identity claim while
            ``is_mock`` is True.
        reference_id: Backend 4 voice-profile identifier supplied by the
            caller (metadata only; no profile storage lives in Backend 3).
    """

    reference_id: str
    session_id: str
    chunk_id: str
    similarity: float
    threshold: float | None
    match: MatchLabel
    model_version: str
    is_mock: bool
    processing_time_ms: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DetectionEvaluationResult:
    """Offline evaluation of synthetic-voice detection scores.

    All rate metrics are None when their denominator is zero (never
    invented, never divided by zero). ``roc_auc`` is None when the sample
    set holds fewer than two classes. ``notes`` records such conditions.
    This struct reports measured numbers only -- never a claim that the
    model is "accurate" or "production ready".
    """

    model_version: str
    is_mock: bool
    sample_count: int
    real_count: int
    synthetic_count: int
    threshold: float
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    accuracy: float | None
    precision: float | None
    recall: float | None
    f1: float | None
    false_positive_rate: float | None
    true_positive_rate: float | None
    roc_auc: float | None
    evaluation_type: str = "synthetic_detection"
    notes: tuple = ()

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["notes"] = list(self.notes)
        return payload


@dataclass(frozen=True)
class VerificationEvaluationResult:
    """Offline evaluation of speaker-verification trials.

    Verification here means "does this sample match the CLAIMED reference
    speaker" (not "which person is this"). FAR/FRR/TAR/TRR are None when
    their trial class is absent; ``eer`` is None when EER is not computable
    (needs >=1 genuine AND >=1 impostor trial). Reasons land in ``notes``.
    """

    model_version: str
    is_mock: bool
    trial_count: int
    genuine_count: int
    impostor_count: int
    threshold: float | None
    far: float | None
    frr: float | None
    tar: float | None
    trr: float | None
    eer: float | None
    eer_threshold: float | None
    evaluation_type: str = "speaker_verification"
    notes: tuple = ()

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["notes"] = list(self.notes)
        return payload


@dataclass(frozen=True)
class Backend3Signals:
    """Stable ML-signal bundle at the Backend 3 -> Backend 4 boundary.

    A passive evidence carrier: each present signal nests the corresponding
    Backend 3 result object unchanged (no duplication, no re-computation).
    Absent signals are None -- never fabricated, never 0.0 placeholders.

    This struct contains NO risk score, NO risk label and NO application
    verdict; combining ``synthetic_probability`` and ``similarity`` into
    risk is Backend 4's job. ``to_dict(include_embedding=False)`` withholds
    the raw embedding (biometric-derived, sensitive) while keeping its
    dimension/version/mock provenance for similarity-only consumers.
    """

    session_id: str
    chunk_id: str
    synthetic: DetectionResult | None = None
    speaker: SpeakerEmbeddingResult | None = None
    similarity: SimilarityResult | None = None

    def to_dict(self, include_embedding: bool = True) -> dict:
        payload = {
            "session_id": self.session_id,
            "chunk_id": self.chunk_id,
            "synthetic": self.synthetic.to_dict() if self.synthetic is not None else None,
            "speaker": None,
            "similarity": self.similarity.to_dict() if self.similarity is not None else None,
            "metadata": {
                "processing_time_ms": round(
                    sum(
                        part.processing_time_ms
                        for part in (self.synthetic, self.speaker, self.similarity)
                        if part is not None
                    ),
                    3,
                )
            },
        }
        if self.speaker is not None:
            speaker_dict = self.speaker.to_dict()
            if not include_embedding:
                speaker_dict.pop("embedding", None)
                speaker_dict["embedding_withheld"] = True
            payload["speaker"] = speaker_dict
        return payload


class ValidationError(ValueError):
    """Raised when caller-supplied input fails validation (maps to 422)."""


class ModelError(RuntimeError):
    """Raised when the model fails to load or infer (maps to 500)."""
