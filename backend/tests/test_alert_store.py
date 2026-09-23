"""Tests for the Part 6 alert domain. Stdlib unittest only."""
from __future__ import annotations

import json
import threading
import unittest

from backend.alert_store import (
    AlertStore,
    SecurityAlert,
    build_alert,
)
from backend.b4_schemas import RiskAssessment, RiskProvenance, RiskReason
from backend.schemas import ValidationError


def _assessment(score: float | None = 91.0, mock: bool = True) -> RiskAssessment:
    return RiskAssessment(
        session_id="call-1", chunk_id="c0018", risk_score=score,
        risk_level="HIGH" if score is not None and score >= 70 else
                   ("UNKNOWN" if score is None else "LOW"),
        confidence=0.8, synthetic_probability=0.91,
        speaker_consistency=64.0, context_risk=None,
        reasons=(RiskReason(code="SYNTHETIC_VOICE_SIGNAL", message="sig",
                            severity="warning", source="synthetic_detection"),),
        provenance=RiskProvenance("cm-mock", "enc-mock", "enc-mock",
                                  "usr-1", mock),
        is_mock=mock, processing_time_ms=1.0)


def _assessment_at(score: float | None, level: str) -> RiskAssessment:
    base = _assessment(score if score is not None else 0.0)
    return RiskAssessment(
        session_id=base.session_id, chunk_id=base.chunk_id,
        risk_score=score, risk_level=level, confidence=base.confidence,
        synthetic_probability=base.synthetic_probability,
        speaker_consistency=base.speaker_consistency,
        context_risk=None, reasons=(), provenance=base.provenance,
        is_mock=True, processing_time_ms=base.processing_time_ms)


class TestAlertBuilder(unittest.TestCase):
    def test_high_creates_alert(self):
        alert = build_alert(_assessment(91.0), timestamp=18.0)
        self.assertIsInstance(alert, SecurityAlert)
        self.assertEqual(alert.call_id, "call-1")
        self.assertAlmostEqual(alert.risk, 91.0)
        self.assertEqual(alert.risk_level, "HIGH")
        self.assertEqual(alert.timestamp, 18.0)

    def test_medium_creates_no_alert(self):
        self.assertIsNone(build_alert(_assessment_at(50.0, "MEDIUM"), timestamp=5.0))

    def test_low_creates_no_alert(self):
        self.assertIsNone(build_alert(_assessment_at(10.0, "LOW"), timestamp=5.0))

    def test_unknown_creates_no_alert(self):
        self.assertIsNone(build_alert(_assessment(None), timestamp=5.0))

    def test_mock_flag_preserved(self):
        alert = build_alert(_assessment(91.0, mock=True), timestamp=1.0)
        assert alert is not None
        self.assertTrue(alert.is_mock)

    def test_mock_reason_present(self):
        base = _assessment(91.0, mock=True)
        mock_reason = RiskReason(code="MOCK_MODEL_SIGNAL", message="dev mock",
                                 severity="warning", source="provenance")
        assessment = RiskAssessment(
            session_id=base.session_id, chunk_id=base.chunk_id,
            risk_score=base.risk_score, risk_level=base.risk_level,
            confidence=base.confidence,
            synthetic_probability=base.synthetic_probability,
            speaker_consistency=base.speaker_consistency,
            context_risk=None, reasons=base.reasons + (mock_reason,),
            provenance=base.provenance, is_mock=True,
            processing_time_ms=base.processing_time_ms)
        alert = build_alert(assessment, timestamp=1.0)
        assert alert is not None
        codes = {r["code"] if isinstance(r, dict) else r.code
                 for r in alert.reasons}
        self.assertIn("MOCK_MODEL_SIGNAL", codes)

    def test_provenance_preserved(self):
        alert = build_alert(_assessment(91.0), timestamp=1.0)
        assert alert is not None
        self.assertEqual(alert.provenance["detector_version"], "cm-mock")
        self.assertEqual(alert.provenance["reference_id"], "usr-1")

    def test_no_risk_recalculation(self):
        alert = build_alert(_assessment(83.25), timestamp=1.0)
        assert alert is not None
        self.assertAlmostEqual(alert.risk, 83.25)  # verbatim, not recomputed

    def test_deterministic_message(self):
        first = build_alert(_assessment(91.0), timestamp=18.0)
        second = build_alert(_assessment(91.0), timestamp=18.0)
        assert first is not None and second is not None
        self.assertEqual(first.title, second.title)
        self.assertEqual(first.message, second.message)
        text = (first.title + first.message).lower()
        for banned in ("fraud confirmed", "deepfake confirmed", "criminal",
                       "scam confirmed", "fake voice proof"):
            self.assertNotIn(banned, text)

    def test_bad_input(self):
        with self.assertRaises(ValidationError):
            build_alert("nope", timestamp=1.0)  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            build_alert(_assessment(91.0), timestamp=-1.0)


