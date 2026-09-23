"""Tests for Backend 3 Part 4: model evaluation.

Stdlib unittest only (no pytest dependency).

Fixtures below are deterministic TEST FIXTURES for exercising the metrics
plumbing with hand-checkable numbers. They are NOT real-model benchmarks
and must never be quoted as model performance.
"""
from __future__ import annotations

import json
import unittest

from backend.evaluation import (
    DetectionSample,
    VerificationTrial,
    detection_threshold_sweep,
    evaluate_detection,
    evaluate_verification,
    trial_from_embeddings,
    verification_threshold_sweep,
)
from backend.schemas import ValidationError

# TEST FIXTURE (not a benchmark): perfectly separable detection scores.
PERFECT_REAL = [0.1, 0.2, 0.3]
PERFECT_SYNTH = [0.8, 0.9, 0.95]

# TEST FIXTURE: overlapping scores; thr 0.5 -> tp=tn=fp=fn=1.
MIXED_REAL = [0.1, 0.6]
MIXED_SYNTH = [0.4, 0.9]

# TEST FIXTURE: separable verification trials.
GENUINE = [0.9, 0.8, 0.7]
IMPOSTOR = [0.2, 0.3, 0.1]

# TEST FIXTURE: overlapping trials; thr 0.5 -> FAR=FRR=0.5, EER=0.5 @ 0.5.
OVERLAP_GENUINE = [0.6, 0.4]
OVERLAP_IMPOSTOR = [0.5, 0.3]


def _detection_samples(real, synth):
    return [DetectionSample(score=s, label="real") for s in real] + [
        DetectionSample(score=s, label="synthetic") for s in synth
    ]


def _trials(genuine, impostor):
    return [VerificationTrial(similarity=s, same_speaker=True) for s in genuine] + [
        VerificationTrial(similarity=s, same_speaker=False) for s in impostor
    ]


