"""Tests for Part 5 transport views + application integration. Stdlib only."""
from __future__ import annotations

import json
import math
import unittest

from backend.call_service import (
    CallService,
    view_create_call,
    view_get_call,
    view_get_evidence,
    view_get_history,
    view_system_status,
    view_list_active,
    view_terminate,
)
from backend.schemas import ValidationError


def _tone(n: int = 8000) -> list:
    return [0.5 * math.sin(2.0 * math.pi * 440.0 * i / 16000) for i in range(n)]


def _chunk(**overrides) -> dict:
    params = dict(
        audio=_tone(), sample_rate=16000, session_id="1042", chunk_id="c0018",
        timestamp_s=18.0, language="en", is_speech=True, speech_ratio=0.92)
    params.update(overrides)
    return params


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


def _live_call(service: CallService, owner: str = "owner-1",
               reference_id: str = "") -> object:
    """Start a call whose ID matches the fixture chunk session ("1042").

    Live processing requires B2 chunks tagged with the B4 call ID; the
    shared fixture chunk carries session_id "1042".
    """
    return service.start_call(owner, reference_id=reference_id, call_id="1042")


def _enroll(service: CallService, ref: str = "usr-1042",
            owner: str = "owner-1") -> None:
    from backend.embeddings import SpeakerEmbeddingService

    vector = SpeakerEmbeddingService(_settings()).embed(_chunk()).embedding
    service.profiles.enroll_reference(
        reference_id=ref, owner_id=owner, embedding=list(vector),
        embedder_version="mock-spectral-v0.1.0", is_mock=True)


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


class TestTransportViews(unittest.TestCase):
    def setUp(self):
        _reset_singletons()
        self.service = _service()

    def tearDown(self):
        _reset_singletons()

    def test_active_route_empty(self):
        status, body = view_list_active(self.service)
        self.assertEqual((status, body), (200, []))

    def test_active_route_with_call(self):
        session = self.service.start_call("owner-1")
        status, body = view_list_active(self.service)
        self.assertEqual(status, 200)
        self.assertEqual([call["id"] for call in body], [session.call_id])
        self.assertEqual(body[0]["status"], "ACTIVE")

    def test_call_detail_route(self):
        session = self.service.start_call("owner-1")
        status, body = view_get_call(self.service, session.call_id)
        self.assertEqual(status, 200)
        self.assertEqual(body["id"], session.call_id)
        self.assertIn("caller", body)
        self.assertIn("riskHistory", body)

    def test_history_route_empty(self):
        status, body = view_get_history(self.service)
        self.assertEqual((status, body), (200, []))

    def test_history_route_order(self):
        first = self.service.start_call("owner-1")
        second = self.service.start_call("owner-1")
        self.service.terminate_call(first.call_id)
        self.service.terminate_call(second.call_id)
        status, body = view_get_history(self.service)
        self.assertEqual(status, 200)
        self.assertEqual([call["id"] for call in body],
                         [second.call_id, first.call_id])

    def test_evidence_route_empty(self):
        # Structured wrapper (Part 6 contract); empty list, never fabricated.
        session = self.service.start_call("owner-1")
        status, body = view_get_evidence(self.service, session.call_id)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"call_id": session.call_id, "evidence": []})

    def test_system_status(self):
        status, body = view_system_status(self.service)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["backend"], "VoiceGuard")
        self.assertIn("mock", body["b3_detector_version"])
        self.assertIn("mock", body["b3_embedder_version"])
        self.assertTrue(body["b3_is_mock"])
        self.assertTrue(body["b4_is_mock"])
        self.assertEqual(body["transport"], "development")
        self.assertEqual(body["database"], "in_memory")
        self.assertEqual(body["authentication"], "not_configured")
        json.dumps(body)

    def test_terminate_route(self):
        session = self.service.start_call("owner-1")
        status, body = view_terminate(self.service, session.call_id)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ENDED")
        self.assertEqual(body["monitoringState"], "COMPLETED")
        active = view_list_active(self.service)[1]
        self.assertEqual(active, [])

    def test_missing_call_404(self):
        for view in (view_get_call, view_get_evidence, view_terminate):
            status, body = view(self.service, "ghost")
            self.assertEqual(status, 404)
            self.assertIn("detail", body)

    def test_owner_mismatch_404(self):
        session = self.service.start_call("owner-1")
        status, body = view_get_call(self.service, session.call_id, "owner-2")
        self.assertEqual(status, 404)

    def test_safe_serialization(self):
        session = _live_call(self.service)
        self.service.process_call_chunk(session.call_id, _chunk())
        _, body = view_get_call(self.service, session.call_id)
        json.dumps(body)

    def test_no_embedding_in_response(self):
        _enroll(self.service)
        session = _live_call(self.service, reference_id="usr-1042")
        self.service.process_call_chunk(session.call_id, _chunk())
        _, body = view_get_call(self.service, session.call_id)
        self.assertNotIn("embedding", json.dumps(body))

    def test_no_audio_in_response(self):
        session = _live_call(self.service)
        self.service.process_call_chunk(session.call_id, _chunk())
        _, active = view_list_active(self.service)
        self.assertNotIn("audio", json.dumps(active))

    def test_no_owner_leakage(self):
        session = self.service.start_call("owner-1")
        _, body = view_get_call(self.service, session.call_id)
        self.assertNotIn("owner-1", json.dumps(body))

    def test_create_call_route(self):
        status, body = view_create_call(self.service, "owner-1")
        self.assertEqual(status, 200)
        self.assertIn("id", body)
        bad_status, bad_body = view_create_call(self.service, "")
        self.assertEqual(bad_status, 400)
        self.assertIn("detail", bad_body)

    def test_frontend_call_shape(self):
        session = self.service.start_call("owner-1")
        _, body = view_get_call(self.service, session.call_id)
        for key in ("id", "caller", "receiver", "startTime", "durationSeconds",
                    "currentRisk", "currentRiskLevel", "syntheticProbability",
                    "speakerConsistency", "contextRisk", "confidence", "status",
                    "monitoringState", "detectionEvents", "riskHistory",
                    "evidence", "protocol", "codec", "packetLoss", "latencyMs"):
            self.assertIn(key, body)