class TestAlertStore(unittest.TestCase):
    def setUp(self):
        self.store = AlertStore()

    def test_create(self):
        alert = self.store.create_if_new(_assessment(91.0), timestamp=18.0)
        self.assertIsNotNone(alert)
        self.assertEqual(len(self.store), 1)

    def test_get(self):
        created = self.store.create_if_new(_assessment(91.0), timestamp=1.0)
        assert created is not None
        self.assertIs(created, self.store.get(created.alert_id))

    def test_list_for_call(self):
        self.store.create_if_new(_assessment(91.0), timestamp=1.0)
        other = _assessment(95.0)
        other = RiskAssessment(
            session_id="call-2", chunk_id=other.chunk_id,
            risk_score=other.risk_score, risk_level=other.risk_level,
            confidence=other.confidence,
            synthetic_probability=other.synthetic_probability,
            speaker_consistency=other.speaker_consistency,
            context_risk=None, reasons=(), provenance=other.provenance,
            is_mock=True, processing_time_ms=other.processing_time_ms)
        self.store.create_if_new(other, timestamp=40.0)
        self.assertEqual(len(self.store.list_for_call("call-1")), 1)
        self.assertEqual(len(self.store.list_for_call("call-2")), 1)

    def test_list_active(self):
        created = self.store.create_if_new(_assessment(91.0), timestamp=1.0)
        assert created is not None
        self.assertEqual(len(self.store.list_active()), 1)
        self.store.acknowledge(created.alert_id)
        self.assertEqual(self.store.list_active(), [])

    def test_acknowledge(self):
        created = self.store.create_if_new(_assessment(91.0), timestamp=1.0)
        assert created is not None
        acknowledged = self.store.acknowledge(created.alert_id)
        self.assertTrue(acknowledged.acknowledged)
        self.assertIs(acknowledged, self.store.get(created.alert_id))  # retained

    def test_repeated_acknowledge(self):
        created = self.store.create_if_new(_assessment(91.0), timestamp=1.0)
        assert created is not None
        self.store.acknowledge(created.alert_id)
        again = self.store.acknowledge(created.alert_id)  # idempotent
        self.assertTrue(again.acknowledged)

    def test_missing_alert(self):
        with self.assertRaises(ValidationError):
            self.store.get("ghost")
        with self.assertRaises(ValidationError):
            self.store.acknowledge("ghost")

    def test_call_isolation(self):
        self.store.create_if_new(_assessment(91.0), timestamp=1.0)
        self.assertEqual(self.store.list_for_call("other-call"), [])

    def test_thread_safety(self):
        errors: list = []

        def work(i: int) -> None:
            try:
                score = 80.0 + (i % 10)
                item = _assessment_at(score, "HIGH")
                item = RiskAssessment(
                    session_id=f"call-{i % 4}", chunk_id=item.chunk_id,
                    risk_score=item.risk_score, risk_level=item.risk_level,
                    confidence=item.confidence,
                    synthetic_probability=item.synthetic_probability,
                    speaker_consistency=item.speaker_consistency,
                    context_risk=None, reasons=(), provenance=item.provenance,
                    is_mock=True, processing_time_ms=item.processing_time_ms)
                self.store.create_if_new(item, timestamp=float(i))
            except Exception as exc:  # noqa: BLE001 - collected for assertion
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(24)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])

    def test_safe_serialization(self):
        created = self.store.create_if_new(_assessment(91.0), timestamp=1.0)
        assert created is not None
        json.dumps(created.to_dict())

    def test_no_embedding(self):
        created = self.store.create_if_new(_assessment(91.0), timestamp=1.0)
        assert created is not None
        self.assertNotIn("embedding", json.dumps(created.to_dict()))

    def test_no_audio(self):
        created = self.store.create_if_new(_assessment(91.0), timestamp=1.0)
        assert created is not None
        self.assertNotIn("audio", json.dumps(created.to_dict()).lower().replace(
            "authenticity", ""))

    def test_cooldown_deduplication(self):
        first = self.store.create_if_new(_assessment(91.0), timestamp=10.0)
        second = self.store.create_if_new(_assessment(92.0), timestamp=20.0)
        assert first is not None and second is not None
        self.assertIs(first, second)  # within 30s cooldown
        self.assertEqual(len(self.store), 1)
        third = self.store.create_if_new(_assessment(93.0), timestamp=45.0)
        assert third is not None
        self.assertIsNot(first, third)  # outside cooldown
        self.assertEqual(len(self.store), 2)

    def test_cooldown_configurable(self):
        store = AlertStore(cooldown_s=5.0)
        first = store.create_if_new(_assessment(91.0), timestamp=10.0)
        second = store.create_if_new(_assessment(91.0), timestamp=20.0)
        assert first is not None and second is not None
        self.assertIsNot(first, second)


if __name__ == "__main__":
    unittest.main()