class TestDetectionEvaluation(unittest.TestCase):
    def test_basic_confusion_matrix(self):
        result = evaluate_detection(_detection_samples(MIXED_REAL, MIXED_SYNTH), 0.5)
        self.assertEqual(
            (result.true_positives, result.true_negatives,
             result.false_positives, result.false_negatives),
            (1, 1, 1, 1),
        )
        self.assertEqual((result.sample_count, result.real_count, result.synthetic_count), (4, 2, 2))

    def test_accuracy(self):
        perfect = evaluate_detection(_detection_samples(PERFECT_REAL, PERFECT_SYNTH), 0.5)
        self.assertAlmostEqual(perfect.accuracy, 1.0)
        mixed = evaluate_detection(_detection_samples(MIXED_REAL, MIXED_SYNTH), 0.5)
        self.assertAlmostEqual(mixed.accuracy, 0.5)

    def test_precision(self):
        mixed = evaluate_detection(_detection_samples(MIXED_REAL, MIXED_SYNTH), 0.5)
        self.assertAlmostEqual(mixed.precision, 0.5)  # 1/(1+1)

    def test_recall(self):
        mixed = evaluate_detection(_detection_samples(MIXED_REAL, MIXED_SYNTH), 0.5)
        self.assertAlmostEqual(mixed.recall, 0.5)  # 1/(1+1)

    def test_f1(self):
        mixed = evaluate_detection(_detection_samples(MIXED_REAL, MIXED_SYNTH), 0.5)
        self.assertAlmostEqual(mixed.f1, 0.5)
        perfect = evaluate_detection(_detection_samples(PERFECT_REAL, PERFECT_SYNTH), 0.5)
        self.assertAlmostEqual(perfect.f1, 1.0)

    def test_fpr(self):
        mixed = evaluate_detection(_detection_samples(MIXED_REAL, MIXED_SYNTH), 0.5)
        self.assertAlmostEqual(mixed.false_positive_rate, 0.5)  # 1/(1+1)

    def test_tpr(self):
        mixed = evaluate_detection(_detection_samples(MIXED_REAL, MIXED_SYNTH), 0.5)
        self.assertAlmostEqual(mixed.true_positive_rate, 0.5)

    def test_threshold_sweep(self):
        sweep = detection_threshold_sweep(
            _detection_samples(MIXED_REAL, MIXED_SYNTH), [0.3, 0.5, 0.9]
        )
        self.assertEqual(len(sweep["rows"]), 3)
        by_thr = {row["threshold"]: row for row in sweep["rows"]}
        # thr 0.3: 0.1->TN, 0.6->FP, both synth ->TP: tp=2, fp=1, recall=1.
        self.assertEqual((by_thr[0.3]["true_positives"], by_thr[0.3]["false_positives"]), (2, 1))
        self.assertAlmostEqual(by_thr[0.3]["recall"], 1.0)
        # thr 0.9: only 0.9 predicted synthetic -> tp=1, fp=0, fn=1, precision=1
        self.assertEqual((by_thr[0.9]["true_positives"], by_thr[0.9]["false_positives"]), (1, 0))
        self.assertAlmostEqual(by_thr[0.9]["precision"], 1.0)
        # F1: thr0.3 -> 0.8, thr0.5 -> 0.5, thr0.9 -> 2/3; max wins.
        self.assertAlmostEqual(by_thr[0.3]["f1"], 0.8)
        self.assertEqual(sweep["max_f1_threshold"], 0.3)

    def test_roc_auc_perfect(self):
        result = evaluate_detection(_detection_samples(PERFECT_REAL, PERFECT_SYNTH), 0.5)
        self.assertAlmostEqual(result.roc_auc, 1.0)

    def test_roc_auc_partial(self):
        # Ranks: 0.1(R) 0.4(S) 0.6(R) 0.9(S) -> pos ranks 2+4=6 -> (6-3)/4 = 0.75.
        result = evaluate_detection(_detection_samples(MIXED_REAL, MIXED_SYNTH), 0.5)
        self.assertAlmostEqual(result.roc_auc, 0.75)

    def test_one_class_dataset(self):
        only_real = evaluate_detection(
            [DetectionSample(score=0.1, label="real"), DetectionSample(score=0.6, label="real")],
            0.5,
        )
        self.assertAlmostEqual(only_real.accuracy, 0.5)
        self.assertIsNone(only_real.recall)  # no positives: 0/0
        self.assertAlmostEqual(only_real.precision, 0.0)  # 0/(0+1): defined, zero
        self.assertIsNone(only_real.roc_auc)
        self.assertTrue(any("single-class" in note for note in only_real.notes))

    def test_empty_dataset(self):
        result = evaluate_detection([], 0.5)
        self.assertEqual(result.sample_count, 0)
        self.assertIsNone(result.accuracy)
        self.assertIsNone(result.roc_auc)
        self.assertTrue(any("empty" in note for note in result.notes))

    def test_invalid_score(self):
        for bad in (1.5, -0.1, float("nan"), float("inf"), "high"):
            with self.assertRaises(ValidationError, msg=f"score={bad!r}"):
                evaluate_detection([DetectionSample(score=bad, label="real")], 0.5)
        with self.assertRaises(ValidationError):
            evaluate_detection(_detection_samples(MIXED_REAL, MIXED_SYNTH), 1.5)

    def test_invalid_label(self):
        with self.assertRaises(ValidationError):
            evaluate_detection([{"score": 0.5, "label": "maybe"}], 0.5)
        with self.assertRaises(ValidationError):
            evaluate_detection([{"score": 0.5}], 0.5)

    def test_mock_provenance(self):
        result = evaluate_detection(
            _detection_samples(PERFECT_REAL, PERFECT_SYNTH), 0.5,
            model_version="mock-heuristic-v0.1.0", is_mock=True,
        )
        payload = result.to_dict()
        self.assertTrue(payload["is_mock"])
        self.assertEqual(payload["model_version"], "mock-heuristic-v0.1.0")
        self.assertEqual(payload["evaluation_type"], "synthetic_detection")

    def test_threshold_boundary_is_positive(self):
        result = evaluate_detection([DetectionSample(score=0.5, label="synthetic")], 0.5)
        self.assertEqual(result.true_positives, 1)


