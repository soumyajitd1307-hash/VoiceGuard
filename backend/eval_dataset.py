"""Part 9: evaluation dataset abstraction (stdlib only, no downloads).

Records carry EXPLICIT ground truth plus optional metadata. Nothing is
ever inferred: no labels from filenames (there are no filenames), no
language from audio, no speaker from audio. Splits are explicit
(``"dev"`` / ``"test"``); leakage checks fail loudly instead of silently
dropping data.

Two record kinds:

* ``LabeledSample`` -- one scored item for synthetic-voice detection:
  ``sample_id``, ``label`` ("real"|"synthetic"), optional ``score`` (a
  P(synthetic) in [0, 1] produced by a model run), ``speaker_id``,
  ``language``, ``source`` (generator/codec/family label supplied by the
  curator), ``split``, plus an optional in-memory ``audio`` tuple or an
  opaque ``audio_ref``. The framework never loads ``audio_ref`` itself.

* ``TrialRecord`` -- one speaker-verification trial: ``trial_id``,
  ``same_speaker`` ground truth, optional precomputed ``similarity`` OR
  in-memory ``reference``/``test`` vectors (scored on demand through
  ``SpeakerSimilarityService`` -- cosine math is never duplicated here),
  plus ``speaker_id`` (test side), ``reference_speaker_id``,
  ``language``, ``source``, ``split``.

Results and metrics never retain raw audio or vectors -- only IDs,
counts and statistics. Privacy fields (owner/contact/secrets) have no
place in these records at all.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Union

from backend.schemas import ValidationError
from backend.similarity import SpeakerSimilarityService

SampleInput = Union["LabeledSample", dict]
TrialInput = Union["TrialRecord", dict]

_VALID_LABELS = ("real", "synthetic")
_VALID_SPLITS = ("dev", "test", "")


def _check_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.")
    return value


def _check_label(value: Any) -> str:
    if not isinstance(value, str) or value.strip().lower() not in _VALID_LABELS:
        raise ValidationError(f"label must be one of {list(_VALID_LABELS)}.")
    return value.strip().lower()


def _check_split(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or value.strip().lower() not in _VALID_SPLITS:
        raise ValidationError(f"split must be one of {list(_VALID_SPLITS)}.")
    return value.strip().lower()


def _check_optional_text(value: Any, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string.")
    return value.strip()


def _check_score(value: Any, field: str, low: float, high: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field} must be a number.")
    f = float(value)
    if math.isnan(f) or math.isinf(f):
        raise ValidationError(f"{field} must be finite.")
    if not low <= f <= high:
        raise ValidationError(f"{field}={f!r} out of range [{low}, {high}].")
    return f


def _check_audio(value: Any) -> tuple | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise ValidationError("audio must be an in-memory float sequence, not a path.")
    try:
        items = tuple(value)
    except TypeError:
        raise ValidationError("audio must be a sequence of numbers.") from None
    for item in items:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValidationError("audio samples must be numbers.")
        if not math.isfinite(float(item)):
            raise ValidationError("audio samples must be finite.")
    return tuple(float(item) for item in items)


def _check_vector(value: Any, field: str) -> tuple | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise ValidationError(f"{field} must be a numeric sequence.")
    try:
        items = list(value)
    except TypeError:
        raise ValidationError(f"{field} must be a numeric sequence.") from None
    if len(items) == 0:
        raise ValidationError(f"{field} must be non-empty.")
    out = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValidationError(f"{field} values must be numbers.")
        f = float(item)
        if not math.isfinite(f):
            raise ValidationError(f"{field} values must be finite.")
        out.append(f)
    return tuple(out)


@dataclass(frozen=True)
class LabeledSample:
    """One labelled detection item with explicit ground truth + metadata."""

    sample_id: str
    label: str
    score: float | None = None
    speaker_id: str = ""
    language: str = ""
    source: str = ""
    split: str = ""
    audio: tuple | None = None
    audio_ref: str = ""
    # Optional per-record provenance. When present on some records, every
    # record in a run must agree -- the runner refuses mixed mock/real sets.
    is_mock: bool | None = None


@dataclass(frozen=True)
class TrialRecord:
    """One verification trial with explicit ground truth + metadata."""

    trial_id: str
    same_speaker: bool
    similarity: float | None = None
    reference: tuple | None = None
    test: tuple | None = None
    speaker_id: str = ""
    reference_speaker_id: str = ""
    language: str = ""
    source: str = ""
    split: str = ""
    # Optional per-record provenance (see LabeledSample.is_mock).
    is_mock: bool | None = None


def _check_mock_flag(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValidationError("is_mock must be a boolean.")
    return value


def coerce_sample(item: SampleInput) -> LabeledSample:
    """Validate a sample dict/record. Unknown metadata keys are ignored;
    malformed records raise (never repaired silently)."""
    if isinstance(item, LabeledSample):
        payload = {
            "sample_id": item.sample_id, "label": item.label, "score": item.score,
            "speaker_id": item.speaker_id, "language": item.language,
            "source": item.source, "split": item.split, "audio": item.audio,
            "audio_ref": item.audio_ref, "is_mock": item.is_mock,
        }
    elif isinstance(item, dict):
        payload = item
        if "sample_id" not in payload or "label" not in payload:
            raise ValidationError("Sample dicts need 'sample_id' and 'label'.")
    else:
        raise ValidationError(
            f"Sample must be a LabeledSample or dict (got {type(item).__name__}).")
    audio_ref = payload.get("audio_ref")
    if audio_ref is not None and not isinstance(audio_ref, str):
        raise ValidationError("audio_ref must be a string.")
    return LabeledSample(
        sample_id=_check_id(payload["sample_id"], "sample_id"),
        label=_check_label(payload["label"]),
        score=_check_score(payload.get("score"), "score", 0.0, 1.0),
        speaker_id=_check_optional_text(payload.get("speaker_id"), "speaker_id"),
        language=_check_optional_text(payload.get("language"), "language"),
        source=_check_optional_text(payload.get("source"), "source"),
        split=_check_split(payload.get("split")),
        audio=_check_audio(payload.get("audio")),
        audio_ref=(audio_ref or ""),
        is_mock=_check_mock_flag(payload.get("is_mock")),
    )


def coerce_trial(item: TrialInput) -> TrialRecord:
    """Validate a trial dict/record (similarity or both vectors required)."""
    if isinstance(item, TrialRecord):
        payload = {
            "trial_id": item.trial_id, "same_speaker": item.same_speaker,
            "similarity": item.similarity, "reference": item.reference,
            "test": item.test, "speaker_id": item.speaker_id,
            "reference_speaker_id": item.reference_speaker_id,
            "language": item.language, "source": item.source, "split": item.split,
            "is_mock": item.is_mock,
        }
    elif isinstance(item, dict):
        payload = item
        if "trial_id" not in payload or "same_speaker" not in payload:
            raise ValidationError("Trial dicts need 'trial_id' and 'same_speaker'.")
    else:
        raise ValidationError(
            f"Trial must be a TrialRecord or dict (got {type(item).__name__}).")
    same = payload["same_speaker"]
    if not isinstance(same, bool):
        raise ValidationError("same_speaker must be a boolean.")
    similarity = _check_score(payload.get("similarity"), "similarity", -1.0, 1.0)
    reference = _check_vector(payload.get("reference"), "reference")
    test = _check_vector(payload.get("test"), "test")
    if similarity is None and (reference is None or test is None):
        raise ValidationError(
            "Trial needs a precomputed 'similarity' or both 'reference' and 'test' vectors.")
    return TrialRecord(
        trial_id=_check_id(payload["trial_id"], "trial_id"),
        same_speaker=same,
        similarity=similarity,
        reference=reference,
        test=test,
        speaker_id=_check_optional_text(payload.get("speaker_id"), "speaker_id"),
        reference_speaker_id=_check_optional_text(
            payload.get("reference_speaker_id"), "reference_speaker_id"),
        language=_check_optional_text(payload.get("language"), "language"),
        source=_check_optional_text(payload.get("source"), "source"),
        split=_check_split(payload.get("split")),
        is_mock=_check_mock_flag(payload.get("is_mock")),
    )


def resolve_trial_similarity(
    trial: TrialRecord,
    service: SpeakerSimilarityService | None = None,
) -> float:
    """Return the trial's similarity, scoring vectors on demand (no cosine
    duplication: ``SpeakerSimilarityService`` does the math)."""
    if trial.similarity is not None:
        return trial.similarity
    assert trial.reference is not None and trial.test is not None
    scorer = service or SpeakerSimilarityService()
    return scorer.compare(list(trial.reference), list(trial.test)).similarity


def partition_by_split(
    records: Sequence,
) -> tuple[list, list]:
    """Split records on their explicit ``split`` field into (dev, test).

    Records without a split raise: held-out evaluation must never guess
    which data calibrated the threshold.
    """
    dev: list = []
    test: list = []
    for record in records:
        split = record.split if hasattr(record, "split") else ""
        if split == "dev":
            dev.append(record)
        elif split == "test":
            test.append(record)
        else:
            raise ValidationError(
                "Held-out evaluation needs explicit 'dev'/'test' splits on every record.")
    if not dev or not test:
        raise ValidationError("Need non-empty dev AND test splits for held-out evaluation.")
    return dev, test


def _audio_key(record: Any) -> tuple | None:
    audio = getattr(record, "audio", None)
    return tuple(audio) if audio is not None else None


def validate_no_leakage(
    dev: Sequence,
    test: Sequence,
    speaker_disjoint: bool = False,
    id_field: str = "sample_id",
) -> dict:
    """Fail loudly on leakage between calibration and held-out sets.

    Checks (always): duplicate IDs across sets; identical in-memory audio
    content on both sides. Optional: speaker overlap (``speaker_disjoint``
    trials/samples). Source overlap is REPORTED (note) rather than failed:
    shared generators limit generalization claims but are not leakage.
    Returns a report dict; raises ``ValidationError`` on any leak.
    """
    dev_ids = [getattr(record, id_field) for record in dev]
    test_ids = [getattr(record, id_field) for record in test]
    duplicate_ids = sorted(set(dev_ids) & set(test_ids))
    if duplicate_ids:
        raise ValidationError(
            f"Sample IDs appear in both dev and test: {duplicate_ids[:5]}.")
    dev_audio = {_audio_key(record) for record in dev} - {None}
    test_audio = {_audio_key(record) for record in test} - {None}
    if dev_audio & test_audio:
        raise ValidationError("Identical audio content appears in both dev and test.")
    report: dict[str, Any] = {
        "duplicate_ids": [],
        "audio_overlap": False,
        "speaker_overlap": [],
        "source_overlap": [],
    }
    if speaker_disjoint:
        dev_speakers = {getattr(r, "speaker_id", "") or "" for r in dev} - {""}
        test_speakers = {getattr(r, "speaker_id", "") or "" for r in test} - {""}
        overlap = sorted(dev_speakers & test_speakers)
        if overlap:
            raise ValidationError(
                f"Speakers appear in both dev and test: {overlap[:5]}.")
        report["speaker_overlap"] = []
    dev_sources = {getattr(r, "source", "") or "" for r in dev} - {""}
    test_sources = {getattr(r, "source", "") or "" for r in test} - {""}
    report["source_overlap"] = sorted(dev_sources & test_sources)
    return report
