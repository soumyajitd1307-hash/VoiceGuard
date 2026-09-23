"""Tests for Backend 4 core risk domain (fusion engine + schemas).

Stdlib unittest only. Deterministic hand-built fixtures; B3 mock models
used only for integration/provenance checks. No risk numbers here are
validated decisions -- all weights are documented development heuristics.
"""
from __future__ import annotations

import json
import unittest

from backend.b4_schemas import RiskAssessment, RiskProvenance, RiskReason
from backend.risk_engine import (
    RiskFusionEngine,
    RiskWeights,
    is_mock_bundle,
    risk_level_for,
)
from backend.schemas import ValidationError
from backend.signals import build_backend3_signals


def _detection(probability: float, **overrides) -> dict:
    payload = {
        "label": "synthetic",
        "synthetic_probability": probability,
        "model_version": "mock-heuristic-v0.1.0",
        "processing_time_ms": 1.0,
        "session_id": "1042",
        "chunk_id": "c0018",
        "is_mock": True,
    }
    payload.update(overrides)
    return payload


def _similarity(value: float, **overrides) -> dict:
    payload = {
        "reference_id": "usr-1042",
        "session_id": "1042",
        "chunk_id": "c0018",
        "similarity": value,
        "threshold": None,
        "match": "uncertain",
        "model_version": "mock-spectral-v0.1.0",
        "is_mock": True,
        "processing_time_ms": 0.5,
    }
    payload.update(overrides)
    return payload


def _assess(signals):
    return RiskFusionEngine().assess(signals)


def _strip_timing(payload: dict) -> dict:
    payload = json.loads(json.dumps(payload))
    payload.pop("processing_time_ms", None)
    return payload