class TestVerificationEvaluation(unittest.TestCase):
    def test_genuine_impostor_separation(self):
        result = evaluate_verification(_trials(GENUINE, IMPOSTOR), 0.5)
        self.assertEqual((result.trial_count, result.genuine_count, result.impostor_count), (6, 3, 3))

    def test_far(self):
        result = evaluate_verification(_trials(GENUINE, IMPOSTOR), 0.5)
        self.assertAlmostEqual(result.far, 0.0)
        overlap = evaluate_verification(_trials(OVERLAP_GENUINE, OVERLAP_IMPOSTOR), 0.5)
        self.assertAlmostEqual(overlap.far, 0.5)  # 0.5 accepted, 0.3 rejected

    def test_frr(self):
        result = evaluate_verification(_trials(GENUINE, IMPOSTOR), 0.5)
        self.assertAlmostEqual(result.frr, 0.0)
        overlap = evaluate_verification(_trials(OVERLAP_GENUINE, OVERLAP_IMPOSTOR), 0.5)
        self.assertAlmostEqual(overlap.frr, 0.5)  # 0.6 accepted, 0.4 rejected

    def test_tar(self):
        overlap = evaluate_verification(_trials(OVERLAP_GENUINE, OVERLAP_IMPOSTOR), 0.5)
        self.assertAlmostEqual(overlap.tar, 0.5)  # 1 - FRR

    def test_trr(self):
        overlap = evaluate_verification(_trials(OVERLAP_GENUINE, OVERLAP_IMPOSTOR), 0.5)
        self.assertAlmostEqual(overlap.trr, 0.5)  # 1 - FAR

    def test_threshold_sweep(self):
        sweep = verification_threshold_sweep(_trials(OVERLAP_GENUINE, OVERLAP_IMPOSTOR), [0.35, 0.5, 0.65])
        self.assertEqual(len(sweep["rows"]), 3)
        by_thr = {row["threshold"]: row for row in sweep["rows"]}
        self.assertAlmostEqual(by_thr[0.35]["far"], 0.5)  # 0.5 acc, 0.3 rej
        self.assertAlmostEqual(by_thr[0.35]["frr"], 0.0)  # both genuine accepted
        self.assertAlmostEqual(by_thr[0.65]["far"], 0.0)
        self.assertAlmostEqual(by_thr[0.65]["frr"], 1.0)
        self.assertEqual((sweep["genuine_count"], sweep["impostor_count"]), (2, 2))

    def test_eer_separable(self):
        result = evaluate_verification(_trials(GENUINE, IMPOSTOR), 0.5)
        self.assertAlmostEqual(result.eer, 0.0)
        self.assertIsNotNone(result.eer_threshold)

    def test_eer_overlap(self):
        # At thr 0.5: FAR=FRR=0.5 -> EER 0.5 is the minimum-gap point.
        result = evaluate_verification(_trials(OVERLAP_GENUINE, OVERLAP_IMPOSTOR), 0.5)
        self.assertAlmostEqual(result.eer, 0.5)
        self.assertAlmostEqual(result.eer_threshold, 0.5)

    def test_missing_genuine_trials(self):
        result = evaluate_verification(_trials([], IMPOSTOR), 0.5)
        self.assertAlmostEqual(result.far, 0.0)
        self.assertIsNone(result.frr)
        self.assertIsNone(result.tar)
        self.assertIsNone(result.eer)
        self.assertTrue(any("EER" in note for note in result.notes))

    def test_missing_impostor_trials(self):
        result = evaluate_verification(_trials(GENUINE, []), 0.5)
        self.assertAlmostEqual(result.frr, 0.0)
        self.assertIsNone(result.far)
        self.assertIsNone(result.trr)
        self.assertIsNone(result.eer)

    def test_no_threshold_gives_no_rates(self):
        result = evaluate_verification(_trials(GENUINE, IMPOSTOR))
        self.assertIsNone(result.threshold)
        self.assertIsNone(result.far)
        self.assertIsNone(result.frr)
        # EER is threshold-independent and still computed.
        self.assertAlmostEqual(result.eer, 0.0)

    def test_invalid_similarity(self):
        for bad in (2.0, -1.5, float("nan"), float("inf"), "high"):
            with self.assertRaises(ValidationError, msg=f"sim={bad!r}"):
                evaluate_verification([VerificationTrial(similarity=bad, same_speaker=True)], 0.5)
        with self.assertRaises(ValidationError):
            evaluate_verification(_trials(GENUINE, IMPOSTOR), 2.0)
        with self.assertRaises(ValidationError):
            evaluate_verification([{"similarity": 0.5, "same_speaker": "yes"}], 0.5)

    def test_mock_provenance(self):
        result = evaluate_verification(
            _trials(GENUINE, IMPOSTOR), 0.5,
            model_version="mock-spectral-v0.1.0", is_mock=True,
        )
        payload = result.to_dict()
        self.assertTrue(payload["is_mock"])
        self.assertEqual(payload["model_version"], "mock-spectral-v0.1.0")
        self.assertEqual(payload["evaluation_type"], "speaker_verification")

    def test_trial_from_embeddings_reuses_service(self):
        trial = trial_from_embeddings([1.0, 0.0], [1.0, 0.0], True)
        self.assertIsInstance(trial, VerificationTrial)
        self.assertAlmostEqual(trial.similarity, 1.0, places=6)
        self.assertTrue(trial.same_speaker)
        with self.assertRaises(ValidationError):
            trial_from_embeddings([1.0], [1.0], "yes")  # type: ignore[arg-type]


