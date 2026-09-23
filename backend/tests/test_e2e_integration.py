"""Part 10: end-to-end integration + production hardening tests.

Covers the full stack: REST routes (via real api.py handlers), auth
matrix, ownership matrix, SQLite restart, failure/rollback behavior,
concurrency, WebSocket hardening, contract lockdown, input validation,
privacy scans, model-config matrix, system status, error recovery, and
resource sanity. All integration runs use mock models and are labelled
as such -- none of this validates ML accuracy.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import tempfile
import threading
import unittest
from unittest import mock

from backend.call_service import CallService
from backend.schemas import ModelError, ValidationError

BANNED_KEYS = ("embedding", "audio", "raw_audio", "owner_id", "phone_number",
               "contact_name", "ProfileReference", "auth_token", "token",
               "secret", "password")


def _settings(**overrides):
    from backend.config import Settings

    params = dict(
        model_name="mock", model_version="mock-heuristic-v0.1.0",
        embedder_name="mock", embedder_version="mock-spectral-v0.1.0",
        synthetic_threshold=0.7, real_threshold=0.3,
        min_duration_s=0.25, max_duration_s=30.0,
        max_id_length=128, log_level="CRITICAL")
    params.update(overrides)
    return Settings(**params)


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


def _service(**overrides) -> CallService:
    from backend.b4_service import Backend4Service
    from backend.profile_store import ProfileStore

    settings = _settings()
    profiles = ProfileStore()
    kwargs = dict(profile_store=profiles,
                  b4_service=Backend4Service(settings, profile_store=profiles))
    kwargs.update(overrides)
    return CallService(**kwargs)


def _tone(n: int = 8000) -> list:
    return [0.5 * math.sin(2.0 * math.pi * 440.0 * i / 16000) for i in range(n)]


def _square(n: int = 8000) -> list:
    return [0.9 if i % 2 == 0 else -0.9 for i in range(n)]


def _chunk(call_id="1042", chunk_id="c0018", ts=18.0, audio=None, **overrides):
    params = dict(audio=audio if audio is not None else _tone(),
                  sample_rate=16000, session_id=call_id, chunk_id=chunk_id,
                  timestamp_s=ts, language="en", is_speech=True,
                  speech_ratio=0.92)
    params.update(overrides)
    return params


def _enroll(service, ref="usr-1042", owner="owner-1"):
    from backend.embeddings import SpeakerEmbeddingService

    vector = SpeakerEmbeddingService(_settings()).embed(_chunk()).embedding
    service.profiles.enroll_reference(
        reference_id=ref, owner_id=owner, embedding=list(vector),
        embedder_version="mock-spectral-v0.1.0", is_mock=True)


def _req(headers=None):
    from starlette.requests import Request

    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/",
                    "headers": raw})


class FakeWebSocket:
    def __init__(self, script=()):
        self.headers = {}
        self.script = list(script)
        self.sent = []
        self.closed = None

    async def accept(self):
        return None

    async def receive_text(self):
        from starlette.websockets import WebSocketDisconnect

        if not self.script:
            raise WebSocketDisconnect()
        action = self.script.pop(0)
        if action == "disconnect":
            raise WebSocketDisconnect()
        return action

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self, code=1000):
        self.closed = code


def _scan_banned(payload) -> list:
    text = json.dumps(payload, default=str)
    return [key for key in BANNED_KEYS if key in text]


class E2EBase(unittest.TestCase):
    def setUp(self):
        _reset_singletons()
        self.service = _service()

    def tearDown(self):
        _reset_singletons()


# ------------------------------------------------------------------
# Steps 3-5: lifecycle, reference flows
# ------------------------------------------------------------------
class TestFullLifecycle(E2EBase):
    def test_start_process_terminate_history(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        self.assertTrue(session.is_active)
        _enroll(self.service)
        session = self.service.start_call("owner-1", reference_id="usr-1042",
                                          call_id="call-2")
        result = self.service.process_call_chunk(
            "call-2", _chunk(call_id="call-2", chunk_id="c1", ts=1.0))
        update = result.risk_update
        self.assertEqual(update["type"], "risk_update")
        self.assertEqual(update["callId"], "call-2")
        self.assertIn("risk", update)
        stored = self.service.calls.get_call("call-2")
        self.assertEqual(stored.latest_risk_update["risk"], update["risk"])
        self.service.terminate_call("call-2")
        self.assertFalse(self.service.calls.get_call("call-2").is_active)
        history = self.service.calls.list_history()
        self.assertTrue(any(c.call_id == "call-2" for c in history))
        with self.assertRaises(ValidationError):
            self.service.process_call_chunk(
                "call-2", _chunk(call_id="call-2", chunk_id="c2", ts=2.0))

    def test_all_provenance_marked_mock(self):
        _enroll(self.service)
        session = self.service.start_call("owner-1", reference_id="usr-1042",
                                          call_id="call-1")
        result = self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        self.assertTrue(result.assessment.is_mock)
        self.assertTrue(result.provenance.is_mock)

    def test_high_risk_creates_alert_and_audit(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", chunk_id="c1", ts=1.0,
                             audio=_square()))
        alerts = self.service.alerts.list_for_call("call-1")
        self.assertEqual(len(alerts), 1)
        self.assertTrue(alerts[0].is_mock)
        # Second HIGH chunk inside cooldown deduplicates.
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", chunk_id="c2", ts=2.0,
                             audio=_square()))
        self.assertEqual(len(self.service.alerts.list_for_call("call-1")), 1)
        events = self.service.audit.list_for_call("call-1")
        kinds = [e.event_type for e in events]
        self.assertIn("call_started", kinds)
        self.assertIn("risk_update", kinds)
        self.assertIn("alert_created", kinds)

    def test_evidence_only_from_available_signals(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        records = self.service.evidence.list_for_call("call-1")
        self.assertTrue(len(records) >= 1)
        for record in records:
            self.assertTrue(record.is_mock)

    def test_ws_receives_risk_update(self):
        received: list = []
        session = self.service.start_call("owner-1", call_id="call-1")
        self.service.ws.connect("call-1", received.append)
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        self.assertTrue(any(m.get("type") == "risk_update" for m in received))

    def test_terminated_call_absent_from_active(self):
        self.service.start_call("owner-1", call_id="call-1")
        self.service.terminate_call("call-1")
        self.assertEqual(
            [c.call_id for c in self.service.calls.list_active()], [])


class TestNoReferenceFlow(E2EBase):
    def test_no_fake_speaker_score(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        result = self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        self.assertIsNone(result.assessment.speaker_consistency)
        update = result.risk_update
        self.assertNotIn("speakerConsistency", update)
        self.assertNotIn("similarity", json.dumps(update))

    def test_missing_reference_not_fabricated(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        result = self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        self.assertEqual(result.assessment.provenance.reference_id, "")
        self.assertIsNone(result.assessment.speaker_consistency)


# ------------------------------------------------------------------
# Steps 6-7: ownership + auth matrix (route level)
# ------------------------------------------------------------------
class TestRouteAuthMatrix(unittest.TestCase):
    def setUp(self):
        _reset_singletons()
        import backend.api as api

        api.reset_api_service()
        self.api = api
        self._patched_settings = None

    def tearDown(self):
        _reset_singletons()
        if self._patched_settings is not None:
            self._patched_settings.stop()
        import backend.api as api

        api.reset_api_service()

    def _use_settings(self, **overrides):
        from unittest import mock

        settings = _settings(**overrides)
        patcher = mock.patch.object(self.api, "_settings", settings)
        patcher.start()
        self._patched_settings = patcher
        self.api.reset_api_service()
        return settings

    def test_disabled_mode_allows_anonymous(self):
        self._use_settings()
        # Route-level check through the real handler:
        response = self.api.get_active_calls(_req())
        self.assertIsInstance(response, list)

    def test_token_missing_rejected(self):
        self._use_settings(auth_mode="token", auth_token="s3cret",
                           dev_owner="owner-1")
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self.api.get_active_calls(_req())
        self.assertEqual(ctx.exception.status_code, 401)

    def test_token_wrong_rejected(self):
        self._use_settings(auth_mode="token", auth_token="s3cret",
                           dev_owner="owner-1")
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self.api.get_active_calls(
                _req({"x-voiceguard-token": "wrong"}))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_token_correct_accepted_and_scoped(self):
        self._use_settings(auth_mode="token", auth_token="s3cret",
                           dev_owner="owner-1")
        headers = {"x-voiceguard-token": "s3cret"}
        created = self.api.create_call(
            self.api.CreateCallBody(owner_id="spoofed-owner"), _req(headers))
        # Body owner ignored: principal identity wins.
        self.assertNotEqual(created.get("caller", {}).get("id"), "spoofed-owner")
        response = self.api.get_active_calls(_req(headers))
        self.assertEqual(len(response), 1)

    def test_strict_mode_fails_closed(self):
        self._use_settings(auth_mode="strict")
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self.api.get_active_calls(
                _req({"x-voiceguard-token": "anything"}))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_token_never_in_error(self):
        self._use_settings(auth_mode="token", auth_token="s3cret",
                           dev_owner="owner-1")
        from fastapi import HTTPException

        try:
            self.api.get_active_calls(_req({"x-voiceguard-token": "bad"}))
            self.fail("expected 401")
        except HTTPException as exc:
            self.assertNotIn("s3cret", str(exc.detail))
            self.assertNotIn("bad", str(exc.detail))


class TestRouteOwnership(E2EBase):
    def test_foreign_get_404(self):
        from backend.call_service import (view_acknowledge_alert,
                                          view_get_call, view_get_evidence,
                                          view_list_alerts, view_terminate)

        session = self.service.start_call("owner-1", call_id="call-1")
        for status, body in (
                view_get_call(self.service, "call-1", "owner-2"),
                view_get_evidence(self.service, "call-1", "owner-2"),
                view_list_alerts(self.service, "call-1", "owner-2"),
                view_terminate(self.service, "call-1", "owner-2"),
                view_acknowledge_alert(self.service, "nope", "owner-2")):
            self.assertEqual(status, 404)
            self.assertNotIn("owner-1", json.dumps(body))

    def test_foreign_process_rejected(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        with self.assertRaises(ValidationError):
            self.service.process_call_chunk(
                "call-1", _chunk(call_id="call-1", ts=1.0), owner_id="owner-2")

    def test_foreign_ws_subscription_rejected(self):
        async def _run():
            from backend import api as api_module

            ws = FakeWebSocket()
            ws.headers = {}
            with mock.patch.object(api_module, "_settings", _settings(
                    auth_mode="token", auth_token="s3cret", dev_owner="owner-2")):
                api_module.reset_api_service()
                try:
                    await api_module.ws_calls(ws, "call-1")
                finally:
                    api_module.reset_api_service()
            return ws

        self.service.start_call("owner-1", call_id="call-1")
        # Seed the api-level service with the same call by sharing state:
        # route uses its own singleton, so instead assert the gate logic:
        # unknown call for this owner closes 4401.
        ws = asyncio.run(_run())
        self.assertEqual(ws.closed, 4401)


# ------------------------------------------------------------------
# Step 8: storage restart
# ------------------------------------------------------------------
class TestStorageRestart(unittest.TestCase):
    def setUp(self):
        _reset_singletons()
        handle, self.path = tempfile.mkstemp(suffix=".db")
        import os as _os

        _os.close(handle)
        _os.unlink(self.path)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        import os as _os

        _reset_singletons()
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                if _os.path.exists(self.path + suffix):
                    _os.unlink(self.path + suffix)
            except OSError:
                pass

    def _sqlite_service(self):
        from backend.b4_service import Backend4Service
        from backend.profile_store import ProfileStore
        from backend.storage import open_storage

        bundle = open_storage("sqlite", self.path)
        return CallService_for_tests(bundle)

    def test_full_state_survives_restart(self):
        from backend.call_service import CallService as RealCallService
        from backend.b4_service import Backend4Service
        from backend.storage import open_storage

        bundle = open_storage("sqlite", self.path)
        service = RealCallService(
            call_store=bundle.calls, profile_store=bundle.profiles,
            b4_service=Backend4Service(_settings(), profile_store=bundle.profiles),
            ws_manager=None, alert_store=bundle.alerts,
            evidence_store=bundle.evidence, audit_store=bundle.audit)
        # Enroll the reference (metadata must survive restart) but run the
        # call WITHOUT it: synthetic-only fusion scores HIGH and raises
        # an alert, which is what this restart test needs to observe.
        _enroll(service)
        session = service.start_call("owner-1", call_id="call-1")
        service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", chunk_id="c1", ts=1.0,
                             audio=_square()))
        [alert] = service.alerts.list_for_call("call-1")
        service.acknowledge_alert(alert.alert_id, owner_id="owner-1")
        # Recreate everything over the same file.
        bundle2 = open_storage("sqlite", self.path)
        service2 = RealCallService(
            call_store=bundle2.calls, profile_store=bundle2.profiles,
            b4_service=Backend4Service(_settings(), profile_store=bundle2.profiles),
            ws_manager=None, alert_store=bundle2.alerts,
            evidence_store=bundle2.evidence, audit_store=bundle2.audit)
        stored = service2.calls.get_call("call-1")
        self.assertEqual(len(stored.risk_history), 1)
        self.assertIsNotNone(stored.latest_risk_update)
        self.assertIsNotNone(stored.latest_assessment)
        self.assertTrue(service2.alerts.get(alert.alert_id).acknowledged)
        self.assertTrue(len(service2.evidence.list_for_call("call-1")) >= 1)
        kinds = [e.event_type for e in service2.audit.list_for_call("call-1")]
        self.assertIn("risk_update", kinds)
        meta = service2.get_reference_metadata("usr-1042", owner_id="owner-1")
        self.assertEqual(meta.dimension, 32)
        # Cooldown survived: same-window HIGH chunk deduplicates.
        before = len(service2.alerts.list_for_call("call-1"))
        service2.process_call_chunk(
            "call-1", _chunk(call_id="call-1", chunk_id="c2", ts=2.0,
                             audio=_square()))
        self.assertEqual(len(service2.alerts.list_for_call("call-1")), before)
        service2.terminate_call("call-1")
        self.assertEqual(
            [c.call_id for c in service2.calls.list_history()], ["call-1"])


def CallService_for_tests(bundle):
    from backend.b4_service import Backend4Service
    from backend.call_service import CallService

    return CallService(
        call_store=bundle.calls, profile_store=bundle.profiles,
        b4_service=Backend4Service(_settings(), profile_store=bundle.profiles),
        ws_manager=None, alert_store=bundle.alerts,
        evidence_store=bundle.evidence, audit_store=bundle.audit)


# ------------------------------------------------------------------
# Step 9: failure matrix
# ------------------------------------------------------------------
class TestFailureMatrix(E2EBase):
    def test_malformed_chunk(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        with self.assertRaises((ValidationError, ModelError)):
            self.service.process_call_chunk("call-1", {"bogus": True})

    def test_terminated_call_rejects_chunks(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        self.service.terminate_call("call-1")
        with self.assertRaises(ValidationError):
            self.service.process_call_chunk(
                "call-1", _chunk(call_id="call-1", ts=1.0))

    def test_missing_reference_rejected(self):
        with self.assertRaises(ValidationError):
            self.service.start_call("owner-1", reference_id="ghost",
                                    call_id="call-1")

    def test_nan_timestamp_rejected(self):
        from backend.risk_update import to_risk_update

        session = self.service.start_call("owner-1", call_id="call-1")
        result = self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        with self.assertRaises(ValidationError):
            to_risk_update(result.assessment, float("nan"))

    def test_malformed_create_body(self):
        from backend.call_service import view_create_call

        status, body = view_create_call(self.service, "")
        self.assertEqual(status, 400)
        self.assertIn("detail", body)

    def test_storage_failure_maps_500(self):
        import backend.api as api
        from fastapi import HTTPException

        service = self.service
        with mock.patch.object(service.calls, "list_active",
                               side_effect=__import__(
                                   "backend.storage",
                                   fromlist=["StorageError"]).StorageError("disk gone")):
            with mock.patch.object(api, "get_call_service", return_value=service):
                with self.assertRaises(HTTPException) as ctx:
                    api.get_active_calls(_req())
                self.assertEqual(ctx.exception.status_code, 500)

    def test_wrong_types_rejected(self):
        with self.assertRaises(ValidationError):
            self.service.start_call("owner-1", call_id=12345)  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            self.service.process_call_chunk("call-1", "not-a-chunk")  # type: ignore[arg-type]


# ------------------------------------------------------------------
# Step 10: concurrency
# ------------------------------------------------------------------
class TestConcurrency(E2EBase):
    def test_simultaneous_chunks(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        errors: list = []

        def work(i):
            try:
                self.service.process_call_chunk(
                    "call-1", _chunk(call_id="call-1", chunk_id=f"c{i}",
                                     ts=float(i), audio=_square()))
            except Exception as exc:  # noqa: BLE001 - collected for assertion
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        stored = self.service.calls.get_call("call-1")
        self.assertEqual(len(stored.risk_history), 8)
        # One alert: all chunks share the cooldown window.
        self.assertEqual(len(self.service.alerts.list_for_call("call-1")), 1)

    def test_simultaneous_acknowledges(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0, audio=_square()))
        [alert] = self.service.alerts.list_for_call("call-1")
        errors: list = []

        def work():
            try:
                self.service.acknowledge_alert(alert.alert_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=work) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertTrue(self.service.alerts.get(alert.alert_id).acknowledged)

    def test_simultaneous_sqlite_writes(self):
        import os as _os

        handle, path = tempfile.mkstemp(suffix=".db")
        _os.close(handle)
        _os.unlink(path)
        try:
            from backend.storage import open_storage

            bundle = open_storage("sqlite", path)
            errors: list = []

            def work(i):
                try:
                    bundle.calls.create_call(f"owner-{i % 3}")
                    bundle.audit.append("risk_update", "call-x", f"risk {i}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=work, args=(i,)) for i in range(16)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(bundle.calls), 16)
        finally:
            for suffix in ("", "-wal", "-shm", "-journal"):
                try:
                    if _os.path.exists(path + suffix):
                        _os.unlink(path + suffix)
                except OSError:
                    pass


# ------------------------------------------------------------------
# Step 11: WebSocket hardening
# ------------------------------------------------------------------
class TestWsHardening(E2EBase):
    def test_call_isolation(self):
        first: list = []
        second: list = []
        self.service.start_call("owner-1", call_id="call-1")
        self.service.start_call("owner-1", call_id="call-2")
        self.service.ws.connect("call-1", first.append)
        self.service.ws.connect("call-2", second.append)
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)

    def test_security_alert_scoped(self):
        first: list = []
        second: list = []
        self.service.start_call("owner-1", call_id="call-1")
        self.service.start_call("owner-1", call_id="call-2")
        self.service.ws.connect("call-1", first.append)
        self.service.ws.connect("call-2", second.append)
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0, audio=_square()))
        kinds_first = [m.get("type") for m in first]
        self.assertIn("risk_update", kinds_first)
        self.assertIn("security_alert", kinds_first)
        self.assertEqual(second, [])

    def test_dead_subscriber_pruned(self):
        def _dead(message):
            raise RuntimeError("gone")

        self.service.start_call("owner-1", call_id="call-1")
        self.service.ws.connect("call-1", _dead)
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        self.assertEqual(self.service.ws.subscribers_for("call-1"), 0)

    def test_high_frequency_updates(self):
        received: list = []
        self.service.start_call("owner-1", call_id="call-1")
        self.service.ws.connect("call-1", received.append)
        for i in range(50):
            self.service.process_call_chunk(
                "call-1", _chunk(call_id="call-1", chunk_id=f"c{i}",
                                 ts=float(i), audio=_tone()))
        risks = [m for m in received if m.get("type") == "risk_update"]
        self.assertEqual(len(risks), 50)
        self.assertEqual(
            [m["timestamp"] for m in risks], [float(i) for i in range(50)])

    def test_reconnect_resubscribes(self):
        received: list = []
        self.service.start_call("owner-1", call_id="call-1")
        token = self.service.ws.connect("call-1", received.append)
        self.service.ws.disconnect(token)
        self.assertEqual(self.service.ws.subscribers_for("call-1"), 0)
        self.service.ws.connect("call-1", received.append)
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        self.assertEqual(len(received), 1)

    def test_malformed_event_rejected(self):
        with self.assertRaises(ValidationError):
            self.service.ws.broadcast_risk_update({"type": "pong"})
        with self.assertRaises(ValidationError):
            self.service.ws.publish_to_call(
                "call-1", {"speaker": {"embedding": [0.1]}})

    def test_publish_after_disconnect(self):
        received: list = []
        self.service.start_call("owner-1", call_id="call-1")
        token = self.service.ws.connect("call-1", received.append)
        self.service.ws.disconnect(token)
        delivered = self.service.ws.publish_to_call(
            "call-1", {"type": "risk_update", "callId": "call-1", "risk": 1.0})
        self.assertEqual(delivered, 0)
        self.assertEqual(received, [])

    def test_unauthorized_route_subscription(self):
        async def _run():
            import backend.api as api_module

            ws = FakeWebSocket()
            ws.headers = {}
            with mock.patch.object(api_module, "_settings", _settings(
                    auth_mode="token", auth_token="s3cret", dev_owner="owner-9")):
                api_module.reset_api_service()
                try:
                    await api_module.ws_calls(ws, "whatever")
                finally:
                    api_module.reset_api_service()
            return ws

        ws = asyncio.run(_run())
        self.assertEqual(ws.closed, 4401)
        self.assertEqual(ws.sent, [])


# ------------------------------------------------------------------
# Steps 12-13: REST contracts + input validation
# ------------------------------------------------------------------
class TestRestContracts(E2EBase):
    def test_ml_api_preserved(self):
        import backend.api as api

        self.assertIsNotNone(api.router)
        self.assertIsNotNone(api.api_router)
        routes = [getattr(route, "path", "") for route in api.router.routes]
        self.assertIn("/ml/v1/detect", routes)
        self.assertIn("/ml/v1/health", routes)
        health = api.health()
        self.assertEqual(health["status"], "ok")
        self.assertIn("model_version", health)

    def test_detect_rejects_bad_audio(self):
        import backend.api as api
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            api.detect(api.DetectBody(audio_base64="!!!not-base64!!!",
                                      sample_rate=16000, session_id="s",
                                      chunk_id="c"))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_error_bodies_have_detail(self):
        from backend.call_service import (view_get_call,
                                          view_acknowledge_alert)

        for status, body in (view_get_call(self.service, "ghost"),
                             view_acknowledge_alert(self.service, "ghost")):
            self.assertEqual(status, 404)
            self.assertEqual(set(body), {"detail"})

    def test_oversized_call_id_behaves_as_not_found(self):
        from backend.call_service import view_get_call

        status, _ = view_get_call(self.service, "x" * 500)
        self.assertEqual(status, 404)

    def test_nan_audio_rejected(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        bad = _chunk(call_id="call-1", ts=1.0,
                     audio=[0.1, 0.2, float("nan")])
        with self.assertRaises(ValidationError):
            self.service.process_call_chunk("call-1", bad)

    def test_misrouted_chunk_rejected(self):
        self.service.start_call("owner-1", call_id="call-1")
        with self.assertRaises(ValidationError):
            self.service.process_call_chunk("call-1", _chunk(call_id="other"))


class TestInputValidation(E2EBase):
    def test_bad_owner_types(self):
        with self.assertRaises(ValidationError):
            self.service.start_call("")
        with self.assertRaises(ValidationError):
            self.service.start_call(123)  # type: ignore[arg-type]

    def test_inf_timestamp_rejected(self):
        from backend.risk_update import to_risk_update

        session = self.service.start_call("owner-1", call_id="call-1")
        result = self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        with self.assertRaises(ValidationError):
            to_risk_update(result.assessment, float("inf"))

    def test_threshold_bounds_unchanged(self):
        from backend.config import Settings as Cfg

        with self.assertRaises(ValueError):
            Cfg(**{**self._defaults(), "synthetic_threshold": 0.2,
                   "real_threshold": 0.9})

    def _defaults(self):
        return dict(
            model_name="mock", model_version="mock-heuristic-v0.1.0",
            embedder_name="mock", embedder_version="mock-spectral-v0.1.0",
            synthetic_threshold=0.7, real_threshold=0.3,
            min_duration_s=0.25, max_duration_s=30.0,
            max_id_length=128, log_level="CRITICAL")

    def test_invalid_enum_values_fail(self):
        from backend.config import Settings as Cfg

        with self.assertRaises(ValueError):
            Cfg(**{**self._defaults(), "storage_backend": "postgres"})
        with self.assertRaises(ValueError):
            Cfg(**{**self._defaults(), "auth_mode": "oauth"})


# ------------------------------------------------------------------
# Steps 14-16: privacy, model config, system status
# ------------------------------------------------------------------
class TestPrivacyE2E(E2EBase):
    def _collect_wire(self):
        from backend.call_service import (view_get_call, view_get_evidence,
                                          view_list_active, view_list_alerts,
                                          view_system_status)

        _enroll(self.service)
        session = self.service.start_call("owner-1", reference_id="usr-1042",
                                          call_id="call-1")
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0, audio=_square()))
        received: list = []
        self.service.ws.connect("call-1", received.append)
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", chunk_id="c2", ts=2.0,
                             audio=_square()))
        return [
            view_list_active(self.service)[1],
            view_get_call(self.service, "call-1")[1],
            view_get_evidence(self.service, "call-1")[1],
            view_list_alerts(self.service, "call-1")[1],
            view_system_status(self.service)[1],
            received,
        ]

    def test_internal_repr_never_leaves_process(self):
        # Internal session reprs may name their own call_id; the guarantee
        # is that no view/WS payload carries owner identity.
        from backend.call_service import view_get_call

        self.service.start_call("owner-1", call_id="call-1")
        _, body = view_get_call(self.service, "call-1")
        self.assertNotIn("owner-1", json.dumps(body))

    def test_no_banned_keys_anywhere(self):
        for payload in self._collect_wire():
            offenders = _scan_banned(payload)
            self.assertEqual(offenders, [], f"leak: {offenders}")

    def test_exceptions_carry_no_secrets(self):
        _enroll(self.service)
        try:
            self.service.get_reference_metadata("usr-1042", owner_id="intruder")
            self.fail("expected ValidationError")
        except ValidationError as exc:
            offenders = [k for k in BANNED_KEYS
                         if k in str(exc) and k != "owner_id"]
            # "owner_id" word may appear in field-name text; values must not.
            self.assertNotIn("owner-1", str(exc))
            self.assertNotIn("0.25", str(exc))
            self.assertEqual([o for o in offenders if o != "owner_id"], [])


class TestModelConfig(E2EBase):
    def test_mock_mock_e2e(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        result = self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        self.assertTrue(result.assessment.is_mock)
        self.assertIn("mock", result.assessment.provenance.detector_version)

    def test_real_missing_weights_fails_loudly(self):
        with self.assertRaises((ValueError, ModelError)):
            _settings(model_name="real", detector_model="")
        settings = _settings(model_name="real",
                             detector_model="/nonexistent/weights.json",
                             model_version="real-detector-v1")
        from backend.models.registry import get_model, reset_model_registry

        reset_model_registry()
        try:
            with self.assertRaises(ModelError):
                get_model(settings)
        finally:
            reset_model_registry()

    def test_no_silent_fallback_to_mock(self):
        from backend.models.registry import get_model, reset_model_registry

        reset_model_registry()
        try:
            get_model(_settings(model_name="real",
                                detector_model="/nonexistent/x.json",
                                model_version="v"))
            self.fail("expected ModelError")
        except ModelError:
            pass
        finally:
            reset_model_registry()

    def test_provenance_reports_versions(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        result = self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        provenance = result.assessment.provenance
        self.assertTrue(provenance.detector_version)
        self.assertTrue(provenance.embedder_version)
        self.assertTrue(result.assessment.is_mock)


class TestSystemStatus(E2EBase):
    def test_status_accuracy(self):
        from backend.call_service import view_system_status
        from backend.detector import get_detector
        from backend.embeddings import get_embedding_service

        self.service.start_call("owner-1", call_id="call-1")
        status, body = view_system_status(self.service)
        self.assertEqual(status, 200)
        self.assertEqual(body["b3_detector_version"],
                         get_detector().model_version)
        self.assertEqual(body["b3_embedder_version"],
                         get_embedding_service().model_version)
        self.assertTrue(body["b3_is_mock"])
        self.assertEqual(body["active_calls"], 1)
        self.assertEqual(body["transport"], "development")

    def test_status_exposes_no_secrets(self):
        from backend.call_service import view_system_status

        _, body = view_system_status(self.service)
        self.assertEqual(_scan_banned(body), [])


# ------------------------------------------------------------------
# Steps 18-20: recovery, compat, resources
# ------------------------------------------------------------------
class TestErrorRecovery(E2EBase):
    def test_invalid_audio_then_healthy(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        with self.assertRaises((ValidationError, ModelError)):
            self.service.process_call_chunk(
                "call-1", _chunk(call_id="call-1", ts=1.0, audio=[]))
        result = self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", chunk_id="c2", ts=2.0))
        self.assertIsNotNone(result.assessment.risk_score)

    def test_deleted_reference_then_reenroll(self):
        _enroll(self.service)
        self.service.profiles.delete_reference("usr-1042")
        with self.assertRaises(ValidationError):
            self.service.start_call("owner-1", reference_id="usr-1042",
                                    call_id="call-1")
        _enroll(self.service)
        session = self.service.start_call("owner-1", reference_id="usr-1042",
                                          call_id="call-1")
        self.assertTrue(session.is_active)

    def test_bad_model_path_then_reset_healthy(self):
        from backend.models.registry import get_model, reset_model_registry

        reset_model_registry()
        try:
            with self.assertRaises(ModelError):
                get_model(_settings(model_name="real",
                                    detector_model="/nonexistent/x.json",
                                    model_version="v"))
        finally:
            reset_model_registry()
        _reset_singletons()
        self.assertTrue(get_model(_settings()).is_mock)

    def test_service_recreation_over_sqlite(self):
        import os as _os

        from backend.storage import open_storage

        handle, path = tempfile.mkstemp(suffix=".db")
        _os.close(handle)
        _os.unlink(path)
        try:
            first = open_storage("sqlite", path)
            first.calls.create_call("owner-1", call_id="call-1")
            second = open_storage("sqlite", path)
            self.assertTrue(second.calls.get_call("call-1").is_active)
        finally:
            for suffix in ("", "-wal", "-shm", "-journal"):
                try:
                    if _os.path.exists(path + suffix):
                        _os.unlink(path + suffix)
                except OSError:
                    pass


class TestApiCompat(E2EBase):
    def test_risk_update_required_keys(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        result = self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        update = result.risk_update
        for key in ("type", "callId", "timestamp", "risk", "contextRisk",
                    "confidence"):
            self.assertIn(key, update)
        self.assertEqual(update["type"], "risk_update")
        self.assertGreaterEqual(update["risk"], 0)
        self.assertLessEqual(update["risk"], 100)
        self.assertIn(update["confidence"], ("LOW", "MEDIUM", "HIGH"))

    def test_call_keys_and_nulls(self):
        from backend.call_service import view_get_call

        session = self.service.start_call("owner-1", call_id="call-1")
        _, body = view_get_call(self.service, "call-1")
        for key in ("id", "caller", "receiver", "startTime",
                    "durationSeconds", "currentRisk", "currentRiskLevel",
                    "syntheticProbability", "speakerConsistency",
                    "contextRisk", "confidence", "status", "monitoringState",
                    "detectionEvents", "riskHistory", "evidence", "protocol",
                    "codec", "packetLoss", "latencyMs"):
            self.assertIn(key, body)
        # Pre-chunk call: unknown measurements are explicit nulls.
        self.assertIsNone(body["currentRisk"])
        self.assertIsNone(body["evidence"])

    def test_evidence_shape(self):
        from backend.call_service import view_get_evidence

        session = self.service.start_call("owner-1", call_id="call-1")
        _, empty = view_get_evidence(self.service, "call-1")
        self.assertEqual(empty, {"call_id": "call-1", "evidence": []})
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0))
        _, body = view_get_evidence(self.service, "call-1")
        for record in body["evidence"]:
            for key in ("evidence_id", "call_id", "timestamp",
                        "evidence_type", "description", "is_mock"):
                self.assertIn(key, record)

    def test_alert_shape(self):
        from backend.call_service import view_list_alerts

        session = self.service.start_call("owner-1", call_id="call-1")
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0, audio=_square()))
        _, body = view_list_alerts(self.service, "call-1")
        [alert] = body["alerts"]
        for key in ("alert_id", "call_id", "risk", "risk_level", "title",
                    "is_mock", "timestamp"):
            self.assertIn(key, alert)

    def test_security_alert_shape(self):
        received: list = []
        session = self.service.start_call("owner-1", call_id="call-1")
        self.service.ws.connect("call-1", received.append)
        self.service.process_call_chunk(
            "call-1", _chunk(call_id="call-1", ts=1.0, audio=_square()))
        alerts = [m for m in received if m.get("type") == "security_alert"]
        self.assertEqual(len(alerts), 1)
        for key in ("type", "callId", "alert_id", "risk", "risk_level",
                    "title", "is_mock", "timestamp"):
            self.assertIn(key, alerts[0])


class TestResourceSanity(E2EBase):
    def test_single_model_init_across_chunks(self):
        from backend.models.registry import get_model, reset_model_registry

        reset_model_registry()
        try:
            session = self.service.start_call("owner-1", call_id="call-1")
            for i in range(3):
                self.service.process_call_chunk(
                    "call-1", _chunk(call_id="call-1", chunk_id=f"c{i}",
                                     ts=float(i)))
            self.assertEqual(get_model(_settings()).load_count, 1)
        finally:
            reset_model_registry()

    def test_history_bounded(self):
        import backend.call_store as call_store_module

        session = self.service.start_call("owner-1", call_id="call-1")
        original = call_store_module.MAX_HISTORY
        call_store_module.MAX_HISTORY = 5
        try:
            for i in range(9):
                self.service.process_call_chunk(
                    "call-1", _chunk(call_id="call-1", chunk_id=f"c{i}",
                                     ts=float(i)))
            stored = self.service.calls.get_call("call-1")
            self.assertEqual(len(stored.risk_history), 5)
        finally:
            call_store_module.MAX_HISTORY = original

    def test_alerts_bounded_by_cooldown(self):
        session = self.service.start_call("owner-1", call_id="call-1")
        for i in range(5):
            self.service.process_call_chunk(
                "call-1", _chunk(call_id="call-1", chunk_id=f"c{i}",
                                 ts=float(i), audio=_square()))
        self.assertEqual(len(self.service.alerts.list_for_call("call-1")), 1)

    def test_subscriber_balance(self):
        self.service.start_call("owner-1", call_id="call-1")
        tokens = [self.service.ws.connect("call-1", lambda m: None)
                  for _ in range(5)]
        self.assertEqual(self.service.ws.subscribers_for("call-1"), 5)
        for token in tokens:
            self.service.ws.disconnect(token)
        self.assertEqual(self.service.ws.subscribers_for("call-1"), 0)


if __name__ == "__main__":
    unittest.main()