class TestRiskFusion(unittest.TestCase):
    def test_synthetic_only_input(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.91)))
        self.assertAlmostEqual(assessment.risk_score, 91.0)
        self.assertIsNotNone(assessment.synthetic_probability)
        self.assertIsNone(assessment.speaker_consistency)

    def test_speaker_only_input(self):
        assessment = _assess(build_backend3_signals(
            similarity_result=_similarity(1.0)))
        self.assertAlmostEqual(assessment.risk_score, 0.0)
        self.assertIsNone(assessment.synthetic_probability)
        self.assertAlmostEqual(assessment.speaker_consistency, 100.0)

    def test_synthetic_and_speaker(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(1.0),
            similarity_result=_similarity(1.0)))
        # (0.6*100 + 0.4*0) / 1.0 = 60
        self.assertAlmostEqual(assessment.risk_score, 60.0)

    def test_no_signals_rejected_by_contract(self):
        with self.assertRaises(ValidationError):
            build_backend3_signals()

    def test_missing_synthetic(self):
        assessment = _assess(build_backend3_signals(
            similarity_result=_similarity(0.0)))
        self.assertIsNone(assessment.synthetic_probability)
        self.assertAlmostEqual(assessment.risk_score, 50.0)  # speaker only

    def test_missing_speaker(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.5)))
        self.assertIsNone(assessment.speaker_consistency)
        self.assertAlmostEqual(assessment.risk_score, 50.0)

    def test_similarity_minus_one(self):
        assessment = _assess(build_backend3_signals(
            similarity_result=_similarity(-1.0)))
        self.assertAlmostEqual(assessment.risk_score, 100.0)
        self.assertAlmostEqual(assessment.speaker_consistency, 0.0)

    def test_similarity_zero(self):
        assessment = _assess(build_backend3_signals(
            similarity_result=_similarity(0.0)))
        self.assertAlmostEqual(assessment.risk_score, 50.0)
        self.assertAlmostEqual(assessment.speaker_consistency, 50.0)

    def test_similarity_plus_one(self):
        assessment = _assess(build_backend3_signals(
            similarity_result=_similarity(1.0)))
        self.assertAlmostEqual(assessment.risk_score, 0.0)

    def test_probability_zero(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.0)))
        self.assertAlmostEqual(assessment.risk_score, 0.0)

    def test_probability_one(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(1.0)))
        self.assertAlmostEqual(assessment.risk_score, 100.0)

    def test_boundary_39_low(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.39)))
        self.assertAlmostEqual(assessment.risk_score, 39.0)
        self.assertEqual(assessment.risk_level, "LOW")

    def test_boundary_40_medium(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.40)))
        self.assertEqual(assessment.risk_level, "MEDIUM")

    def test_boundary_69_medium(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.69)))
        self.assertEqual(assessment.risk_level, "MEDIUM")

    def test_boundary_70_high(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.70)))
        self.assertEqual(assessment.risk_level, "HIGH")

    def test_score_clamping(self):
        for signals in (
            build_backend3_signals(detection_result=_detection(1.0)),
            build_backend3_signals(similarity_result=_similarity(-1.0)),
            build_backend3_signals(
                detection_result=_detection(0.0),
                similarity_result=_similarity(1.0)),
        ):
            score = _assess(signals).risk_score
            assert score is not None
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)
        self.assertEqual(risk_level_for(39.99), "LOW")
        self.assertEqual(risk_level_for(70.0), "HIGH")

    def test_weight_renormalization(self):
        # Speaker missing: synthetic takes the full contribution, not 0.6x.
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.5)))
        self.assertAlmostEqual(assessment.risk_score, 50.0)
        # Custom weights respected when both present: (1*100 + 3*0)/4.
        engine = RiskFusionEngine(RiskWeights(synthetic=1.0, speaker=3.0))
        combined = engine.assess(build_backend3_signals(
            detection_result=_detection(1.0),
            similarity_result=_similarity(1.0)))
        self.assertAlmostEqual(combined.risk_score, 25.0)
        with self.assertRaises(ValidationError):
            RiskWeights(synthetic=0.0, speaker=0.0)
        with self.assertRaises(ValidationError):
            RiskWeights(synthetic=-1.0, speaker=1.0)

    def test_deterministic_repeated_input(self):
        signals = build_backend3_signals(
            detection_result=_detection(0.91),
            similarity_result=_similarity(0.64))
        first = _strip_timing(RiskFusionEngine().assess(signals).to_dict())
        second = _strip_timing(RiskFusionEngine().assess(signals).to_dict())
        self.assertEqual(first, second)

    def test_mock_detector(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.9, is_mock=True)))
        self.assertTrue(assessment.is_mock)
        self.assertTrue(assessment.provenance.is_mock)
        self.assertTrue(any(r.code == "MOCK_MODEL_SIGNAL" for r in assessment.reasons))

    def test_mock_embedding(self):
        vec = [0.1] * 32
        bundle = build_backend3_signals(embedding_result={
            "session_id": "1042", "chunk_id": "c0018", "embedding": vec,
            "dimension": 32, "model_version": "mock-spectral-v0.1.0",
            "is_mock": True, "processing_time_ms": 1.0})
        assessment = _assess(bundle)
        self.assertTrue(assessment.is_mock)
        self.assertEqual(assessment.provenance.embedder_version, "mock-spectral-v0.1.0")

    def test_mock_similarity(self):
        assessment = _assess(build_backend3_signals(
            similarity_result=_similarity(0.2, is_mock=True)))
        self.assertTrue(assessment.is_mock)

    def test_mixed_model_provenance(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.9, is_mock=False,
                                        model_version="cm-real-v2"),
            similarity_result=_similarity(0.2, is_mock=True)))
        self.assertTrue(assessment.is_mock)  # any mock taints the bundle
        self.assertEqual(assessment.provenance.detector_version, "cm-real-v2")
        self.assertEqual(assessment.provenance.similarity_version, "mock-spectral-v0.1.0")
        self.assertIsNone(assessment.provenance.embedder_version)

    def test_reference_id_preservation(self):
        assessment = _assess(build_backend3_signals(
            similarity_result=_similarity(0.2, reference_id="usr-1042")))
        self.assertEqual(assessment.provenance.reference_id, "usr-1042")

    def test_session_id_preservation(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.5)))
        self.assertEqual(assessment.session_id, "1042")

    def test_chunk_id_preservation(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.5)))
        self.assertEqual(assessment.chunk_id, "c0018")

    def test_missing_signals_never_zero(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.5)))
        self.assertIsNone(assessment.speaker_consistency)
        payload = assessment.to_dict()
        self.assertIsNone(payload["speaker_consistency"])
        self.assertNotIn("speaker_consistency\": 0", json.dumps(payload))

    def test_no_signals_unknown(self):
        # Empty bundles are rejected by the B3 contract, so "unknown" only
        # arises via risk_level_for(None); the engine never fabricates it.
        with self.assertRaises(ValidationError):
            build_backend3_signals()
        self.assertEqual(risk_level_for(None), "UNKNOWN")

    def test_invalid_probability_rejected(self):
        with self.assertRaises(ValidationError):
            build_backend3_signals(detection_result=_detection(5.0))
        with self.assertRaises(ValidationError):
            build_backend3_signals(detection_result=_detection(float("nan")))

    def test_invalid_similarity_rejected(self):
        with self.assertRaises(ValidationError):
            build_backend3_signals(similarity_result=_similarity(9.0))
        with self.assertRaises(ValidationError):
            build_backend3_signals(similarity_result=_similarity(float("inf")))

    def test_mock_gate_function(self):
        mock_bundle = build_backend3_signals(detection_result=_detection(0.5))
        self.assertTrue(is_mock_bundle(mock_bundle))
        real_bundle = build_backend3_signals(
            detection_result=_detection(0.5, is_mock=False, model_version="cm-v9"))
        self.assertFalse(is_mock_bundle(real_bundle))
        with self.assertRaises(ValidationError):
            is_mock_bundle("nope")  # type: ignore[arg-type]

    def test_reason_schema(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.9),
            similarity_result=_similarity(0.1, match="non_match")))
        codes = {reason.code for reason in assessment.reasons}
        self.assertTrue({"SYNTHETIC_VOICE_SIGNAL", "SPEAKER_MISMATCH",
                         "MOCK_MODEL_SIGNAL"} <= codes)
        for reason in assessment.reasons:
            self.assertIsInstance(reason, RiskReason)
            self.assertIn(reason.severity, ("info", "warning", "critical"))
            self.assertIn(reason.source, ("synthetic_detection", "speaker_similarity",
                                          "context", "fusion", "provenance"))
            self.assertTrue(reason.message and not reason.message.startswith("CRITICAL"))

    def test_confidence_semantics(self):
        one = _assess(build_backend3_signals(detection_result=_detection(0.5)))
        two = _assess(build_backend3_signals(
            detection_result=_detection(0.5), similarity_result=_similarity(0.5)))
        self.assertAlmostEqual(one.confidence, 0.5)
        self.assertAlmostEqual(two.confidence, 0.8)

    def test_b3_produces_no_risk(self):
        bundle = build_backend3_signals(
            detection_result=_detection(0.9),
            similarity_result=_similarity(0.1))
        text = json.dumps(bundle.to_dict()).lower()
        self.assertNotIn("risk_score", text)
        self.assertNotIn("risk_level", text)

    def test_context_passthrough_not_fused(self):
        base = _assess(build_backend3_signals(detection_result=_detection(0.5)))
        with_context = RiskFusionEngine().assess(
            build_backend3_signals(detection_result=_detection(0.5)),
            context_risk=90.0)
        self.assertAlmostEqual(with_context.risk_score, base.risk_score)
        self.assertAlmostEqual(with_context.context_risk, 90.0)
        with self.assertRaises(ValidationError):
            RiskFusionEngine().assess(
                build_backend3_signals(detection_result=_detection(0.5)),
                context_risk=150.0)

    def test_integration_with_b3_pipeline(self):
        import math

        from backend.pipeline import Backend3Pipeline
        from backend.config import Settings

        settings = Settings(
            model_name="mock", model_version="mock-heuristic-v0.1.0",
            embedder_name="mock", embedder_version="mock-spectral-v0.1.0",
            synthetic_threshold=0.7, real_threshold=0.3,
            min_duration_s=0.25, max_duration_s=30.0,
            max_id_length=128, log_level="CRITICAL")
        tone = [0.5 * math.sin(2.0 * math.pi * 440.0 * i / 16000) for i in range(8000)]
        bundle = Backend3Pipeline(settings).process_chunk({
            "audio": tone, "sample_rate": 16000, "session_id": "1042",
            "chunk_id": "c0018", "is_speech": True})
        assessment = RiskFusionEngine().assess(bundle)
        self.assertEqual(assessment.session_id, "1042")
        self.assertTrue(assessment.is_mock)
        self.assertIsNotNone(assessment.risk_score)


if __name__ == "__main__":
    unittest.main()
