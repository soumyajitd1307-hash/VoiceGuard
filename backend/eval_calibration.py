"""Part 9: probability calibration (stdlib only, deterministic).

Two documented methods, both fit on development data ONLY and evaluated
on held-out data by the runner:

* Platt/logistic scaling: ``p_cal = sigmoid(a * score + b)`` with ``(a,
  b)`` fit by fixed-iteration batch gradient descent on the logistic
  loss (fixed learning rate and iteration count -> deterministic; no
  randomness, no scipy dependency).
* Isotonic regression (PAVA): the stepwise non-decreasing fit minimizing
  squared error on the development set. Deterministic by construction.

Also provided: Brier score, log loss (epsilon-clipped), and reliability
summaries (fixed bins of mean predicted probability vs empirical rate).
A calibrated probability is NOT a B4 risk score -- score, calibrated
probability and risk remain three distinct concepts.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Sequence

from backend.schemas import ValidationError

log = logging.getLogger(__name__)

_EPS = 1e-12


def _check_pairs(scores: Sequence, labels: Sequence,
                 require_both_classes: bool = True) -> tuple[list, list]:
    try:
        score_list = list(scores)
        label_list = list(labels)
    except TypeError:
        raise ValidationError("scores and labels must be sequences.") from None
    if len(score_list) != len(label_list):
        raise ValidationError("scores and labels must have equal length.")
    if len(score_list) == 0:
        raise ValidationError("Need at least one sample to calibrate.")
    clean_scores = []
    clean_labels = []
    for score, label in zip(score_list, label_list):
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValidationError("scores must be numbers.")
        if not math.isfinite(float(score)):
            raise ValidationError("scores must be finite.")
        if label not in (0, 1, True, False):
            raise ValidationError("labels must be 0/1 booleans or ints.")
        clean_scores.append(float(score))
        clean_labels.append(1 if label else 0)
    if require_both_classes and (all(label == 0 for label in clean_labels)
                                 or all(label == 1 for label in clean_labels)):
        raise ValidationError("Calibration needs both classes in development data.")
    return clean_scores, clean_labels


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    shifted = math.exp(value)
    return shifted / (1.0 + shifted)


@dataclass(frozen=True)
class PlattCalibration:
    """Logistic scaling ``sigmoid(a * score + b)`` fit on dev data."""

    slope: float
    intercept: float
    dev_count: int

    def apply(self, score: float) -> float:
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValidationError("score must be a number.")
        if not math.isfinite(float(score)):
            raise ValidationError("score must be finite.")
        return _sigmoid(self.slope * float(score) + self.intercept)

    def to_dict(self) -> dict:
        return {"method": "platt", "slope": self.slope,
                "intercept": self.intercept, "dev_count": self.dev_count}


def fit_platt(scores: Sequence, labels: Sequence,
              iterations: int = 500, learning_rate: float = 0.5) -> PlattCalibration:
    """Fit Platt scaling by batch gradient descent (fixed schedule ->
    deterministic). Returns the fitted ``PlattCalibration``."""
    clean_scores, clean_labels = _check_pairs(scores, labels)
    if iterations <= 0 or learning_rate <= 0:
        raise ValidationError("iterations and learning_rate must be positive.")
    slope, intercept = 0.0, 0.0
    n = len(clean_scores)
    for _ in range(iterations):
        grad_slope = 0.0
        grad_intercept = 0.0
        for score, label in zip(clean_scores, clean_labels):
            predicted = _sigmoid(slope * score + intercept)
            error = predicted - label
            grad_slope += error * score
            grad_intercept += error
        slope -= learning_rate * grad_slope / n
        intercept -= learning_rate * grad_intercept / n
    fitted = PlattCalibration(slope=slope, intercept=intercept, dev_count=n)
    log.info("platt fit: slope=%.4f intercept=%.4f n=%d", slope, intercept, n)
    return fitted


@dataclass(frozen=True)
class IsotonicCalibration:
    """PAVA stepwise fit: sorted unique ``knots`` with fitted ``values``."""

    knots: tuple
    values: tuple
    dev_count: int

    def apply(self, score: float) -> float:
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValidationError("score must be a number.")
        if not math.isfinite(float(score)):
            raise ValidationError("score must be finite.")
        score = float(score)
        # Right-continuous step function over the dev knots.
        chosen = self.values[0]
        for knot, value in zip(self.knots, self.values):
            if score >= knot:
                chosen = value
            else:
                break
        return chosen

    def to_dict(self) -> dict:
        return {"method": "isotonic", "knots": list(self.knots),
                "values": list(self.values), "dev_count": self.dev_count}


def fit_isotonic(scores: Sequence, labels: Sequence) -> IsotonicCalibration:
    """Fit isotonic regression by pool-adjacent-violators (PAVA)."""
    clean_scores, clean_labels = _check_pairs(scores, labels)
    order = sorted(range(len(clean_scores)), key=lambda i: clean_scores[i])
    sorted_scores = [clean_scores[i] for i in order]
    sorted_labels = [float(clean_labels[i]) for i in order]
    # Blocks of (start_index, end_index_exclusive, fitted_value).
    blocks: list[list] = [[i, i + 1, sorted_labels[i]] for i in range(len(sorted_scores))]
    changed = True
    while changed:
        changed = False
        merged: list[list] = []
        for block in blocks:
            if merged and merged[-1][2] > block[2] + 1e-12:
                prev = merged.pop()
                start, _, _ = prev
                _, end, _ = block
                values = sorted_labels[start:end]
                merged.append([start, end, sum(values) / len(values)])
                changed = True
            else:
                merged.append(block)
        blocks = merged
    knots = tuple(sorted_scores[block[0]] for block in blocks)
    values = tuple(block[2] for block in blocks)
    return IsotonicCalibration(knots=knots, values=values, dev_count=len(clean_scores))


def brier_score(probabilities: Sequence, labels: Sequence) -> float:
    """Mean squared error between probabilities and 0/1 labels."""
    clean_scores, clean_labels = _check_pairs(
        probabilities, labels, require_both_classes=False)
    return sum((p - y) ** 2 for p, y in zip(clean_scores, clean_labels)) / len(clean_scores)


def log_loss(probabilities: Sequence, labels: Sequence) -> float:
    """Binary log loss with epsilon clipping (never log(0))."""
    clean_scores, clean_labels = _check_pairs(
        probabilities, labels, require_both_classes=False)
    total = 0.0
    for probability, label in zip(clean_scores, clean_labels):
        clipped = min(max(probability, _EPS), 1.0 - _EPS)
        total += -(label * math.log(clipped) + (1 - label) * math.log(1 - clipped))
    return total / len(clean_scores)


def reliability_summary(probabilities: Sequence, labels: Sequence,
                        bins: int = 5) -> list[dict]:
    """Fixed-bin reliability table: mean predicted vs empirical rate + count."""
    if not isinstance(bins, int) or isinstance(bins, bool) or bins <= 0:
        raise ValidationError("bins must be a positive integer.")
    clean_scores, clean_labels = _check_pairs(
        probabilities, labels, require_both_classes=False)
    table = []
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        bucket = [(p, y) for p, y in zip(clean_scores, clean_labels)
                  if (low <= p < high) or (index == bins - 1 and p == high)]
        if not bucket:
            table.append({"bin_low": low, "bin_high": high,
                          "mean_predicted": None, "empirical_rate": None, "count": 0})
        else:
            table.append({
                "bin_low": low, "bin_high": high,
                "mean_predicted": sum(p for p, _ in bucket) / len(bucket),
                "empirical_rate": sum(y for _, y in bucket) / len(bucket),
                "count": len(bucket),
            })
    return table
