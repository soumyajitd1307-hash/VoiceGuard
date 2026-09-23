"""Tests for Part 9: evaluation framework (dataset, runner, calibration).

Stdlib unittest only. All fixtures are deterministic TEST FIXTURES for
exercising framework math -- hand-checkable numbers below assert the
plumbing, never model quality. No number here is a VoiceGuard
performance claim.
"""
from __future__ import annotations

import json
import math
import unittest

from backend import evaluation as base_eval
from backend.eval_calibration import (
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
    partition_by_split,
    resolve_trial_similarity,
    validate_no_leakage,
)
from backend.eval_runner import (
    bootstrap_ci,
    detection_sweep_extended,
    evaluate_calibration_split,
    evaluate_detection_split,
    evaluate_subgroups,
    evaluate_verification_split,
    run_heldout_detection,
    run_heldout_verification,
    select_threshold,
)
from backend.schemas import ValidationError

# TEST FIXTURES (plumbing only): perfectly separable detection scores.
PERFECT = ([0.1, 0.2, 0.3], [0.7, 0.8, 0.9])
# TEST FIXTURE: overlapping; thr 0.5 -> tp=tn=fp=fp... tp=1,tn=1,fp=1,fn=1.
MIXED = ([0.1, 0.6], [0.4, 0.9])
# TEST FIXTURES: verification trials.
GENUINE = [0.9, 0.8, 0.7]
IMPOSTOR = [0.2, 0.3, 0.1]


def _samples(real, synth, split="dev", **kwargs):
    # IDs embed the split: dev/test fixtures must never share sample IDs,
    # or the leakage validator (correctly) rejects the run.
    return ([LabeledSample(sample_id=f"{split}-r{i}", label="real", score=score,
                           split=split, **kwargs)
             for i, score in enumerate(real)] +
            [LabeledSample(sample_id=f"{split}-s{i}", label="synthetic", score=score,
                           split=split, **kwargs)
             for i, score in enumerate(synth)])


def _trials(genuine, impostor, split="dev", **kwargs):
    return ([TrialRecord(trial_id=f"{split}-g{i}", same_speaker=True, similarity=score,
                         split=split, **kwargs) for i, score in enumerate(genuine)] +
            [TrialRecord(trial_id=f"{split}-i{i}", same_speaker=False, similarity=score,
                         split=split, **kwargs) for i, score in enumerate(impostor)])


class TestDatasetRecords(unittest.TestCase):
    def test_valid_records(self):
        sample = coerce_sample({"sample_id": "a", "label": "synthetic", "score": 0.9})
        self.assertEqual(sample.label, "synthetic")
        trial = coerce_trial({"trial_id": "t", "same_speaker": True, "similarity": 0.5})
        self.assertTrue(trial.same_speaker)

    def test_invalid_labels(self):
        with self.assertRaises(ValidationError):
            coerce_sample({"sample_id": "a", "label": "maybe"})
        with self.assertRaises(ValidationError):
            coerce_sample({"sample_id": "a"})  # missing label
        with self.assertRaises(ValidationError):
            coerce_trial({"trial_id": "t", "same_speaker": "yes"})

    def test_duplicate_ids_rejected(self):
        dev = _samples([0.1], [0.9])
        test = [LabeledSample(sample_id="dev-r0", label="real", score=0.2, split="test")]
        with self.assertRaises(ValidationError) as ctx:
            validate_no_leakage(dev, test)
        self.assertIn("dev-r0", str(ctx.exception))

    def test_split_validation(self):
        with self.assertRaises(ValidationError):
            partition_by_split(_samples([0.1], [0.9]))  # split "" everywhere
        with self.assertRaises(ValidationError):
            partition_by_split([])

    def test_speaker_leakage(self):
        dev = [LabeledSample(sample_id="a", label="real", score=0.1,
                             speaker_id="spk1", split="dev")]
        test = [LabeledSample(sample_id="b", label="real", score=0.2,
                              speaker_id="spk1", split="test")]
        with self.assertRaises(ValidationError):
            validate_no_leakage(dev, test, speaker_disjoint=True)
        # Without the flag, shared speakers are allowed.
        report = validate_no_leakage(dev, test)
        self.assertEqual(report["speaker_overlap"], [])

    def test_malformed_metadata(self):
        with self.assertRaises(ValidationError):
            coerce_sample({"sample_id": "a", "label": "real", "score": float("nan")})
        with self.assertRaises(ValidationError):
            coerce_trial({"trial_id": "t", "same_speaker": True})  # no score/vectors
        with self.assertRaises(ValidationError):
            coerce_sample({"sample_id": "a", "label": "real",
                           "audio": "/tmp/evil.wav"})  # paths rejected

    def test_audio_overlap_rejected(self):
        audio = (0.1, 0.2, 0.3)
        dev = [LabeledSample(sample_id="a", label="real", score=0.1,
                             audio=audio, split="dev")]
        test = [LabeledSample(sample_id="b", label="real", score=0.2,
                              audio=audio, split="test")]
        with self.assertRaises(ValidationError):
            validate_no_leakage(dev, test)

    def test_source_overlap_reported_not_failed(self):
        dev = [LabeledSample(sample_id="a", label="real", score=0.1,
                             source="tts-x", split="dev")]
        test = [LabeledSample(sample_id="b", label="real", score=0.2,
                              source="tts-x", split="test")]
        report = validate_no_leakage(dev, test)
        self.assertEqual(report["source_overlap"], ["tts-x"])

    def test_vector_trials_scored_on_demand(self):
        trial = coerce_trial({"trial_id": "t", "same_speaker": True,
                              "reference": [1.0, 0.0], "test": [1.0, 0.0]})
        self.assertAlmostEqual(resolve_trial_similarity(trial), 1.0, places=6)


