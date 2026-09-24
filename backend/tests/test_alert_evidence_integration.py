"""Part 6 integration: CallService + alert/evidence/audit + REST/WS.

Stdlib unittest only. Uses the real B3 pipeline, risk engine, adapter and
stores (mock models); doubles only to force specific risk bands.
"""
from __future__ import annotations

import json
import math
import unittest
from unittest import mock

from backend.call_service import (
    CallService,
    view_acknowledge_alert,
    view_get_call,
    view_get_evidence,
    view_list_alerts,
)
from backend.schemas import ValidationError


def _settings():
    from backend.config import Settings

    return Settings(
        model_name="mock", model_version="mock-heuristic-v0.1.0",
        embedder_name="mock", embedder_version="mock-spectral-v0.1.0",
        synthetic_threshold=0.7, real_threshold=0.3,
        min_duration_s=0.25, max_duration_s=30.0,
        max_id_length=128, log_level="CRITICAL")


def _service() -> CallService:
    from backend.b4_service import Backend4Service
    from backend.profile_store import ProfileStore

    settings = _settings()
    profiles = ProfileStore()
    return CallService(
        profile_store=profiles,
        b4_service=Backend4Service(settings, profile_store=profiles))


def _reset_singletons():
    from backend.b4_service import reset_b4_service
    from backend.detector import reset_detector
    from backend.embeddings import reset_embedding_service
    from backend.models.embed_registry import reset_embedder_registry
    from backend.models.registry import reset_model_registry
    from backend.pipeline import reset_pipeline

    reset_detector()
    reset_embedding_service()
    reset_embedder_registry()
    reset_model_registry()
    reset_pipeline()
    reset_b4_service()


def _high_chunk(call_id: str = "1042", chunk_id: str = "c0018") -> dict:
    # Square-ish wave scores ~0.82 synthetic through the real mock model.
    return {
        "audio": [0.9 if i % 2 else -0.9 for i in range(8000)],
        "sample_rate": 16000, "session_id": call_id, "chunk_id": chunk_id,
        "timestamp_s": 18.0, "is_speech": True, "speech_ratio": 0.95}


def _low_chunk(call_id: str = "1042", chunk_id: str = "c0018") -> dict:
    return {
        "audio": [0.05 * math.sin(2.0 * math.pi * 440.0 * i / 16000)
                  for i in range(8000)],
        "sample_rate": 16000, "session_id": call_id, "chunk_id": chunk_id,
        "timestamp_s": 5.0, "is_speech": True, "speech_ratio": 0.9}


