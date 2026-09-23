"""Tests for the Part 5 call/session store. Stdlib unittest only."""
from __future__ import annotations

import json
import threading
import unittest

from backend.call_store import CallSession, CallStore
from backend.schemas import ValidationError


class TestCallStore(unittest.TestCase):
    def setUp(self):
        self.store = CallStore()

    def test_create_call(self):
        session = self.store.create_call("owner-1")
        self.assertIsInstance(session, CallSession)
        self.assertTrue(session.is_active)
        self.assertEqual(session.status, "ACTIVE")
        self.assertIsNone(session.ended_at)

    def test_generated_call_id(self):
        first = self.store.create_call("owner-1")
        second = self.store.create_call("owner-1")
        self.assertTrue(first.call_id)
        self.assertNotEqual(first.call_id, second.call_id)
        self.assertNotIn("memory", first.call_id.lower())

    def test_duplicate_id_rejected(self):
        self.store.create_call("owner-1", call_id="call-1")
        with self.assertRaises(ValidationError):
            self.store.create_call("owner-1", call_id="call-1")
        self.store.terminate_call("call-1")
        with self.assertRaises(ValidationError):  # history still collides
            self.store.create_call("owner-1", call_id="call-1")

    def test_get_call(self):
        created = self.store.create_call("owner-1")
        self.assertIs(created, self.store.get_call(created.call_id))

    def test_missing_call(self):
        with self.assertRaises(ValidationError):
            self.store.get_call("ghost")

    def test_owner_aware_get(self):
        created = self.store.create_call("owner-1")
        self.assertIs(created, self.store.get_call(created.call_id, "owner-1"))

    def test_wrong_owner_behaves_as_missing(self):
        created = self.store.create_call("owner-1")
        try:
            self.store.get_call(created.call_id, "owner-2")
            self.fail("expected ValidationError")
        except ValidationError as exc:
            missing_text = str(exc)
        try:
            self.store.get_call("ghost", "owner-2")
        except ValidationError as exc2:
            self.assertEqual(missing_text, str(exc2).replace("ghost", created.call_id))
        self.assertNotIn("owner-1", missing_text)

    def test_active_listing(self):
        first = self.store.create_call("owner-1")
        second = self.store.create_call("owner-2")
        ids = {s.call_id for s in self.store.list_active()}
        self.assertEqual(ids, {first.call_id, second.call_id})
        owned = self.store.list_active("owner-1")
        self.assertEqual([s.call_id for s in owned], [first.call_id])

    def test_terminated_removed_from_active(self):
        created = self.store.create_call("owner-1")
        self.store.terminate_call(created.call_id)
        self.assertEqual(self.store.list_active(), [])

    def test_history_listing(self):
        first = self.store.create_call("owner-1")
        second = self.store.create_call("owner-1")
        self.assertEqual(self.store.list_history(), [])
        self.store.terminate_call(first.call_id)
        self.store.terminate_call(second.call_id)
        history = self.store.list_history()
        self.assertEqual(len(history), 2)
        # Newest first (deterministic via seq tiebreak).
        self.assertEqual(history[0].call_id, second.call_id)
        self.assertEqual(history[1].call_id, first.call_id)

    def test_update_latest(self):
        created = self.store.create_call("owner-1")
        update = {"type": "risk_update", "callId": created.call_id,
                  "timestamp": 5.0, "risk": 42.0}
        session = self.store.update_latest(created.call_id, update)
        self.assertEqual(session.latest_risk_update["risk"], 42.0)
        self.assertEqual(len(session.risk_history), 1)
        update["risk"] = 999.0  # stored copies are immune to caller mutation
        self.assertEqual(session.latest_risk_update["risk"], 42.0)

    def test_risk_history_capped(self):
        import backend.call_store as call_store_module

        created = self.store.create_call("owner-1")
        original_max = call_store_module.MAX_HISTORY
        call_store_module.MAX_HISTORY = 5
        try:
            for i in range(9):
                self.store.update_latest(
                    created.call_id,
                    {"type": "risk_update", "callId": created.call_id,
                     "timestamp": float(i), "risk": float(i)})
            self.assertEqual(len(created.risk_history), 5)
            self.assertEqual(created.risk_history[0]["timestamp"], 4.0)
        finally:
            call_store_module.MAX_HISTORY = original_max

    def test_terminate(self):
        created = self.store.create_call("owner-1")
        session = self.store.terminate_call(created.call_id)
        self.assertEqual(session.status, "ENDED")
        self.assertIsNotNone(session.ended_at)
        self.assertEqual(session.monitoring_state, "COMPLETED")

    def test_repeated_terminate_idempotent(self):
        created = self.store.create_call("owner-1")
        first = self.store.terminate_call(created.call_id)
        second = self.store.terminate_call(created.call_id)
        self.assertEqual(first.ended_at, second.ended_at)
        self.assertEqual(second.status, "ENDED")

    def test_update_terminated_rejected(self):
        created = self.store.create_call("owner-1")
        self.store.terminate_call(created.call_id)
        with self.assertRaises(ValidationError):
            self.store.update_latest(created.call_id, {"risk": 1.0})

    def test_clear(self):
        self.store.create_call("owner-1")
        self.store.clear()
        self.assertEqual(len(self.store), 0)
        self.assertEqual(self.store.list_active(), [])

    def test_thread_safe_access(self):
        errors: list = []

        def work(i: int) -> None:
            try:
                session = self.store.create_call(f"owner-{i % 4}")
                self.store.update_latest(
                    session.call_id,
                    {"type": "risk_update", "callId": session.call_id,
                     "timestamp": 1.0, "risk": 10.0})
                self.store.list_active()
                self.store.terminate_call(session.call_id)
            except Exception as exc:  # noqa: BLE001 - collected for assertion
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(24)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])

    def test_no_embedding_or_audio_storage(self):
        created = self.store.create_call("owner-1")
        self.store.update_latest(created.call_id, {"type": "risk_update", "risk": 1.0})
        text = json.dumps(created.to_frontend_dict())
        self.assertNotIn("embedding", text)
        self.assertNotIn("audio", text)

    def test_frontend_shape(self):
        created = self.store.create_call("owner-1")
        self.store.update_latest(
            created.call_id,
            {"type": "risk_update", "callId": created.call_id, "timestamp": 5.0,
             "risk": 42.0, "syntheticProbability": 60.0, "speakerConsistency": 70.0,
             "contextRisk": 10.0, "confidence": "MEDIUM", "monitoringState": "SUSPICIOUS"})
        payload = created.to_frontend_dict()
        self.assertEqual(payload["id"], created.call_id)
        self.assertEqual(payload["currentRisk"], 42.0)
        self.assertEqual(payload["currentRiskLevel"], "MEDIUM")
        self.assertEqual(payload["status"], "ACTIVE")
        self.assertEqual(payload["monitoringState"], "SUSPICIOUS")
        self.assertEqual(payload["detectionEvents"], [])
        self.assertIsNone(payload["evidence"])
        self.assertEqual(len(payload["riskHistory"]), 1)
        json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
