"""Part 9: held-out evaluation runner (stdlib only, deterministic).

Orchestrates the Part 4 primitives (``backend/evaluation.py`` -- confusion,
sweeps, ROC-AUC, EER; reused, never duplicated) into rigorous runs:

    dev split  ->  sweep + candidate operating point (+ calibration fit)
    leakage validation between splits (never silent)
    test split ->  final metrics at the dev-chosen point (+ held-out
                    calibration assessment, subgroups, bootstrap CIs)

Honesty architecture:
    * Threshold candidates (``max_f1``, ``youden_j``, ``eer``) are
      mathematical properties of the DEVELOPMENT table, labelled
      ``candidate`` -- never production thresholds, never written back
      into application configuration (B4's HIGH=70 and fusion weights are
      untouched by this module; a regression test pins that).
    * Mock and real runs never mix: ``is_mock`` + versions ride on every
      summary, and helpers refuse to aggregate across mock boundaries.
    * Bootstrap CIs use an explicit seed (reproducible); tiny samples
      yield documented ``None`` instead of misleading precision.
    * Summaries carry dataset/model provenance, seed, method and timestamp,
      and never raw audio, vectors, owners or secrets.
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from backend import evaluation as _base
from backend.eval_calibration import (
    IsotonicCalibration,
    PlattCalibration,
    brier_score,
    fit_isotonic,
    fit_platt,
    log_loss,
    reliability_summary,
)
from backend.eval_dataset import (
    LabeledSample,
    TrialRecord,
    coerce_sample,
    coerce_trial,
    resolve_trial_similarity,
    validate_no_leakage,
)
from backend.schemas import ValidationError
from backend.similarity import SpeakerSimilarityService

log = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------ schemas

@dataclass(frozen=True)
class DetectionEvalSummary:
    """Single-threshold detection summary on one split (dev or test)."""

    dataset_id: str
    split: str
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
    specificity: float | None
    false_positive_rate: float | None
    false_negative_rate: float | None
    true_positive_rate: float | None
    f1: float | None
    balanced_accuracy: float | None
    roc_auc: float | None
    average_precision: float | None
    brier_score: float | None
    log_loss: float | None
    notes: tuple = ()
    generated_at: str = ""

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["notes"] = list(self.notes)
        return payload


@dataclass(frozen=True)
class VerificationEvalSummary:
    """Single-threshold verification summary on one split."""

    dataset_id: str
    split: str
    model_version: str
    embedder_version: str
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
    notes: tuple = ()
    generated_at: str = ""

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["notes"] = list(self.notes)
        return payload


@dataclass(frozen=True)
class CalibrationEvalSummary:
    """Calibration fit on dev, assessed on a split (usually held-out)."""

    dataset_id: str
    split: str
    model_version: str
    is_mock: bool
    method: str
    parameters: dict
    dev_count: int
    test_count: int
    brier_before: float | None
    brier_after: float | None
    log_loss_before: float | None
    log_loss_after: float | None
    reliability: tuple = ()
    notes: tuple = ()
    generated_at: str = ""

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["reliability"] = list(self.reliability)
        payload["notes"] = list(self.notes)
        return payload


@dataclass(frozen=True)
class HeldoutReport:
    """Complete dev->test run. ``candidate`` is evidence for a human
    decision, never an applied production threshold."""

    dataset_id: str
    kind: str
    model_version: str
    is_mock: bool
    candidate: dict
    dev_summary: dict
    test_summary: dict
    leakage_report: dict
    generated_at: str = ""

    def to_dict(self) -> dict:
        import copy

        return copy.deepcopy(asdict(self))


# ------------------------------------------------------------ helpers

def _require_uniform_mock(records: Sequence, role: str) -> None:
    """Refuse runs mixing mock and real records. Unflagged records (None)
    are neutral; any disagreement among flagged records raises."""
    flags = {record.is_mock for record in records
             if getattr(record, "is_mock", None) is not None}
    if len(flags) > 1:
        raise ValidationError(
            f"Refusing to mix mock and real {role} in one evaluation.")

def _require_scores(samples: Sequence[LabeledSample]) -> list[float]:
    scores = [sample.score for sample in samples]
    missing = sum(1 for score in scores if score is None)
    if missing:
        raise ValidationError(
            f"Evaluation needs scores on every sample ({missing} missing).")
    return [float(score) for score in scores]  # type: ignore[misc]


def _labels_01(samples: Sequence[LabeledSample]) -> list[int]:
    return [1 if sample.label == "synthetic" else 0 for sample in samples]


def _average_precision(scores: Sequence[float], labels: Sequence[int]) -> float | None:
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    total_positive = sum(labels)
    if total_positive == 0:
        return None
    area = 0.0
    hits = 0
    previous_recall = 0.0
    for rank, index in enumerate(order, start=1):
        if labels[index] == 1:
            hits += 1
            recall = hits / total_positive
            area += (recall - previous_recall) * (hits / rank)
            previous_recall = recall
    return area


# ------------------------------------------------------------ detection

def detection_sweep_extended(
    samples: Sequence,
    thresholds: Sequence[float],
    model_version: str = "unknown",
    is_mock: bool = True,
) -> dict:
    """Part 4 sweep rows plus TNR/FNR/balanced-accuracy and ROC points."""
    clean = [coerce_sample(item) for item in samples]
    # Rows are computed here (not via base) so every row can carry the
    # extended fields; the confusion/rate math matches
    # backend/evaluation.py exactly (same >= rule, same None-on-zero rules).
    threshold_list = [_base._check_detection_threshold(t) for t in thresholds]
    if not threshold_list:
        raise ValidationError("thresholds must contain at least one value.")
    rows = []
    for threshold in threshold_list:
        tp, tn, fp, fn = _base._confusion(clean, threshold)
        precision = _base._safe_div(tp, tp + fp)
        recall = _base._safe_div(tp, tp + fn)
        tnr = _base._safe_div(tn, tn + fp)
        f1 = None
        if precision is not None and recall is not None and (precision + recall) > 0:
            f1 = 2 * precision * recall / (precision + recall)
        elif precision is not None and recall is not None:
            f1 = 0.0 if (tp + fp + fn) > 0 else None
        balanced = None
        if recall is not None and tnr is not None:
            balanced = (recall + tnr) / 2.0
        rows.append({
            "threshold": threshold,
            "true_positives": tp, "true_negatives": tn,
            "false_positives": fp, "false_negatives": fn,
            "accuracy": _base._safe_div(tp + tn, len(clean)) if clean else None,
            "precision": precision, "recall": recall,
            "specificity": tnr,
            "true_positive_rate": recall,
            "false_positive_rate": _base._safe_div(fp, fp + tn),
            "false_negative_rate": _base._safe_div(fn, fn + tp),
            "f1": f1, "balanced_accuracy": balanced,
        })
    roc_points = sorted(
        ({"threshold": row["threshold"],
          "false_positive_rate": row["false_positive_rate"],
          "true_positive_rate": row["true_positive_rate"]} for row in rows),
        key=lambda point: (point["false_positive_rate"] is None,
                           point["false_positive_rate"] or 0.0))
    return {
        "model_version": model_version, "is_mock": is_mock,
        "evaluation_type": "synthetic_detection_sweep_extended",
        "rows": rows, "roc_points": roc_points,
    }


def select_threshold(rows: Sequence[dict], criterion: str = "max_f1") -> dict:
    """Pick a CANDIDATE operating point by an explicit named criterion.

    Criteria: ``max_f1`` (argmax F1, first wins ties), ``youden_j``
    (argmax TPR - FPR). Returns ``{"criterion": ..., "threshold": ...}``.
    """
    if criterion == "max_f1":
        key = lambda row: (row["f1"] is not None, row["f1"] or 0.0, -(row["threshold"]))
    elif criterion == "youden_j":
        key = lambda row: (
            row["true_positive_rate"] is not None
            and row["false_positive_rate"] is not None,
            ((row["true_positive_rate"] or 0.0) - (row["false_positive_rate"] or 0.0)),
            -(row["threshold"]))
    else:
        raise ValidationError(f"Unknown threshold criterion {criterion!r}.")
    usable = [row for row in rows
              if row["f1"] is not None] if criterion == "max_f1" else list(rows)
    if not usable:
        raise ValidationError("No usable sweep rows for threshold selection.")
    best = max(usable, key=key)
    return {"criterion": criterion, "threshold": best["threshold"]}


def evaluate_detection_split(
    samples: Sequence,
    dataset_id: str,
    split: str,
    threshold: float,
    model_version: str = "unknown",
    is_mock: bool = True,
) -> DetectionEvalSummary:
    """Single-threshold detection summary with extended metrics."""
    clean = [coerce_sample(item) for item in samples]
    scores = _require_scores(clean)
    labels = _labels_01(clean)
    base = _base.evaluate_detection(
        [{"score": sample.score, "label": sample.label} for sample in clean],
        threshold, model_version, is_mock)
    tnr = _base._safe_div(base.true_negatives,
                          base.true_negatives + base.false_positives)
    fnr = _base._safe_div(base.false_negatives,
                          base.false_negatives + base.true_positives)
    balanced = None
    if base.true_positive_rate is not None and tnr is not None:
        balanced = (base.true_positive_rate + tnr) / 2.0
    return DetectionEvalSummary(
        dataset_id=dataset_id, split=split, model_version=model_version,
        is_mock=is_mock, sample_count=base.sample_count,
        real_count=base.real_count, synthetic_count=base.synthetic_count,
        threshold=base.threshold, true_positives=base.true_positives,
        true_negatives=base.true_negatives, false_positives=base.false_positives,
        false_negatives=base.false_negatives, accuracy=base.accuracy,
        precision=base.precision, recall=base.recall, specificity=tnr,
        false_positive_rate=base.false_positive_rate,
        false_negative_rate=fnr, true_positive_rate=base.true_positive_rate,
        f1=base.f1, balanced_accuracy=balanced, roc_auc=base.roc_auc,
        average_precision=_average_precision(scores, labels),
        brier_score=brier_score(scores, labels),
        log_loss=log_loss(scores, labels),
        notes=base.notes, generated_at=_utcnow_iso(),
    )


def evaluate_calibration_split(
    samples: Sequence,
    dataset_id: str,
    split: str,
    calibration: PlattCalibration | IsotonicCalibration,
    model_version: str = "unknown",
    is_mock: bool = True,
) -> CalibrationEvalSummary:
    """Assess a dev-fit calibration on one split (usually held-out)."""
    clean = [coerce_sample(item) for item in samples]
    scores = _require_scores(clean)
    labels = _labels_01(clean)
    calibrated = [calibration.apply(score) for score in scores]
    method = calibration.to_dict()
    return CalibrationEvalSummary(
        dataset_id=dataset_id, split=split, model_version=model_version,
        is_mock=is_mock, method=str(method.get("method")),
        parameters={key: value for key, value in method.items()
                    if key not in ("method", "dev_count")},
        dev_count=int(method.get("dev_count", 0)), test_count=len(clean),
        brier_before=brier_score(scores, labels),
        brier_after=brier_score(calibrated, labels),
        log_loss_before=log_loss(scores, labels),
        log_loss_after=log_loss(calibrated, labels),
        reliability=tuple(reliability_summary(calibrated, labels)),
        notes=(), generated_at=_utcnow_iso(),
    )


def run_heldout_detection(
    records: Sequence,
    dataset_id: str,
    model_version: str = "unknown",
    is_mock: bool = True,
    thresholds: Sequence[float] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9),
    candidate_criterion: str = "max_f1",
    calibration: str | None = None,
) -> HeldoutReport:
    """Dev sweep -> candidate -> held-out test metrics (+ calibration).

    ``calibration`` is None, ``"platt"`` or ``"isotonic"`` (fit on dev
    ONLY). Raises on any dev/test leakage. Never writes back into app
    configuration.
    """
    clean = [coerce_sample(item) for item in records]
    _require_uniform_mock(clean, "detection samples")
    dev = [sample for sample in clean if sample.split == "dev"]
    test = [sample for sample in clean if sample.split == "test"]
    if not dev or not test:
        raise ValidationError("Need non-empty dev AND test splits for held-out evaluation.")
    leakage = validate_no_leakage(dev, test)
    sweep = detection_sweep_extended(
        dev, thresholds, model_version, is_mock)
    candidate = select_threshold(sweep["rows"], candidate_criterion)
    dev_summary = evaluate_detection_split(
        dev, dataset_id, "dev", candidate["threshold"], model_version, is_mock)
    test_summary = evaluate_detection_split(
        test, dataset_id, "test", candidate["threshold"], model_version, is_mock)
    calibration_summary = None
    if calibration is not None:
        if calibration == "platt":
            fitted = fit_platt(_require_scores(dev), _labels_01(dev))
        elif calibration == "isotonic":
            fitted = fit_isotonic(_require_scores(dev), _labels_01(dev))
        else:
            raise ValidationError(f"Unknown calibration {calibration!r}.")
        calibration_summary = evaluate_calibration_split(
            test, dataset_id, "test", fitted, model_version, is_mock).to_dict()
    return HeldoutReport(
        dataset_id=dataset_id, kind="synthetic_detection",
        model_version=model_version, is_mock=is_mock, candidate=candidate,
        dev_summary=dev_summary.to_dict(), test_summary=test_summary.to_dict(),
        leakage_report={**leakage,
                        "calibration": calibration_summary},
        generated_at=_utcnow_iso(),
    )


# ------------------------------------------------------------ verification

def evaluate_verification_split(
    trials: Sequence,
    dataset_id: str,
    split: str,
    threshold: float | None,
    model_version: str = "unknown",
    embedder_version: str = "unknown",
    is_mock: bool = True,
    service: SpeakerSimilarityService | None = None,
) -> VerificationEvalSummary:
    """Single-threshold verification summary (vectors scored on demand)."""
    clean = [coerce_trial(item) for item in trials]
    scored = [{
        "similarity": (trial.similarity if trial.similarity is not None
                       else resolve_trial_similarity(trial, service)),
        "same_speaker": trial.same_speaker,
    } for trial in clean]
    base = _base.evaluate_verification(scored, threshold, model_version, is_mock)
    return VerificationEvalSummary(
        dataset_id=dataset_id, split=split, model_version=model_version,
        embedder_version=embedder_version, is_mock=is_mock,
        trial_count=base.trial_count, genuine_count=base.genuine_count,
        impostor_count=base.impostor_count, threshold=base.threshold,
        far=base.far, frr=base.frr, tar=base.tar, trr=base.trr,
        eer=base.eer, eer_threshold=base.eer_threshold,
        notes=base.notes, generated_at=_utcnow_iso(),
    )


def run_heldout_verification(
    records: Sequence,
    dataset_id: str,
    model_version: str = "unknown",
    embedder_version: str = "unknown",
    is_mock: bool = True,
    candidate_criterion: str = "eer",
    service: SpeakerSimilarityService | None = None,
) -> HeldoutReport:
    """Dev EER point -> held-out test metrics, speaker-disjoint enforced."""
    clean = [coerce_trial(item) for item in records]
    _require_uniform_mock(clean, "verification trials")
    dev = [trial for trial in clean if trial.split == "dev"]
    test = [trial for trial in clean if trial.split == "test"]
    if not dev or not test:
        raise ValidationError("Need non-empty dev AND test splits for held-out evaluation.")
    leakage = validate_no_leakage(dev, test, speaker_disjoint=True, id_field="trial_id")
    if candidate_criterion != "eer":
        raise ValidationError(f"Unknown verification criterion {candidate_criterion!r}.")
    dev_summary = evaluate_verification_split(
        dev, dataset_id, "dev", None, model_version, embedder_version,
        is_mock, service)
    if dev_summary.eer_threshold is None:
        raise ValidationError("Cannot select an EER candidate from dev trials.")
    candidate = {"criterion": "eer", "threshold": dev_summary.eer_threshold}
    test_summary = evaluate_verification_split(
        test, dataset_id, "test", candidate["threshold"], model_version,
        embedder_version, is_mock, service)
    return HeldoutReport(
        dataset_id=dataset_id, kind="speaker_verification",
        model_version=model_version, is_mock=is_mock, candidate=candidate,
        dev_summary=dev_summary.to_dict(), test_summary=test_summary.to_dict(),
        leakage_report=leakage, generated_at=_utcnow_iso(),
    )


# ------------------------------------------------------------ subgroups + CI

def evaluate_subgroups(
    records: Sequence,
    by: str,
    dataset_id: str,
    split: str,
    threshold: float,
    model_version: str = "unknown",
    is_mock: bool = True,
    min_n: int = 30,
    service: SpeakerSimilarityService | None = None,
) -> dict:
    """Per-group metrics over a metadata key (``language`` or ``source``).

    Groups below ``min_n`` are reported as skipped with a reason -- never
    as claims. No metadata is ever inferred; empty keys group as "unknown".
    """
    if by not in ("language", "source"):
        raise ValidationError("Subgroups support 'language' or 'source' only.")
    groups: dict[str, list] = {}
    for item in records:
        record = coerce_sample(item) if _looks_like_sample(item) else coerce_trial(item)
        key = getattr(record, by) or "unknown"
        groups.setdefault(key, []).append(record)
    output: dict[str, Any] = {}
    for key in sorted(groups):
        members = groups[key]
        if len(members) < min_n:
            output[key] = {"skipped": True,
                           "reason": f"n={len(members)} below minimum {min_n}.",
                           "count": len(members)}
            continue
        if isinstance(members[0], LabeledSample):
            output[key] = evaluate_detection_split(
                members, dataset_id, f"{split}:{by}={key}", threshold,
                model_version, is_mock).to_dict()
        else:
            output[key] = evaluate_verification_split(
                members, dataset_id, f"{split}:{by}={key}", threshold,
                model_version, "unknown", is_mock, service).to_dict()
    return {"dataset_id": dataset_id, "by": by, "groups": output}


def _looks_like_sample(item: Any) -> bool:
    if isinstance(item, LabeledSample):
        return True
    if isinstance(item, TrialRecord):
        return False
    if isinstance(item, dict):
        return "label" in item
    raise ValidationError("Subgroup records must be samples or trials.")


def bootstrap_ci(
    scores: Sequence[float],
    labels: Sequence[int],
    metric_fn: Callable[[list, list], float | None],
    n_boot: int = 200,
    seed: int = 0,
) -> dict:
    """Seeded bootstrap percentile CI for a metric over (score, label) pairs.

    Deterministic for a given seed. Samples < 10 yield Nones + a reason.
    """
    score_list = list(scores)
    label_list = list(labels)
    if len(score_list) != len(label_list):
        raise ValidationError("scores and labels must have equal length.")
    n = len(score_list)
    if n < 10:
        return {"point": None, "lo": None, "hi": None, "n_boot": n_boot,
                "seed": seed, "n": n,
                "reason": "too few samples for a defensible interval."}
    if n_boot <= 0:
        raise ValidationError("n_boot must be positive.")
    point = metric_fn(score_list, label_list)
    rng = random.Random(seed)
    estimates = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        value = metric_fn([score_list[i] for i in idx],
                          [label_list[i] for i in idx])
        if value is not None and math.isfinite(value):
            estimates.append(value)
    if not estimates:
        return {"point": point, "lo": None, "hi": None, "n_boot": n_boot,
                "seed": seed, "n": n, "reason": "metric undefined on resamples."}
    ordered = sorted(estimates)
    lower = ordered[max(0, math.ceil(0.025 * len(ordered)) - 1)]
    upper = ordered[min(len(ordered) - 1, math.floor(0.975 * len(ordered)))]
    return {"point": point, "lo": lower, "hi": upper, "n_boot": n_boot,
            "seed": seed, "n": n}