class TestAlertEvidenceIntegration(unittest.TestCase):
    def setUp(self):
        _reset_singletons()
        self.service = _service()

    def tearDown(self):
        _reset_singletons()

    def _live_call(self, call_id: str = "1042"):
        return self.service.start_call("owner-1", call_id=call_id)

    def test_process_chunk_creates_evidence(self):
        session = self._live_call()
        self.service.process_call_chunk(session.call_id, _high_chunk())
        records = self.service.evidence.list_for_call(session.call_id)
        types = {r.evidence_type for r in records}
        self.assertIn("synthetic_voice_signal", types)
        self.assertIn("risk_assessment", types)

    def test_high_mock_assessment_creates_mock_alert(self):
        session = self._live_call()
        self.service.process_call_chunk(session.call_id, _high_chunk())
        alerts = self.service.alerts.list_for_call(session.call_id)
        self.assertEqual(len(alerts), 1)
        self.assertTrue(alerts[0].is_mock)
        self.assertEqual(alerts[0].risk_level, "HIGH")

    def test_medium_creates_no_alert(self):
        session = self._live_call()
        self.service.process_call_chunk(session.call_id, _low_chunk())
        self.assertEqual(self.service.alerts.list_for_call(session.call_id), [])

    def test_repeated_high_risk_chunks_deduplicate(self):
        session = self._live_call()
        self.service.process_call_chunk(session.call_id, _high_chunk(chunk_id="c1"))
        second = _high_chunk()
        second["chunk_id"] = "c2"
        self.service.process_call_chunk(session.call_id, second)
        alerts = self.service.alerts.list_for_call(session.call_id)
        self.assertEqual(len(alerts), 1)  # same cooldown window

    def test_call_termination_creates_audit(self):
        session = self._live_call()
        self.service.process_call_chunk(session.call_id, _low_chunk())
        self.service.terminate_call(session.call_id)
        types = [e.event_type for e in
                 self.service.audit.list_for_call(session.call_id)]
        self.assertIn("call_started", types)
        self.assertIn("risk_update", types)
        self.assertIn("call_terminated", types)
        self.assertEqual(types[-1], "call_terminated")

    def test_evidence_rest_output(self):
        session = self._live_call()
        self.service.process_call_chunk(session.call_id, _high_chunk())
        status, body = view_get_evidence(self.service, session.call_id)
        self.assertEqual(status, 200)
        self.assertEqual(body["call_id"], session.call_id)
        self.assertTrue(len(body["evidence"]) >= 2)
        json.dumps(body)
        empty = self.service.start_call("owner-1", call_id="empty-1")
        _, empty_body = view_get_evidence(self.service, empty.call_id)
        self.assertEqual(empty_body, {"call_id": empty.call_id, "evidence": []})

    def test_alert_rest_output(self):
        session = self._live_call()
        self.service.process_call_chunk(session.call_id, _high_chunk())
        status, body = view_list_alerts(self.service, session.call_id)
        self.assertEqual(status, 200)
        self.assertEqual(len(body["alerts"]), 1)
        self.assertTrue(body["alerts"][0]["is_mock"])
        missing_status, _ = view_list_alerts(self.service, "ghost")
        self.assertEqual(missing_status, 404)

    def test_acknowledge_route(self):
        session = self._live_call()
        self.service.process_call_chunk(session.call_id, _high_chunk())
        [alert] = self.service.alerts.list_for_call(session.call_id)
        status, body = view_acknowledge_alert(self.service, alert.alert_id)
        self.assertEqual(status, 200)
        self.assertTrue(body["acknowledged"])
        events = self.service.audit.list_for_call(session.call_id)
        self.assertEqual(events[-1].event_type, "alert_acknowledged")
        ghost_status, _ = view_acknowledge_alert(self.service, "ghost")
        self.assertEqual(ghost_status, 404)

    def test_no_raw_vector_anywhere(self):
        session = self._live_call()
        self.service.process_call_chunk(session.call_id, _high_chunk())
        _, call_body = view_get_call(self.service, session.call_id)
        _, evidence_body = view_get_evidence(self.service, session.call_id)
        _, alerts_body = view_list_alerts(self.service, session.call_id)
        text = json.dumps([call_body, evidence_body, alerts_body])
        self.assertNotIn("embedding", text)
        audit_text = json.dumps(
            [e.to_dict() for e in self.service.audit.list_for_call(session.call_id)])
        self.assertNotIn("embedding", audit_text)

    def test_security_alert_ws_message(self):
        received: list = []
        session = self._live_call()
        self.service.ws.connect(session.call_id, received.append)
        self.service.process_call_chunk(session.call_id, _high_chunk())
        kinds = [message["type"] for message in received]
        self.assertIn("risk_update", kinds)
        self.assertIn("security_alert", kinds)
        alert_message = next(m for m in received if m["type"] == "security_alert")
        self.assertEqual(alert_message["callId"], session.call_id)
        self.assertTrue(alert_message["is_mock"])
        self.assertNotIn("embedding", json.dumps(alert_message))

    def test_mock_chain_provenance(self):
        session = self._live_call()
        self.service.process_call_chunk(session.call_id, _high_chunk())
        [alert] = self.service.alerts.list_for_call(session.call_id)
        records = self.service.evidence.list_for_call(session.call_id)
        events = self.service.audit.list_for_call(session.call_id)
        self.assertTrue(alert.is_mock)
        self.assertTrue(all(r.is_mock for r in records))
        self.assertTrue(all(e.is_mock for e in events))
        combined = json.dumps([
            alert.to_dict(), [r.to_dict() for r in records],
            [e.to_dict() for e in events]]).lower()
        for banned in ("fraud confirmed", "deepfake confirmed",
                       "scam confirmed", "criminal"):
            self.assertNotIn(banned, combined)

    def test_call_detail_includes_alerts(self):
        session = self._live_call()
        self.service.process_call_chunk(session.call_id, _high_chunk())
        _, body = view_get_call(self.service, session.call_id)
        self.assertEqual(len(body["alerts"]), 1)
        self.assertEqual(body["evidence_count"], len(
            self.service.evidence.list_for_call(session.call_id)))

    def test_error_in_alert_path_does_not_fabricate(self):
        session = self._live_call()
        with mock.patch.object(
                self.service.alerts, "create_if_new",
                side_effect=ValidationError("store down")):
            with self.assertRaises(ValidationError):
                self.service.process_call_chunk(session.call_id, _high_chunk())


    def test_ended_call_evidence_still_served(self):
        # Regression: B4 must keep serving evidence/alerts after terminate
        # (the frontend refetches them for history calls).
        session = self._live_call("ended-evidence-1")
        self.service.process_call_chunk(
            session.call_id, _high_chunk("ended-evidence-1"))
        status, before = view_get_evidence(
            self.service, session.call_id, None)
        self.assertEqual(status, 200)
        self.assertTrue(before["evidence"])
        self.service.terminate_call(session.call_id)
        status, after = view_get_evidence(
            self.service, session.call_id, None)
        self.assertEqual(status, 200)
        self.assertEqual(
            [r["evidence_id"] for r in after["evidence"]],
            [r["evidence_id"] for r in before["evidence"]])
        status, alerts = view_list_alerts(
            self.service, session.call_id, None)
        self.assertEqual(status, 200)
        self.assertIsInstance(alerts["alerts"], list)


if __name__ == "__main__":
    unittest.main()
