"""Tests for the B4 RiskUpdate adapter (transport shape, no transport yet).

Stdlib unittest only. Asserts the frontend-compatible dict shape without
modifying frontend types, and that nothing sensitive leaks onto the wire.
"""
from __future__ import annotations

import json
import unittest

from backend.risk_engine import RiskFusionEngine
from backend.risk_update import to_risk_update
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


class TestRiskUpdateAdapter(unittest.TestCase):
    def test_full_serialization(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.91),
            similarity_result=_similarity(0.64)))
        update = to_risk_update(assessment, timestamp=18.0)
        self.assertEqual(update["type"], "risk_update")
        self.assertEqual(update["callId"], "1042")
        self.assertAlmostEqual(update["timestamp"], 18.0)
        # (0.6*91 + 0.4*((1-0.64)/2*100)) = (54.6 + 7.2) = 61.8
        self.assertAlmostEqual(update["risk"], 61.8)
        self.assertAlmostEqual(update["syntheticProbability"], 91.0)
        self.assertAlmostEqual(update["speakerConsistency"], 82.0)
        self.assertEqual(update["confidence"], "HIGH")  # two signals -> 0.8
        self.assertEqual(update["monitoringState"], "SUSPICIOUS")
        json.dumps(update)

    def test_missing_components_omitted(self):
        synthetic_only = _assess(build_backend3_signals(
            detection_result=_detection(0.5)))
        update = to_risk_update(synthetic_only, timestamp=5.0)
        self.assertIn("syntheticProbability", update)
        self.assertNotIn("speakerConsistency", update)
        similarity_only = _assess(build_backend3_signals(
            similarity_result=_similarity(0.0)))
        update2 = to_risk_update(similarity_only, timestamp=5.0)
        self.assertNotIn("syntheticProbability", update2)
        self.assertIn("speakerConsistency", update2)

    def test_unscored_assessment_rejected(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.5)))
        broken = assessment.to_dict()  # sanity: dict path unaffected
        self.assertIn("risk_score", broken)
        with self.assertRaises(ValidationError):
            to_risk_update("nope", timestamp=1.0)  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            to_risk_update(assessment, timestamp=-1.0)

    def test_no_risk_without_score(self):
        # Scoreless assessments cannot exist via the contract, but the
        # adapter must still refuse them explicitly (defence in depth).
        from backend.b4_schemas import RiskAssessment, RiskProvenance

        empty = RiskAssessment(
            session_id="1042", chunk_id="c0018", risk_score=None,
            risk_level="UNKNOWN", confidence=None, synthetic_probability=None,
            speaker_consistency=None, context_risk=None, reasons=(),
            provenance=RiskProvenance(None, None, None, "", True),
            is_mock=True, processing_time_ms=0.0)
        with self.assertRaises(ValidationError):
            to_risk_update(empty, timestamp=1.0)

    def test_confidence_mapping(self):
        one_signal = _assess(build_backend3_signals(
            detection_result=_detection(0.5)))
        self.assertEqual(to_risk_update(one_signal, timestamp=1.0)["confidence"], "MEDIUM")
        two_signals = _assess(build_backend3_signals(
            detection_result=_detection(0.5), similarity_result=_similarity(0.5)))
        self.assertEqual(to_risk_update(two_signals, timestamp=1.0)["confidence"], "HIGH")

    def test_monitoring_state_mapping(self):
        low = _assess(build_backend3_signals(detection_result=_detection(0.1)))
        self.assertEqual(to_risk_update(low, timestamp=1.0)["monitoringState"],
                         "MONITORING_ACTIVE")
        high = _assess(build_backend3_signals(detection_result=_detection(0.9)))
        self.assertEqual(to_risk_update(high, timestamp=1.0)["monitoringState"],
                         "ALERT_TRIGGERED")

    def test_context_handling(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.5)))
        self.assertEqual(to_risk_update(assessment, timestamp=1.0)["contextRisk"], 0.0)
        self.assertEqual(
            to_risk_update(assessment, timestamp=1.0, context_risk=33.0)["contextRisk"], 33.0)
        with self.assertRaises(ValidationError):
            to_risk_update(assessment, timestamp=1.0, context_risk=500.0)

    def test_no_raw_embeddings_in_risk_update(self):
        vec = [0.1] * 32
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.5),
            embedding_result={
                "session_id": "1042", "chunk_id": "c0018", "embedding": vec,
                "dimension": 32, "model_version": "mock-spectral-v0.1.0",
                "is_mock": True, "processing_time_ms": 1.0}))
        text = json.dumps(to_risk_update(assessment, timestamp=1.0))
        self.assertNotIn("embedding", text)
        self.assertNotIn("0.1, 0.1", text)

    def test_no_b3_metrics_invented(self):
        assessment = _assess(build_backend3_signals(
            detection_result=_detection(0.5)))
        update = to_risk_update(assessment, timestamp=1.0)
        for invented in ("frequencyArtifacts", "prosodyAnomaly", "spectralFlux"):
            self.assertNotIn(invented, update)


    def test_is_mock_propagated_verbatim(self):
        mock_update = to_risk_update(_assess(build_backend3_signals(
            detection_result=_detection(0.5))), timestamp=1.0)
        self.assertTrue(mock_update["is_mock"])
        real_update = to_risk_update(_assess(build_backend3_signals(
            detection_result=_detection(0.5, label="uncertain",
                                        is_mock=False))),
            timestamp=1.0)
        self.assertFalse(real_update["is_mock"])


if __name__ == "__main__":
    unittest.main()
