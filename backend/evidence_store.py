"""Backend 4 Part 6: evidence domain (in-memory, development only).

Evidence records reference ALREADY-COMPUTED B3/B4 outputs -- nothing is
recalculated here. One record per available signal per chunk:

    synthetic_probability present -> ``synthetic_voice_signal``
    similarity present            -> ``speaker_similarity_signal``
    risk_score present            -> ``risk_assessment``

Missing signals yield no record (None is never converted to zero; no
record is created merely because a call exists). Vocabulary stays
observational ("signal", never "proof of fraud" / "confirmed deepfake").

Mock gate: each record inherits the mock flag of its SOURCE signal, and
descriptions state mock provenance explicitly. Mock records serve UI
development only -- never production-validated evidence.

Privacy: descriptions carry numbers and versions only. Records contain no
audio, embeddings, phone numbers, names, owners, profiles or internal
objects. ``build_evidence_for`` needs the ``Backend3Signals`` (for raw
similarity/threshold/match, which ``RiskAssessment`` intentionally does
not retain) alongside the assessment.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from backend.b4_schemas import RiskAssessment
from backend.schemas import Backend3Signals, ValidationError

log = logging.getLogger(__name__)

TYPE_SYNTHETIC = "synthetic_voice_signal"
TYPE_SIMILARITY = "speaker_similarity_signal"
TYPE_RISK = "risk_assessment"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_timestamp(timestamp: Any) -> float:
    if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
            or not 0.0 <= float(timestamp) < 1e9):
        raise ValidationError("timestamp must be call-relative seconds >= 0.")
    return float(timestamp)


@dataclass(frozen=True)
class EvidenceRecord:
    """One observational evidence record (immutable)."""

    evidence_id: str
    call_id: str
    timestamp: float
    evidence_type: str
    description: str
    risk: float | None
    source: str
    is_mock: bool
    provenance: dict
    created_at: str

    def to_dict(self) -> dict:
        import copy

        return copy.deepcopy(asdict(self))


def build_evidence_for(
    signals: Backend3Signals,
    assessment: RiskAssessment,
    timestamp: float,
) -> list[EvidenceRecord]:
    """Build evidence records for every available signal (possibly empty)."""
    if not isinstance(signals, Backend3Signals):
        raise ValidationError(
            f"Expected Backend3Signals (got {type(signals).__name__}).")
    if not isinstance(assessment, RiskAssessment):
        raise ValidationError(
            f"Expected RiskAssessment (got {type(assessment).__name__}).")
    timestamp = _check_timestamp(timestamp)
    call_id = assessment.session_id
    records: list[EvidenceRecord] = []
    if signals.synthetic is not None:
        probability = signals.synthetic.synthetic_probability
        mock_note = (" [development/mock model]"
                     if signals.synthetic.is_mock else "")
        records.append(EvidenceRecord(
            evidence_id=uuid.uuid4().hex[:12],
            call_id=call_id,
            timestamp=timestamp,
            evidence_type=TYPE_SYNTHETIC,
            description=(f"Synthetic-voice probability "
                         f"{probability * 100.0:.1f}% (label "
                         f"{signals.synthetic.label}).{mock_note}"),
            risk=round(probability * 100.0, 2),
            source="synthetic_detection",
            is_mock=signals.synthetic.is_mock,
            provenance={"detector_version": signals.synthetic.model_version},
            created_at=_utcnow_iso(),
        ))
    if signals.similarity is not None:
        similarity = signals.similarity
        mock_note = (" [development/mock model]"
                     if similarity.is_mock else "")
        records.append(EvidenceRecord(
            evidence_id=uuid.uuid4().hex[:12],
            call_id=call_id,
            timestamp=timestamp,
            evidence_type=TYPE_SIMILARITY,
            description=(f"Speaker similarity {similarity.similarity:.3f} "
                         f"against reference '{similarity.reference_id}' "
                         f"(match state: {similarity.match}).{mock_note}"),
            risk=None,  # similarity is not itself a risk number
            source="speaker_similarity",
            is_mock=similarity.is_mock,
            provenance={
                "similarity_version": similarity.model_version,
                "reference_id": similarity.reference_id,
            },
            created_at=_utcnow_iso(),
        ))
    if assessment.risk_score is not None:
        mock_note = " [development/mock result]" if assessment.is_mock else ""
        records.append(EvidenceRecord(
            evidence_id=uuid.uuid4().hex[:12],
            call_id=call_id,
            timestamp=timestamp,
            evidence_type=TYPE_RISK,
            description=(f"Call risk {float(assessment.risk_score):.1f}/100 "
                         f"({assessment.risk_level}).{mock_note}"),
            risk=float(assessment.risk_score),
            source="risk_fusion",
            is_mock=assessment.is_mock,
            provenance=dict(assessment.provenance.to_dict()),
            created_at=_utcnow_iso(),
        ))
    return records


class EvidenceStore:
    """Thread-safe in-memory evidence records (append-only)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, EvidenceRecord] = {}

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def add_all(self, records: list[EvidenceRecord]) -> list[EvidenceRecord]:
        with self._lock:
            for record in records:
                if not isinstance(record, EvidenceRecord):
                    raise ValidationError("Only EvidenceRecord objects can be stored.")
                self._records[record.evidence_id] = record
        return list(records)

    def get(self, evidence_id: str) -> EvidenceRecord:
        with self._lock:
            record = self._records.get(evidence_id)
        if record is None:
            raise ValidationError(f"evidence {evidence_id!r} not found.")
        return record

    def list_for_call(self, call_id: str) -> list[EvidenceRecord]:
        with self._lock:
            return [r for r in self._records.values() if r.call_id == call_id]

    def clear(self) -> None:
        """Remove all records (tests / controlled reset)."""
        with self._lock:
            self._records.clear()
