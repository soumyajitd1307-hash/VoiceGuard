# VoiceGuard Evaluation (Part 9)

## 0. Status

**Part 9 evaluation infrastructure is implemented, but production
performance has not been established.**

No representative real dataset and no trained production model weights
are available in this repository. Every number below the fixture line is
a plumbing check on deterministic TEST FIXTURES, never a VoiceGuard
performance claim. This document describes what was evaluated (the
framework), what is required for real validation, and what must never be
quoted as production accuracy/AUC/EER/FAR/FRR.

## 1. What was evaluated

The evaluation *framework* (`backend/eval_dataset.py`,
`backend/eval_runner.py`, `backend/eval_calibration.py` on top of the
existing `backend/evaluation.py` primitives):

- detection confusion metrics + threshold sweeps + ROC/AUC + average precision
- verification FAR/FRR/TAR/TRR + EER + sweeps
- Platt/logistic and isotonic calibration (fit dev-only, assessed held-out)
- dev→test held-out runs with leakage validation
- language/source subgroup reporting with minimum-n guards
- seeded bootstrap confidence intervals
- provenance tracking (model versions, `is_mock`, dataset id, seed, timestamp)

What was NOT evaluated: any trained production model on representative
data. The mock heuristic, the mock embedder, and the Part 8 fixture
weights have no validated discriminative power.

## 2. Dataset requirements

A valid evaluation dataset is a list of explicit records:

- Detection: `sample_id` (unique), `label` (`real`|`synthetic`), `score`
  or in-memory `audio`, optional `speaker_id`, `language`, `source`
  (generator/codec/family, curator-supplied), `split` (`dev`|`test`).
- Verification: `trial_id` (unique), `same_speaker` (bool), `similarity`
  or `reference`+`test` vectors, `speaker_id`, `reference_speaker_id`,
  `language`, `source`, `split`.

Ground truth must be explicit. Labels are never inferred from filenames;
language/accent is never inferred from audio; speakers are never inferred.

Recommended external corpora (not downloaded here, licenses apply):
ASVspoof-style sets for detection; VoxCeleb-style trial lists for
verification.

## 3. Development vs test split

Every record carries an explicit `split` (`dev` for calibration/threshold
selection, `test` for final reporting). `partition_by_split` refuses
records without a split. **A threshold tuned on `dev` is reported on
`test` only** — tuning and reporting on the same samples is rejected by
the leakage validator (duplicate IDs, identical audio bytes).

For verification, dev/test must additionally be **speaker-disjoint**
(`validate_no_leakage(..., speaker_disjoint=True)`); shared `source`
labels are reported as a generalization caveat, not an error.

## 4. Metrics

- Detection: TP/TN/FP/FN, accuracy, precision, recall/TPR, specificity/TNR,
  FPR, FNR, F1, balanced accuracy, ROC-AUC (exact rank-based,
  tie-averaged), average precision, Brier score, log loss. Any metric with
  a zero denominator is `None`, never invented.
- Verification: FAR (false accepts / impostors), FRR (false rejects /
  genuine), TAR = 1−FRR, TRR = 1−FAR, empirical EER (min |FAR−FRR| over
  score/midpoint candidates). Verification means "matches the CLAIMED
  reference", not identification.

## 5. Threshold methodology

Sweeps return the complete table; candidates are selected by an explicit
named criterion (`max_f1`, `youden_j` for detection; `eer` point for
verification) and labelled `candidate`. Candidates are evidence for a
human engineering decision. **They are never written back into
application configuration** — B4's HIGH=70, fusion weights, and risk
bands are pinned by regression test and change only by explicit decision.

## 6. Calibration methodology

Platt scaling (`sigmoid(a·score+b)`, fixed-schedule gradient descent) and
isotonic regression (PAVA) are fit on dev ONLY and assessed on held-out
test via Brier score, log loss and fixed-bin reliability tables. A
calibrated probability is distinct from both the raw model score and the
B4 risk score.

## 7. Speaker verification methodology

Trials carry explicit `same_speaker` ground truth; similarities come from
precomputed scores or vectors scored on demand through
`SpeakerSimilarityService` (cosine math lives in exactly one place).
Reference/test separation and speaker-disjoint splits are enforced; EER
requires ≥1 genuine AND ≥1 impostor trial.

## 8. Leakage prevention

`validate_no_leakage` fails loudly (never silently dedups) on: duplicate
IDs across dev/test, identical in-memory audio on both sides, and (when
requested) shared speakers. Source overlap is reported as a caveat:
performance against one generator family does not transfer to unseen
generators — do not extrapolate.

## 9. Limitations

- No representative data and no trained weights exist here: **no
  production accuracy, AUC, EER, FAR/FRR, threshold, or confidence has
  been measured.**
- Mock/fixture numbers exercise plumbing only and must never be mixed
  with real runs (`_check_mock_consistency` refuses aggregation).
- Subgroups below `min_n` (default 30) are skipped, not claimed.
- Bootstrap CIs need n≥10 and a recorded seed; they describe the
  observed sample, not deployment.
- Calibration on tiny or single-class dev data is rejected, not fudged.

## 10. What counts as production validation

ALL of: (a) trained production weights with recorded versions; (b) a
representative, licensed dataset with explicit ground truth, disjoint
dev/test splits and speaker-disjoint verification trials; (c) held-out
metrics run through this framework with recorded seeds; (d) a human
engineering decision adopting a candidate threshold/weights change, with
the decision and its evidence recorded. Until then, every result stays
labelled development/mock/fixture.