class TestExtendedDetection(unittest.TestCase):
    def test_split_summary_perfect(self):
        summary = evaluate_detection_split(
            _samples(*PERFECT), "fx", "dev", 0.5, "m-v1", True)
        self.assertEqual((summary.true_positives, summary.true_negatives,
                          summary.false_positives, summary.false_negatives),
                         (3, 3, 0, 0))
        self.assertAlmostEqual(summary.accuracy, 1.0)
        self.assertAlmostEqual(summary.specificity, 1.0)
        self.assertAlmostEqual(summary.false_negative_rate, 0.0)
        self.assertAlmostEqual(summary.balanced_accuracy, 1.0)
        self.assertAlmostEqual(summary.roc_auc, 1.0)
        self.assertAlmostEqual(summary.average_precision, 1.0)
        # Brier: (0.01+0.04+0.09 + 0.09+0.04+0.01)/6 = 0.28/6.
        self.assertAlmostEqual(summary.brier_score, 0.28 / 6.0)
        self.assertTrue(summary.log_loss > 0.0)
        self.assertEqual(summary.dataset_id, "fx")
        self.assertEqual(summary.split, "dev")
        self.assertTrue(summary.is_mock)
        self.assertTrue(summary.generated_at)
        json.dumps(summary.to_dict())

    def test_split_summary_mixed(self):
        summary = evaluate_detection_split(
            _samples(*MIXED), "fx", "dev", 0.5, "m", True)
        self.assertAlmostEqual(summary.specificity, 0.5)  # tn/(tn+fp)
        self.assertAlmostEqual(summary.false_negative_rate, 0.5)
        self.assertAlmostEqual(summary.balanced_accuracy, 0.5)
        self.assertAlmostEqual(summary.roc_auc, 0.75)
        # AP: order 0.9(S),0.6(R),0.4(S),0.1(R): .5*1 + .5*(2/3).
        self.assertAlmostEqual(summary.average_precision, 0.5 + 0.5 * (2 / 3))

    def test_sweep_extended_fields(self):
        sweep = detection_sweep_extended(_samples(*MIXED), [0.5], "m", True)
        row = sweep["rows"][0]
        self.assertAlmostEqual(row["specificity"], 0.5)
        self.assertAlmostEqual(row["false_negative_rate"], 0.5)
        self.assertAlmostEqual(row["balanced_accuracy"], 0.5)
        self.assertTrue(len(sweep["roc_points"]) >= 1)
        point = sweep["roc_points"][0]
        self.assertIn("false_positive_rate", point)

    def test_threshold_candidates(self):
        sweep = detection_sweep_extended(_samples(*MIXED), [0.3, 0.5, 0.9], "m", True)
        f1 = select_threshold(sweep["rows"], "max_f1")
        self.assertEqual(f1, {"criterion": "max_f1", "threshold": 0.3})
        youden = select_threshold(sweep["rows"], "youden_j")
        self.assertEqual(youden["criterion"], "youden_j")
        self.assertIn(youden["threshold"], (0.3, 0.5, 0.9))
        with self.assertRaises(ValidationError):
            select_threshold(sweep["rows"], "vibes")

    def test_single_class_edge(self):
        summary = evaluate_detection_split(
            _samples([0.1, 0.2], []), "fx", "dev", 0.5, "m", True)
        self.assertIsNone(summary.recall)
        self.assertIsNone(summary.roc_auc)
        self.assertIsNone(summary.average_precision)

    def test_missing_scores_rejected(self):
        samples = [LabeledSample(sample_id="a", label="real", split="dev")]
        with self.assertRaises(ValidationError):
            evaluate_detection_split(samples, "fx", "dev", 0.5)


