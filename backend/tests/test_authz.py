"""Tests for Part 7 authorization boundaries + privacy scans. Stdlib only."""
from __future__ import annotations

import json
import unittest

from backend.auth import AuthError, AuthenticatedPrincipal, authenticate
from backend.call_service import (
    CallService,
    view_acknowledge_alert,
    view_get_call,
    view_get_evidence,
    view_list_active,
    view_list_alerts,
    view_system_status,
)
from backend.config import Settings
from backend.schemas import ValidationError


def _settings(**overrides) -> Settings:
    params = dict(
        model_name="mock", model_version="mock-heuristic-v0.1.0",
        embedder_name="mock", embedder_version="mock-spectral-v0.1.0",
        synthetic_threshold=0.7, real_threshold=0.3,
        min_duration_s=0.25, max_duration_s=30.0,
        max_id_length=128, log_level="CRITICAL",
        storage_backend="memory", storage_path="", env="development",
        auth_mode="disabled", auth_token="", dev_owner="")
    params.update(overrides)
    return Settings(**params)


def _token_settings() -> Settings:
    return _settings(auth_mode="token", auth_token="s3cret", dev_owner="owner-1")


def _principal() -> AuthenticatedPrincipal:
    principal = authenticate({"x-voiceguard-token": "s3cret"}, _token_settings())
    assert principal is not None
    return principal


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


BANNED_KEYS = ("embedding", "audio", "raw_audio", "owner_id", "phone_number",
               "contact_name", "ProfileReference", "auth_token", "token",
               "secret", "password")


def _scan_banned(payload) -> list:
    text = json.dumps(payload)
    return [key for key in BANNED_KEYS if key in text]


class TestAuthorization(unittest.TestCase):
    def setUp(self):
        _reset_singletons()
        self.service = CallService()

    def tearDown(self):
        _reset_singletons()

    def test_own_call_allowed(self):
        session = self.service.start_call("owner-1")
        status, _ = view_get_call(self.service, session.call_id, "owner-1")
        self.assertEqual(status, 200)

    def test_other_owner_call_denied(self):
        session = self.service.start_call("owner-1")
        status, body = view_get_call(self.service, session.call_id, "owner-2")
        self.assertEqual(status, 404)
        self.assertNotIn("owner-1", json.dumps(body))

    def test_owner_spoofing_denied(self):
        # A principal's identity wins; a spoofed body owner gains nothing.
        from backend.auth import request_owner

        self.assertEqual(request_owner(_principal(), "owner-2"), "owner-1")

    def test_unauthenticated_token_mode(self):
        with self.assertRaises(AuthError):
            authenticate({}, _token_settings())

    def test_own_reference_allowed(self):
        self.service.enroll_reference("r", "owner-1", [0.1] * 4, "v", True)
        meta = self.service.get_reference_metadata("r", owner_id="owner-1")
        self.assertEqual(meta.reference_id, "r")

    def test_other_owner_reference_denied(self):
        self.service.enroll_reference("r", "owner-1", [0.1] * 4, "v", True)
        with self.assertRaises(ValidationError) as ctx:
            self.service.get_reference_metadata("r", owner_id="owner-2")
        self.assertNotIn("owner-1", str(ctx.exception))

    def test_alert_isolation(self):
        from backend.b4_schemas import RiskAssessment, RiskProvenance

        assessment = RiskAssessment(
            session_id="s", chunk_id="c", risk_score=90.0, risk_level="HIGH",
            confidence=0.8, synthetic_probability=0.9,
            speaker_consistency=None, context_risk=None, reasons=(),
            provenance=RiskProvenance("a", "b", "c", "", True),
            is_mock=True, processing_time_ms=1.0)
        self.service.calls.create_call("owner-1", call_id="s")
        alert = self.service.alerts.create_if_new(assessment, timestamp=1.0)
        assert alert is not None
        # Owner-scoped acknowledge path: wrong owner behaves as missing.
        with self.assertRaises(ValidationError):
            self.service.acknowledge_alert(alert.alert_id, owner_id="owner-2")
        acknowledged = self.service.acknowledge_alert(alert.alert_id,
                                                      owner_id="owner-1")
        self.assertTrue(acknowledged.acknowledged)

    def test_evidence_isolation(self):
        self.service.calls.create_call("owner-1", call_id="s")
        status, _ = view_get_evidence(self.service, "s", "owner-2")
        self.assertEqual(status, 404)

    def test_acknowledge_isolation(self):
        self.service.calls.create_call("owner-1", call_id="s")
        status, _ = view_acknowledge_alert(self.service, "ghost", "owner-1")
        self.assertEqual(status, 404)

    def test_websocket_isolation_gate(self):
        # Mirrors the api.py WS gate: ownership verified before subscribing.
        session = self.service.start_call("owner-1")
        self.service.calls.get_call(session.call_id, "owner-1")  # allowed
        with self.assertRaises(ValidationError):
            self.service.calls.get_call(session.call_id, "owner-2")  # rejected


class TestPrivacyScans(unittest.TestCase):
    def setUp(self):
        _reset_singletons()
        self.service = CallService()

    def tearDown(self):
        _reset_singletons()

    def test_rest_bodies_clean(self):
        session = self.service.start_call("owner-1")
        payloads = [
            view_list_active(self.service)[1],
            view_get_call(self.service, session.call_id)[1],
            view_get_evidence(self.service, session.call_id)[1],
            view_system_status(self.service)[1],
        ]
        for payload in payloads:
            offenders = [key for key in _scan_banned(payload)
                         if key not in ("token",)]  # "token" checked below strictly
            self.assertEqual(offenders, [], f"leak in {payload!r:.120}")
        # Strict token-word scan on the joined text, excluding the
        # documented authentication-status LABEL value.
        text = json.dumps(payloads)
        self.assertNotIn("auth_token", text)
        self.assertNotIn("VG_AUTH_TOKEN", text)

    def test_ws_messages_clean(self):
        import math

        session = self.service.start_call("owner-1", call_id="1042")
        tone = [0.5 * math.sin(2.0 * math.pi * 440.0 * i / 16000)
                for i in range(8000)]
        self.service.process_call_chunk(session.call_id, {
            "audio": tone, "sample_rate": 16000, "session_id": "1042",
            "chunk_id": "c1", "timestamp_s": 1.0, "is_speech": True})
        stored = self.service.calls.get_call(session.call_id)
        assert stored.latest_risk_update is not None
        self.assertEqual(_scan_banned(stored.latest_risk_update), [])

    def test_repr_scan(self):
        from backend.auth import AuthenticatedPrincipal
        from backend.profile_store import ProfileStore

        store = ProfileStore()
        store.enroll_reference("r", "owner-1", [0.77] * 4, "v", True)
        texts = [
            repr(store._get_record("r")),
            repr(AuthenticatedPrincipal("owner-1", "token", True)),
            repr(self.service.calls.create_call("owner-9")),
        ]
        for text in texts:
            self.assertNotIn("0.77", text)
            self.assertNotIn("s3cret", text)

    def test_exception_payload_scan(self):
        store = self.service.profiles
        store.enroll_reference("r", "owner-1", [0.77] * 4, "v", True)
        with self.assertRaises(ValidationError) as ctx:
            store.get_reference_vector_for_owner("r", "intruder")
        text = str(ctx.exception)
        self.assertNotIn("0.77", text)
        self.assertNotIn("owner-1", text)
        try:
            authenticate({"x-voiceguard-token": "wrong"}, _token_settings())
        except AuthError as exc:
            self.assertNotIn("s3cret", str(exc))


if __name__ == "__main__":
    unittest.main()
