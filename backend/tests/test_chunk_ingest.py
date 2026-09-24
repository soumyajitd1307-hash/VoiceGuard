"""Tests for the live-driver ingest view (Prompt 5 B4 endpoint logic).

Exercises view_ingest_chunk directly (repo convention: no HTTP client):
B2 wire dicts through the full B3+B4 path, unknown/terminated/misrouted
calls, malformed payloads, and non-speech rejection.
"""
from __future__ import annotations

import math
import unittest

from backend.call_service import (
    CallService,
    view_create_call,
    view_ingest_chunk,
    view_terminate,
)


def _tone(n: int = 8000) -> list:
    return [0.5 * math.sin(2.0 * math.pi * 440.0 * i / 16000) for i in range(n)]


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


def _chunk(call_id: str, **overrides) -> dict:
    params = dict(
        audio=_tone(), sample_rate=16000, session_id=call_id, chunk_id="c00000",
        timestamp_s=0.0, language="en", is_speech=True, speech_ratio=0.92)
    params.update(overrides)
    return params


class TestIngestChunkView(unittest.TestCase):
    def setUp(self):
        _reset_singletons()
        self.service = _service()
        status, body = view_create_call(self.service, "owner-1")
        self.assertEqual(status, 200)
        self.call_id = body["id"]

    def tearDown(self):
        _reset_singletons()

    def test_ingest_ok_returns_risk_update(self):
        status, body = view_ingest_chunk(
            self.service, self.call_id, _chunk(self.call_id))
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["call_id"], self.call_id)
        self.assertEqual(body["chunk_id"], "c00000")
        update = body["risk_update"]
        self.assertEqual(update["type"], "risk_update")
        self.assertEqual(update["callId"], self.call_id)
        self.assertIn("risk", update)

    def test_ingest_unknown_call_404(self):
        status, body = view_ingest_chunk(
            self.service, "ghost", _chunk("ghost"))
        self.assertEqual(status, 404)
        self.assertIn("detail", body)

    def test_ingest_terminated_call_400(self):
        status, _ = view_terminate(self.service, self.call_id)
        self.assertEqual(status, 200)
        status, body = view_ingest_chunk(
            self.service, self.call_id, _chunk(self.call_id))
        self.assertEqual(status, 400)
        self.assertIn("detail", body)

    def test_ingest_non_dict_payload_400(self):
        status, body = view_ingest_chunk(self.service, self.call_id, "nope")
        self.assertEqual(status, 400)

    def test_ingest_misrouted_chunk_400(self):
        status, body = view_ingest_chunk(
            self.service, self.call_id, _chunk("other-call"))
        self.assertEqual(status, 400)

    def test_ingest_non_speech_rejected(self):
        # Silence never becomes a detection: the B3 path refuses
        # non-speech chunks instead of scoring them.
        status, body = view_ingest_chunk(
            self.service, self.call_id,
            _chunk(self.call_id, is_speech=False, speech_ratio=0.0))
        self.assertEqual(status, 400)
        self.assertIn("detail", body)


if __name__ == "__main__":
    unittest.main()