class TestHeldoutDetection(unittest.TestCase):
    def _heldout_records(self):
        dev = _samples([0.1, 0.2, 0.35], [0.65, 0.8, 0.9], split="dev")
        test = _samples([0.15, 0.4], [0.6, 0.95], split="test")
        return dev + test

    def test_dev_candidate_applied_to_test(self):
        report = run_heldout_detection(
            self._heldout_records(), "fx", "m-v1", True,
            thresholds=[0.3, 0.5, 0.7], candidate_criterion="max_f1")
        self.assertEqual(report.kind, "synthetic_detection")
        self.assertIn(report.candidate["threshold"], (0.3, 0.5, 0.7))
        self.assertEqual(report.test_summary["split"], "test")
        self.assertEqual(report.dev_summary["split"], "dev")
        self.assertEqual(report.test_summary["sample_count"], 4)
        json.dumps(report.to_dict())

    def test_leakage_blocks_heldout(self):
        records = self._heldout_records()
        poisoned = records + [LabeledSample(
            sample_id="dev-r0", label="real", score=0.1, split="test")]
        with self.assertRaises(ValidationError):
            run_heldout_detection(poisoned, "fx", "m", True)

    def test_mock_mixing_refused(self):
        records = [LabeledSample(sample_id="a", label="real", score=0.1,
                                 split="dev", is_mock=True),
                   LabeledSample(sample_id="b", label="synthetic", score=0.9,
                                 split="dev", is_mock=False),
                   LabeledSample(sample_id="c", label="real", score=0.2,
                                 split="test", is_mock=True)]
        with self.assertRaises(ValidationError):
            run_heldout_detection(records, "fx", "m", True)

    def test_heldout_with_platt(self):
        report = run_heldout_detection(
            self._heldout_records(), "fx", "m", True,
            thresholds=[0.5], calibration="platt")
        calibration = report.leakage_report["calibration"]
        self.assertEqual(calibration["method"], "platt")
        self.assertTrue(calibration["test_count"] >= 1)
        self.assertTrue(math.isfinite(calibration["brier_after"]))

    def test_heldout_with_isotonic(self):
        report = run_heldout_detection(
            self._heldout_records(), "fx", "m", True,
            thresholds=[0.5], calibration="isotonic")
        calibration = report.leakage_report["calibration"]
        self.assertEqual(calibration["method"], "isotonic")

    def test_unknown_calibration_rejected(self):
        with self.assertRaises(ValidationError):
            run_heldout_detection(self._heldout_records(), "fx", "m", True,
                                  thresholds=[0.5], calibration="alchemy")


class TestCalibration(unittest.TestCase):
    # Overconfident-but-ordered fixture: ranking perfect, probabilities off.
    SCORES = [0.05, 0.15, 0.85, 0.95]
    LABELS = [0, 0, 1, 1]

    def test_platt_fit_deterministic(self):
        first = fit_platt(self.SCORES, self.LABELS)
        second = fit_platt(self.SCORES, self.LABELS)
        self.assertEqual((first.slope, first.intercept),
                         (second.slope, second.intercept))
        self.assertEqual(first.dev_count, 4)
        self.assertTrue(math.isfinite(first.slope))

    def test_platt_preserves_ranking(self):
        fitted = fit_platt(self.SCORES, self.LABELS)
        calibrated = [fitted.apply(score) for score in self.SCORES]
        self.assertEqual(sorted(calibrated), calibrated)  # monotone
        for value in calibrated:
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_platt_needs_both_classes(self):
        with self.assertRaises(ValidationError):
            fit_platt([0.1, 0.2], [0, 0])
        with self.assertRaises(ValidationError):
            fit_platt([], [])

    def test_isotonic_improves_train_brier(self):
        scores = [0.1, 0.9, 0.2, 0.8]
        labels = [0, 0, 1, 1]  # non-monotone: room to improve
        fitted = fit_isotonic(scores, labels)
        before = brier_score(scores, labels)
        after = brier_score([fitted.apply(score) for score in scores], labels)
        self.assertLessEqual(after, before)
        self.assertEqual(fitted.dev_count, 4)

    def test_isotonic_deterministic(self):
        first = fit_isotonic(self.SCORES, self.LABELS)
        second = fit_isotonic(self.SCORES, self.LABELS)
        self.assertEqual((first.knots, first.values), (second.knots, second.values))

    def test_brier_and_log_loss(self):
        self.assertAlmostEqual(brier_score([0.0, 1.0], [0, 1]), 0.0)
        self.assertAlmostEqual(brier_score([0.5, 0.5], [0, 1]), 0.25)
        self.assertTrue(log_loss([0.0, 1.0], [0, 1]) < 1e-6)
        with self.assertRaises(ValidationError):
            brier_score([0.5], [0, 1])  # length mismatch

    def test_reliability_table(self):
        table = reliability_summary([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1], bins=2)
        self.assertEqual(len(table), 2)
        self.assertEqual(table[0]["count"], 2)
        self.assertAlmostEqual(table[0]["empirical_rate"], 0.0)
        self.assertAlmostEqual(table[1]["empirical_rate"], 1.0)
        empty = reliability_summary([0.9], [1], bins=3)
        self.assertEqual(empty[0]["count"], 0)
        self.assertIsNone(empty[0]["empirical_rate"])

    def test_calibration_split_summary(self):
        dev = _samples([0.1, 0.2], [0.8, 0.9], split="dev")
        test = _samples([0.15, 0.4], [0.6, 0.95], split="test")
        fitted = fit_platt([s.score for s in dev], [0, 0, 1, 1])
        summary = evaluate_calibration_split(test, "fx", "test", fitted, "m", True)
        self.assertEqual(summary.method, "platt")
        self.assertEqual(summary.dev_count, 4)
        self.assertEqual(summary.test_count, 4)
        self.assertTrue(summary.brier_after <= summary.brier_before + 1e-9)
        json.dumps(summary.to_dict())


