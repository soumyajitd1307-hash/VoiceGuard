"""Backend 3 Part 4: offline model evaluation (stdlib only, no ML dependency).

Covers synthetic-voice detection (Part 1) and speaker verification via
similarity scores (Parts 2+3). Works offline on supplied labelled records;
independent of WebSocket, frontend, database, Backend 4 and live call state.

MOCK LIMITATION -- read before quoting any number:
    The wired models (``MockHeuristicModel``, ``MockSpectralEmbedder``) are
    development stand-ins. Metrics computed from mock-model outputs on
    TEST FIXTURES are plumbing checks, NOT evidence of real-world AI
    performance. Every result carries ``is_mock`` and ``model_version``;
    fixtures in ``backend/tests/test_evaluation.py`` are labelled TEST
    FIXTURES, never benchmarks. This module reports measured numbers only
    (e.g. ``accuracy = 0.91``); it never concludes a model is "accurate",
    "reliable" or "production ready".

Input records (in-memory; no dataset download, no credentials)::

    DetectionSample(score=0.91, label="synthetic")   # score = P(synthetic)
    VerificationTrial(similarity=0.84, same_speaker=True)

    Plain ``{"score": ..., "label": ...}`` / ``{"similarity": ...,
    "same_speaker": ...}`` dicts are accepted interchangeably.

Metric definitions:
    * Detection (positive class = "synthetic", predict synthetic iff
      ``score >= threshold``): accuracy, precision (TP/(TP+FP)), recall
      aka TPR (TP/(TP+FN)), F1, FPR (FP/(FP+TN)). Any metric whose
      denominator is zero is None -- never divided by zero, never invented.
    * ROC-AUC: exact rank-based (Mann-Whitney, tie-averaged) area under the
      empirical ROC curve over the supplied scores. None when fewer than
      two classes are present. No sklearn dependency.
    * Verification (accept iff ``similarity >= threshold``):
      FAR (false acceptance rate) = falsely accepted impostor trials /
      all impostor trials; FRR (false rejection rate) = falsely rejected
      genuine trials / all genuine trials; TAR = 1 - FRR; TRR = 1 - FAR.
      This is verification ("matches the CLAIMED reference?"), not
      identification ("which person is this?").
    * EER (equal error rate): operating point over the supplied trial
      scores minimising |FAR - FRR| (candidates: below-min, each unique
      score, midpoints, above-max; ties broken deterministically towards
      higher thresholds); EER = (FAR + FRR) / 2 there. None without >=1
      genuine AND >=1 impostor trial.

Threshold sweeps return the complete table (list of row dicts) plus, for
detection, the argmax-F1 candidate threshold explicitly labelled as a
mathematical candidate -- NOT a production recommendation. Sweeps never
mutate application configuration (``VG_SIMILARITY_THRESHOLD`` et al.).

Recommended real-evaluation datasets (future, external, not downloaded
here): ASVspoof-style corpora for detection; VoxCeleb-style trial lists
for verification. Adapter shape: score/label lists for detection;
(similarity, same_speaker) trial lists for verification, where
similarities come from ``SpeakerSimilarityService.compare`` (see
``trial_from_embeddings``, which reuses that service -- cosine logic is
never duplicated here).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Sequence, Union

from backend.schemas import (
    DetectionEvaluationResult,
    ValidationError,
    VerificationEvaluationResult,
)
from backend.similarity import SpeakerSimilarityService, VectorInput

log = logging.getLogger(__name__)

DetectionInput = Union["DetectionSample", dict]
TrialInput = Union["VerificationTrial", dict]

_VALID_LABELS = ("real", "synthetic")


@dataclass(frozen=True)
class DetectionSample:
    """One labelled detection example. ``score`` = P(synthetic) in [0, 1]."""

    score: float
    label: str


@dataclass(frozen=True)
class VerificationTrial:
    """One verification trial. ``similarity`` = cosine score in [-1, 1]."""

    similarity: float
    same_speaker: bool


def _check_score(value: Any, field: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field} must be a number (got {type(value).__name__}).")
    f = float(value)
    if math.isnan(f):
        raise ValidationError(f"{field} must not be NaN.")
    if math.isinf(f):
        raise ValidationError(f"{field} must be finite.")
    if not low <= f <= high:
        raise ValidationError(f"{field}={f!r} out of range [{low}, {high}].")
    return f


def _coerce_detection_sample(item: DetectionInput) -> DetectionSample:
    if isinstance(item, DetectionSample):
        score, label = item.score, item.label
    elif isinstance(item, dict):
        if "score" not in item or "label" not in item:
            raise ValidationError("Detection sample dicts need 'score' and 'label' keys.")
        score, label = item["score"], item["label"]
    else:
        raise ValidationError(
            f"Detection sample must be a DetectionSample or dict (got {type(item).__name__})."
        )
    if not isinstance(label, str) or label.strip().lower() not in _VALID_LABELS:
        raise ValidationError(f"label must be one of {list(_VALID_LABELS)} (got {label!r}).")
    return DetectionSample(
        score=_check_score(score, "score", 0.0, 1.0), label=label.strip().lower()
    )


def _coerce_trial(item: TrialInput) -> VerificationTrial:
    if isinstance(item, VerificationTrial):
        similarity, same = item.similarity, item.same_speaker
    elif isinstance(item, dict):
        if "similarity" not in item or "same_speaker" not in item:
            raise ValidationError("Trial dicts need 'similarity' and 'same_speaker' keys.")
        similarity, same = item["similarity"], item["same_speaker"]
    else:
        raise ValidationError(
            f"Trial must be a VerificationTrial or dict (got {type(item).__name__})."
        )
    if not isinstance(same, bool):
        raise ValidationError("same_speaker must be a boolean.")
    return VerificationTrial(
        similarity=_check_score(similarity, "similarity", -1.0, 1.0), same_speaker=same
    )


def _safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _check_detection_threshold(threshold: Any) -> float:
    return _check_score(threshold, "threshold", 0.0, 1.0)


def _check_similarity_threshold(threshold: Any) -> float:
    return _check_score(threshold, "threshold", -1.0, 1.0)


def _confusion(samples: Sequence[DetectionSample], threshold: float) -> tuple[int, int, int, int]:
    tp = tn = fp = fn = 0
    for sample in samples:
        predicted_synthetic = sample.score >= threshold
        if sample.label == "synthetic":
            if predicted_synthetic:
                tp += 1
            else:
                fn += 1
        else:
            if predicted_synthetic:
                fp += 1
            else:
                tn += 1
    return tp, tn, fp, fn


def _roc_auc(samples: Sequence[DetectionSample]) -> float | None:
    """Exact rank-based ROC-AUC (Mann-Whitney U, tie-averaged ranks)."""
    positives = sorted(s.score for s in samples if s.label == "synthetic")
    negatives = sorted(s.score for s in samples if s.label == "real")
    if not positives or not negatives:
        return None
    # Tie-averaged ranks over the pooled sorted scores.
    pooled = sorted([(s, 1) for s in positives] + [(s, 0) for s in negatives])
    rank_sum = 0.0
    i = 0
    n = len(pooled)
    while i < n:
        j = i
        while j < n and pooled[j][0] == pooled[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0  # 1-based ranks i+1 .. j
        rank_sum += avg_rank * sum(label for _, label in pooled[i:j])
        i = j
    n_pos, n_neg = len(positives), len(negatives)
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def evaluate_detection(
    samples: Sequence[DetectionInput],
    threshold: float = 0.5,
    model_version: str = "unknown",
    is_mock: bool = True,
) -> DetectionEvaluationResult:
    """Score one labelled detection set at a single threshold (offline)."""
    threshold = _check_detection_threshold(threshold)
    try:
        items = list(samples)
    except TypeError:
        raise ValidationError("samples must be a sequence.") from None
    clean = [_coerce_detection_sample(item) for item in items]
    notes: list[str] = []
    if not clean:
        notes.append("empty dataset: all metrics are None.")
    tp, tn, fp, fn = _confusion(clean, threshold)
    real_count = tn + fp
    synthetic_count = tp + fn
    if real_count == 0 or synthetic_count == 0:
        notes.append("single-class dataset: some metrics are None; roc_auc is None.")
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)
    elif precision is not None and recall is not None:
        f1 = 0.0 if (tp + fp + fn) > 0 else None
    return DetectionEvaluationResult(
        model_version=model_version,
        is_mock=is_mock,
        sample_count=len(clean),
        real_count=real_count,
        synthetic_count=synthetic_count,
        threshold=threshold,
        true_positives=tp,
        true_negatives=tn,
        false_positives=fp,
        false_negatives=fn,
        accuracy=_safe_div(tp + tn, len(clean)) if clean else None,
        precision=precision,
        recall=recall,
        f1=f1,
        false_positive_rate=_safe_div(fp, fp + tn),
        true_positive_rate=_safe_div(tp, tp + fn),
        roc_auc=_roc_auc(clean),
        notes=tuple(notes),
    )


def detection_threshold_sweep(
    samples: Sequence[DetectionInput],
    thresholds: Sequence[float],
    model_version: str = "unknown",
    is_mock: bool = True,
) -> dict:
    """Evaluate detection metrics across thresholds; returns the full table.

    Returns ``{"rows": [...], "max_f1_threshold": ...}`` where each row holds
    threshold/TP/TN/FP/FN/accuracy/precision/recall/f1/fpr/tpr.
    ``max_f1_threshold`` is the argmax-F1 candidate (first wins ties) --
    a mathematical property of the table, NOT a production recommendation.
    """
    clean = [_coerce_detection_sample(item) for item in samples]
    threshold_list = [_check_detection_threshold(t) for t in thresholds]
    if len(threshold_list) == 0:
        raise ValidationError("thresholds must contain at least one value.")
    rows = []
    for thr in threshold_list:
        result = evaluate_detection(clean, thr, model_version, is_mock)
        rows.append(
            {
                "threshold": thr,
                "true_positives": result.true_positives,
                "true_negatives": result.true_negatives,
                "false_positives": result.false_positives,
                "false_negatives": result.false_negatives,
                "accuracy": result.accuracy,
                "precision": result.precision,
                "recall": result.recall,
                "f1": result.f1,
                "false_positive_rate": result.false_positive_rate,
                "true_positive_rate": result.true_positive_rate,
            }
        )
    scored = [(row["f1"], row["threshold"]) for row in rows if row["f1"] is not None]
    best = max(scored, key=lambda pair: (pair[0], -pair[1]))[1] if scored else None
    return {
        "model_version": model_version,
        "is_mock": is_mock,
        "evaluation_type": "synthetic_detection_sweep",
        "rows": rows,
        "max_f1_threshold": best,
    }


def _verification_rates(
    trials: Sequence[VerificationTrial], threshold: float
) -> tuple[float | None, float | None, float | None, float | None]:
    genuine = [t for t in trials if t.same_speaker]
    impostor = [t for t in trials if not t.same_speaker]
    fa = sum(1 for t in impostor if t.similarity >= threshold)
    fr = sum(1 for t in genuine if t.similarity < threshold)
    far = _safe_div(fa, len(impostor))
    frr = _safe_div(fr, len(genuine))
    tar = 1.0 - frr if frr is not None else None
    trr = 1.0 - far if far is not None else None
    return far, frr, tar, trr


def _eer(trials: Sequence[VerificationTrial]) -> tuple[float | None, float | None, str | None]:
    """Empirical EER from trial scores. Returns (eer, eer_threshold, note)."""
    genuine = [t.similarity for t in trials if t.same_speaker]
    impostor = [t.similarity for t in trials if not t.same_speaker]
    if not genuine or not impostor:
        return None, None, "EER needs >=1 genuine AND >=1 impostor trial."
    uniques = sorted(set(genuine + impostor))
    # Candidates: below-min, each unique score, midpoints, above-max.
    candidates: list[float] = [uniques[0] - 1e-9]
    for prev, cur in zip(uniques, uniques[1:]):
        candidates.append(prev)
        candidates.append((prev + cur) / 2.0)
    candidates += [uniques[-1], uniques[-1] + 1e-9]
    best: tuple[float | None, float | None] = (None, None)
    best_gap: float | None = None
    for thr in sorted(candidates, reverse=True):
        far, frr, _, _ = _verification_rates(trials, thr)
        assert far is not None and frr is not None  # both classes present
        gap = abs(far - frr)
        if best_gap is None or gap < best_gap:
            best_gap = gap
            best = ((far + frr) / 2.0, thr)
    eer, eer_threshold = best
    assert eer is not None and eer_threshold is not None
    return eer, eer_threshold, None


def evaluate_verification(
    trials: Sequence[TrialInput],
    threshold: float | None = None,
    model_version: str = "unknown",
    is_mock: bool = True,
) -> VerificationEvaluationResult:
    """Score one verification trial set (offline)."""
    if threshold is not None:
        threshold = _check_similarity_threshold(threshold)
    try:
        items = list(trials)
    except TypeError:
        raise ValidationError("trials must be a sequence.") from None
    clean = [_coerce_trial(item) for item in items]
    notes: list[str] = []
    if not clean:
        notes.append("empty trial set: all metrics are None.")
    genuine_count = sum(1 for t in clean if t.same_speaker)
    impostor_count = len(clean) - genuine_count
    if clean and (genuine_count == 0 or impostor_count == 0):
        notes.append("single-class trial set: some metrics and EER are None.")
    if threshold is None:
        notes.append("no threshold: match rates are None (score distribution only).")
        far = frr = tar = trr = None
    else:
        far, frr, tar, trr = _verification_rates(clean, threshold)
    eer, eer_threshold, eer_note = _eer(clean)
    if eer_note is not None:
        notes.append(eer_note)
    return VerificationEvaluationResult(
        model_version=model_version,
        is_mock=is_mock,
        trial_count=len(clean),
        genuine_count=genuine_count,
        impostor_count=impostor_count,
        threshold=threshold,
        far=far,
        frr=frr,
        tar=tar,
        trr=trr,
        eer=eer,
        eer_threshold=eer_threshold,
        notes=tuple(notes),
    )


def verification_threshold_sweep(
    trials: Sequence[TrialInput],
    thresholds: Sequence[float],
    model_version: str = "unknown",
    is_mock: bool = True,
) -> dict:
    """Evaluate FAR/FRR/TAR/TRR across similarity thresholds (full table)."""
    clean = [_coerce_trial(item) for item in trials]
    threshold_list = [_check_similarity_threshold(t) for t in thresholds]
    if len(threshold_list) == 0:
        raise ValidationError("thresholds must contain at least one value.")
    rows = []
    for thr in threshold_list:
        far, frr, tar, trr = _verification_rates(clean, thr)
        rows.append(
            {"threshold": thr, "far": far, "frr": frr, "tar": tar, "trr": trr}
        )
    return {
        "model_version": model_version,
        "is_mock": is_mock,
        "evaluation_type": "speaker_verification_sweep",
        "genuine_count": sum(1 for t in clean if t.same_speaker),
        "impostor_count": sum(1 for t in clean if not t.same_speaker),
        "rows": rows,
    }


def trial_from_embeddings(
    reference: VectorInput,
    current: VectorInput,
    same_speaker: bool,
    service: SpeakerSimilarityService | None = None,
) -> VerificationTrial:
    """Build a trial from embedding inputs, reusing the similarity service.

    Cosine math lives in ``SpeakerSimilarityService`` -- never duplicated
    here. ``same_speaker`` is the ground-truth trial label supplied by the
    dataset curator.
    """
    if not isinstance(same_speaker, bool):
        raise ValidationError("same_speaker must be a boolean.")
    scorer = service or SpeakerSimilarityService()
    result = scorer.compare(reference, current)
    return VerificationTrial(similarity=result.similarity, same_speaker=same_speaker)