class TestApplicationIntegration(unittest.TestCase):
    def setUp(self):
        _reset_singletons()
        self.service = _service()

    def tearDown(self):
        _reset_singletons()

    def test_start_call(self):
        session = self.service.start_call("owner-1")
        self.assertTrue(session.is_active)
        self.assertEqual(session.owner_id, "owner-1")

    def test_start_call_bad_reference(self):
        with self.assertRaises(ValidationError):
            self.service.start_call("owner-1", reference_id="ghost")

    def test_process_updates_store(self):
        session = _live_call(self.service)
        result = self.service.process_call_chunk(session.call_id, _chunk())
        stored = self.service.calls.get_call(session.call_id)
        self.assertIsNotNone(stored.latest_risk_update)
        self.assertEqual(stored.latest_risk_update["risk"],
                         result.risk_update["risk"])
        self.assertEqual(len(stored.risk_history), 1)

    def test_process_publishes_risk_update(self):
        received: list = []
        session = _live_call(self.service)
        self.service.ws.connect(session.call_id, received.append)
        self.service.process_call_chunk(session.call_id, _chunk())
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["type"], "risk_update")
        self.assertEqual(received[0]["callId"], session.call_id)

    def test_reference_flows_from_session(self):
        _enroll(self.service)
        session = _live_call(self.service, reference_id="usr-1042")
        result = self.service.process_call_chunk(session.call_id, _chunk())
        self.assertIsNotNone(result.assessment.speaker_consistency)

    def test_terminated_rejects_chunks(self):
        session = self.service.start_call("owner-1")
        self.service.terminate_call(session.call_id)
        with self.assertRaises(ValidationError):
            self.service.process_call_chunk(session.call_id, _chunk())

    def test_mock_status_preserved(self):
        session = _live_call(self.service)
        result = self.service.process_call_chunk(session.call_id, _chunk())
        self.assertTrue(result.assessment.is_mock)
        _, status = view_system_status(self.service)
        self.assertTrue(status["b4_is_mock"])

    def test_owner_scoped_processing(self):
        session = _live_call(self.service)
        result = self.service.process_call_chunk(
            session.call_id, _chunk(), owner_id="owner-1")
        self.assertEqual(result.risk_update["callId"], session.call_id)
        with self.assertRaises(ValidationError):
            self.service.process_call_chunk(
                session.call_id, _chunk(), owner_id="intruder")

    def test_enrollment_path(self):
        from backend.embeddings import SpeakerEmbeddingService

        vector = SpeakerEmbeddingService(_settings()).embed(_chunk()).embedding
        meta = self.service.enroll_reference(
            "usr-7", "owner-1", list(vector), "mock-spectral-v0.1.0", True)
        self.assertEqual(meta.dimension, 32)
        session = _live_call(self.service, reference_id="usr-7")
        result = self.service.process_call_chunk(session.call_id, _chunk())
        self.assertIsNotNone(result.assessment.speaker_consistency)

    def test_misrouted_chunk_rejected(self):
        session = self.service.start_call("owner-1", call_id="call-9")
        with self.assertRaises(ValidationError):
            # Fixture chunk belongs to session "1042", not this call.
            self.service.process_call_chunk(session.call_id, _chunk())


if __name__ == "__main__":
    unittest.main()