class TestHeldoutVerification(unittest.TestCase):
    def _records(self):
        dev = _trials([0.9, 0.8], [0.2, 0.3], split="dev")
        test = _trials([0.85, 0.75], [0.25, 0.35], split="test")
        return dev + test

    def test_eer_candidate_to_test(self):
        report = run_heldout_verification(self._records(), "fx", "m", "enc", True)
        self.assertEqual(report.kind, "speaker_verification")
        self.assertEqual(report.candidate["criterion"], "eer")
        self.assertAlmostEqual(report.test_summary["eer"], 0.0)
        json.dumps(report.to_dict())

    def test_speaker_leakage_blocked(self):
        dev = [TrialRecord(trial_id="g0", same_speaker=True, similarity=0.9,
                           speaker_id="spk1", split="dev")]
        test = [TrialRecord(trial_id="g1", same_speaker=True, similarity=0.85,
                            speaker_id="spk1", split="test")]
        with self.assertRaises(ValidationError):
            run_heldout_verification(dev + test, "fx", "m", "enc", True)

    def test_trial_leakage_blocked(self):
        dev = [TrialRecord(trial_id="dup", same_speaker=True, similarity=0.9,
                           split="dev")]
        test = [TrialRecord(trial_id="dup", same_speaker=False, similarity=0.1,
                            split="test")]
        with self.assertRaises(ValidationError):
            run_heldout_verification(dev + test, "fx", "m", "enc", True)

    def test_verification_summary_fields(self):
        summary = evaluate_verification_split(
            _trials(GENUINE, IMPOSTOR), "fx", "dev", 0.5, "m", "enc", True)
        self.assertEqual((summary.trial_count, summary.genuine_count,
                          summary.impostor_count), (6, 3, 3))
        self.assertAlmostEqual(summary.far, 0.0)
        self.assertAlmostEqual(summary.trr, 1.0)
        self.assertEqual(summary.embedder_version, "enc")
        json.dumps(summary.to_dict())


class TestSubgroups(unittest.TestCase):
    def _records(self):
        return ([LabeledSample(sample_id=f"en{i}", label="real", score=score,
                               language="en", source="tts-x", split="dev")
                 for i, score in enumerate([0.1, 0.2])] +
                [LabeledSample(sample_id=f"es{i}", label="synthetic", score=score,
                               language="es", source="tts-x", split="dev")
                 for i, score in enumerate([0.8, 0.9])])

    def test_language_grouping(self):
        output = evaluate_subgroups(self._records(), "language", "fx", "dev",
                                    0.5, min_n=2)
        self.assertEqual(set(output["groups"]), {"en", "es"})
        self.assertEqual(output["groups"]["en"]["real_count"], 2)

    def test_source_grouping(self):
        output = evaluate_subgroups(self._records(), "language", "fx", "dev",
                                    0.5, min_n=2)
        self.assertIn("en", output["groups"])

    def test_min_n_skip(self):
        output = evaluate_subgroups(self._records(), "language", "fx", "dev",
                                    0.5, min_n=10)
        self.assertTrue(output["groups"]["en"]["skipped"])
        self.assertIn("minimum", output["groups"]["en"]["reason"])

    def test_invalid_key_rejected(self):
        with self.assertRaises(ValidationError):
            evaluate_subgroups(self._records(), "codec", "fx", "dev", 0.5)


