"""Tests for the Part 6 evidence domain. Stdlib unittest only."""
from __future__ import annotations

import json
import unittest

from backend.b4_schemas import RiskAssessment, RiskProvenance
from backend.evidence_store import (
    EvidenceRecord,
    EvidenceStore,
    build_evidence_for,
)
from backend.schemas import ValidationError
from backend.signals import build_backend3_signals


def _detection(probability: float = 0.82) -> dict:
    return {
        "label": "synthetic", "synthetic_probability": probability,
        "model_version": "mock-heuristic-v0.1.0", "processing_time_ms": 1.0,
        "session_id": "call-1", "chunk_id": "c0018", "is_mock": True}


def _similarity(value: float = 0.64) -> dict:
    return {
        "reference_id": "usr-1", "session_id": "call-1", "chunk_id": "c0018",
        "similarity": value, "threshold": None, "match": "uncertain",
        "model_version": "mock-spectral-v0.1.0", "is_mock": True,
        "processing_time_ms": 0.5}


def _assessment(score: float | None = 75.0) -> RiskAssessment:
    return RiskAssessment(
        session_id="call-1", chunk_id="c0018", risk_score=score,
        risk_level="HIGH" if score is not None else "UNKNOWN",
        confidence=0.8, synthetic_probability=0.82,
        speaker_consistency=82.0, context_risk=None, reasons=(),
        provenance=RiskProvenance("cm-mock", "enc-mock", "enc-mock",
                                  "usr-1", True),
        is_mock=True, processing_time_ms=2.0)


def _by_type(records):
    return {record.evidence_type: record for record in records}


class TestEvidenceBuilder(unittest.TestCase):
    def test_synthetic_evidence(self):
        signals = build_backend3_signals(detection_result=_detection())
        records = build_evidence_for(signals, _assessment(), timestamp=5.0)
        record = _by_type(records)["synthetic_voice_signal"]
        self.assertIsInstance(record, EvidenceRecord)
        self.assertIn("82.0%", record.description)
        self.assertAlmostEqual(record.risk, 82.0)
        self.assertEqual(record.source, "synthetic_detection")

    def test_similarity_evidence(self):
        signals = build_backend3_signals(
            detection_result=_detection(), similarity_result=_similarity())
        record = _by_type(build_evidence_for(signals, _assessment(), 5.0))[
            "speaker_similarity_signal"]
        self.assertIn("0.640", record.description)
        self.assertIn("usr-1", record.description)
        self.assertIsNone(record.risk)  # similarity is not a risk number

    def test_risk_assessment_evidence(self):
        signals = build_backend3_signals(detection_result=_detection())
        record = _by_type(build_evidence_for(signals, _assessment(75.0), 5.0))[
            "risk_assessment"]
        self.assertIn("75.0/100", record.description)
        self.assertAlmostEqual(record.risk, 75.0)

    def test_missing_synthetic_no_evidence(self):
        signals = build_backend3_signals(similarity_result=_similarity())
        types = {r.evidence_type for r in
                 build_evidence_for(signals, _assessment(), 5.0)}
        self.assertNotIn("synthetic_voice_signal", types)

    def test_missing_similarity_no_evidence(self):
        signals = build_backend3_signals(detection_result=_detection())
        types = {r.evidence_type for r in
                 build_evidence_for(signals, _assessment(), 5.0)}
        self.assertNotIn("speaker_similarity_signal", types)

    def test_missing_risk_no_evidence(self):
        signals = build_backend3_signals(detection_result=_detection())
        assessment = _assessment(None)
        types = {r.evidence_type for r in
                 build_evidence_for(signals, assessment, 5.0)}
        self.assertNotIn("risk_assessment", types)

    def test_mock_propagation(self):
        signals = build_backend3_signals(detection_result=_detection())
        for record in build_evidence_for(signals, _assessment(), 5.0):
            self.assertTrue(record.is_mock)
            self.assertIn("mock", record.description.lower())

    def test_provenance(self):
        signals = build_backend3_signals(
            detection_result=_detection(), similarity_result=_similarity())
        records = _by_type(build_evidence_for(signals, _assessment(), 5.0))
        self.assertEqual(records["synthetic_voice_signal"].provenance,
                         {"detector_version": "mock-heuristic-v0.1.0"})
        self.assertEqual(records["speaker_similarity_signal"].provenance,
                         {"similarity_version": "mock-spectral-v0.1.0",
                          "reference_id": "usr-1"})

    def test_privacy(self):
        signals = build_backend3_signals(detection_result=_detection())
        text = json.dumps([r.to_dict() for r in
                           build_evidence_for(signals, _assessment(), 5.0)])
        for banned in ("embedding", "audio", "owner_id", "phone",
                       "ProfileReference"):
            self.assertNotIn(banned, text)

    def test_call_isolation(self):
        from backend.evidence_store import EvidenceStore

        store = EvidenceStore()
        signals = build_backend3_signals(detection_result=_detection())
        store.add_all(build_evidence_for(signals, _assessment(), 5.0))
        self.assertEqual(store.list_for_call("other-call"), [])

    def test_bad_input(self):
        signals = build_backend3_signals(detection_result=_detection())
        with self.assertRaises(ValidationError):
            build_evidence_for("nope", _assessment(), 5.0)  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            build_evidence_for(signals, _assessment(), -1.0)

    def test_no_production_claims(self):
        signals = build_backend3_signals(
            detection_result=_detection(), similarity_result=_similarity())
        text = " ".join(r.description for r in
                        build_evidence_for(signals, _assessment(), 5.0)).lower()
        for banned in ("proof of fraud", "confirmed deepfake", "fake voice proof",
                       "fraud confirmed", "scam confirmed", "criminal"):
            self.assertNotIn(banned, text)


class TestEvidenceStore(unittest.TestCase):
    def setUp(self):
        self.store = EvidenceStore()

    def _records(self):
        signals = build_backend3_signals(detection_result=_detection())
        return build_evidence_for(signals, _assessment(), 5.0)

    def test_add_and_get(self):
        [record] = [r for r in self._records()
                    if r.evidence_type == "synthetic_voice_signal"]
        self.store.add_all([record])
        self.assertIs(record, self.store.get(record.evidence_id))

    def test_missing_record(self):
        with self.assertRaises(ValidationError):
            self.store.get("ghost")

    def test_rejects_non_records(self):
        with self.assertRaises(ValidationError):
            self.store.add_all(["nope"])  # type: ignore[list-item]


if __name__ == "__main__":
    unittest.main()