class TestEvaluationConventions(unittest.TestCase):
    def test_deterministic_results(self):
        first = evaluate_detection(_detection_samples(MIXED_REAL, MIXED_SYNTH), 0.5)
        second = evaluate_detection(_detection_samples(MIXED_REAL, MIXED_SYNTH), 0.5)
        self.assertEqual(first.to_dict(), second.to_dict())
        first_v = evaluate_verification(_trials(OVERLAP_GENUINE, OVERLAP_IMPOSTOR), 0.5)
        second_v = evaluate_verification(_trials(OVERLAP_GENUINE, OVERLAP_IMPOSTOR), 0.5)
        self.assertEqual(first_v.to_dict(), second_v.to_dict())

    def test_schema_serialization(self):
        detection = evaluate_detection(_detection_samples(PERFECT_REAL, PERFECT_SYNTH), 0.5)
        verification = evaluate_verification(_trials(GENUINE, IMPOSTOR), 0.5)
        for payload in (detection.to_dict(), verification.to_dict()):
            json.dumps(payload)  # must be JSON-safe
        sweep = detection_threshold_sweep(_detection_samples(MIXED_REAL, MIXED_SYNTH), [0.5])
        json.dumps(sweep)

    def test_no_division_by_zero(self):
        # All-zero denominators across every metric path.
        empty_d = evaluate_detection([], 0.5)
        for field in ("accuracy", "precision", "recall", "f1",
                      "false_positive_rate", "true_positive_rate", "roc_auc"):
            self.assertIsNone(getattr(empty_d, field))
        empty_v = evaluate_verification([], 0.5)
        for field in ("far", "frr", "tar", "trr", "eer"):
            self.assertIsNone(getattr(empty_v, field))

    def test_model_version_preservation(self):
        detection = evaluate_detection(
            _detection_samples(PERFECT_REAL, PERFECT_SYNTH), 0.5, model_version="cm-v9"
        )
        self.assertEqual(detection.model_version, "cm-v9")
        verification = evaluate_verification(_trials(GENUINE, IMPOSTOR), 0.5, model_version="enc-v3")
        self.assertEqual(verification.model_version, "enc-v3")
        sweep = detection_threshold_sweep(
            _detection_samples(PERFECT_REAL, PERFECT_SYNTH), [0.5], model_version="cm-v9"
        )
        self.assertEqual(sweep["model_version"], "cm-v9")

    def test_dict_inputs_accepted(self):
        result = evaluate_detection(
            [{"score": 0.9, "label": "synthetic"}, {"score": 0.1, "label": "real"}], 0.5
        )
        self.assertAlmostEqual(result.accuracy, 1.0)
        trial_result = evaluate_verification(
            [{"similarity": 0.9, "same_speaker": True},
             {"similarity": 0.1, "same_speaker": False}],
            0.5,
        )
        self.assertAlmostEqual(trial_result.far, 0.0)

    def test_all_scores_equal(self):
        samples = [DetectionSample(score=0.5, label="real"), DetectionSample(score=0.5, label="synthetic")]
        result = evaluate_detection(samples, 0.5)
        self.assertEqual((result.true_positives, result.false_positives), (1, 1))
        self.assertAlmostEqual(result.roc_auc, 0.5)  # tie-averaged ranks


if __name__ == "__main__":
    unittest.main()