class TestConfidenceIntervals(unittest.TestCase):
    def _accuracy(self, scores, labels):
        correct = sum(1 for score, label in zip(scores, labels)
                      if (score >= 0.5) == bool(label))
        return correct / len(scores) if scores else None

    def test_bootstrap_sane_bounds(self):
        scores = [0.1, 0.2, 0.8, 0.9] * 5
        labels = [0, 0, 1, 1] * 5
        interval = bootstrap_ci(scores, labels, self._accuracy,
                                n_boot=50, seed=7)
        self.assertAlmostEqual(interval["point"], 1.0)
        self.assertLessEqual(interval["lo"], interval["point"])
        self.assertLessEqual(interval["point"], interval["hi"])
        self.assertEqual(interval["seed"], 7)
        self.assertEqual(interval["n"], 20)

    def test_bootstrap_deterministic(self):
        scores = [0.1, 0.6, 0.4, 0.9] * 5
        labels = [0, 0, 1, 1] * 5
        first = bootstrap_ci(scores, labels, self._accuracy, n_boot=50, seed=3)
        second = bootstrap_ci(scores, labels, self._accuracy, n_boot=50, seed=3)
        self.assertEqual(first, second)

    def test_bootstrap_small_n(self):
        interval = bootstrap_ci([0.1, 0.9], [0, 1], self._accuracy)
        self.assertIsNone(interval["point"])
        self.assertIn("too few", interval["reason"])


class TestProvenancePrivacyGuards(unittest.TestCase):
    def test_mock_real_separation(self):
        dev = [LabeledSample(sample_id="a", label="real", score=0.1,
                             split="dev", is_mock=True)]
        test = [LabeledSample(sample_id="b", label="synthetic", score=0.9,
                              split="test", is_mock=False)]
        with self.assertRaises(ValidationError):
            run_heldout_detection(dev + test, "fx", "m", True)
        ok = run_heldout_detection(
            [LabeledSample(sample_id="a", label="real", score=0.1,
                           split="dev", is_mock=True),
             LabeledSample(sample_id="b", label="synthetic", score=0.9,
                           split="dev", is_mock=True)] +
            [LabeledSample(sample_id="c", label="real", score=0.2,
                           split="test", is_mock=True)],
            "fx", "m", True)
        self.assertTrue(ok.is_mock)

    def test_no_audio_vectors_owners_in_results(self):
        dev = [LabeledSample(sample_id="a", label="real", score=0.1,
                             audio=(0.111, 0.222), split="dev"),
               LabeledSample(sample_id="b", label="synthetic", score=0.9,
                             audio=(0.555, 0.666), split="dev")]
        test = [LabeledSample(sample_id="c", label="real", score=0.2,
                              audio=(0.333, 0.444), split="test"),
                LabeledSample(sample_id="d", label="synthetic", score=0.8,
                              audio=(0.777, 0.888), split="test")]
        report = run_heldout_detection(dev + test, "fx", "m", True)
        text = json.dumps(report.to_dict())
        # Raw sample arrays must never appear (exact serialized forms);
        # metadata key names (e.g. "audio_overlap") describe checks.
        for array in ("[0.111, 0.222]", "[0.555, 0.666]",
                      "[0.333, 0.444]", "[0.777, 0.888]"):
            self.assertNotIn(array, text)
        for banned in ("embedding", "owner_id", "contact", "secret"):
            self.assertNotIn(banned, text)

    def test_production_thresholds_untouched(self):
        # Part 9 produces evidence; it must never rewrite app thresholds.
        from backend.risk_engine import RiskFusionEngine, risk_level_for

        engine = RiskFusionEngine()
        self.assertEqual((engine.weights.synthetic, engine.weights.speaker),
                         (0.6, 0.4))
        self.assertEqual(
            [risk_level_for(score) for score in (39.0, 40.0, 69.0, 70.0, None)],
            ["LOW", "MEDIUM", "MEDIUM", "HIGH", "UNKNOWN"])

    def test_base_module_untouched_behavior(self):
        # Spot-check the reused Part 4 primitives still behave identically.
        result = base_eval.evaluate_detection(
            [{"score": 0.9, "label": "synthetic"},
             {"score": 0.1, "label": "real"}], threshold=0.5)
        self.assertAlmostEqual(result.accuracy, 1.0)
        self.assertAlmostEqual(result.roc_auc, 1.0)


if __name__ == "__main__":
    unittest.main()
