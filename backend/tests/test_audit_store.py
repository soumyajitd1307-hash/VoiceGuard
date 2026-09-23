"""Tests for the Part 6 audit domain. Stdlib unittest only."""
from __future__ import annotations

import json
import threading
import unittest

from backend.audit_store import AuditEvent, AuditStore
from backend.schemas import ValidationError


class TestAuditStore(unittest.TestCase):
    def setUp(self):
        self.store = AuditStore()

    def test_append(self):
        event = self.store.append("call_started", "call-1", "call started")
        self.assertIsInstance(event, AuditEvent)
        self.assertEqual(event.event_type, "call_started")
        self.assertEqual(len(self.store), 1)

    def test_get(self):
        created = self.store.append("risk_update", "call-1", "risk 42/100")
        self.assertIs(created, self.store.get(created.event_id))
        with self.assertRaises(ValidationError):
            self.store.get("ghost")

    def test_list_by_call(self):
        self.store.append("call_started", "call-1", "started")
        self.store.append("call_started", "call-2", "started")
        self.store.append("risk_update", "call-1", "risk 10/100")
        listed = self.store.list_for_call("call-1")
        self.assertEqual(len(listed), 2)
        self.assertTrue(all(e.call_id == "call-1" for e in listed))

    def test_append_only(self):
        created = self.store.append("call_started", "call-1", "started")
        self.assertFalse(hasattr(self.store, "delete"))
        self.assertFalse(hasattr(self.store, "update"))
        with self.assertRaises(AttributeError):
            created.event_type = "tampered"  # frozen dataclass

    def test_event_ordering(self):
        first = self.store.append("call_started", "call-1", "started")
        second = self.store.append("risk_update", "call-1", "risk update")
        third = self.store.append("call_terminated", "call-1", "terminated")
        listed = self.store.list_for_call("call-1")
        self.assertEqual([e.event_id for e in listed],
                         [first.event_id, second.event_id, third.event_id])

    def test_mock_propagation(self):
        event = self.store.append("alert_created", "call-1", "alert",
                                  is_mock=True)
        self.assertTrue(event.is_mock)
        real = self.store.append("alert_created", "call-1", "alert",
                                 is_mock=False)
        self.assertFalse(real.is_mock)

    def test_no_pii(self):
        event = self.store.append("call_started", "call-1", "started")
        text = json.dumps(event.to_dict())
        for banned in ("owner_id", "phone", "contact", "ProfileReference"):
            self.assertNotIn(banned, text)

    def test_no_embedding(self):
        event = self.store.append("risk_update", "call-1", "risk 42/100")
        self.assertNotIn("embedding", json.dumps(event.to_dict()))

    def test_no_audio(self):
        event = self.store.append("risk_update", "call-1", "risk 42/100")
        self.assertNotIn("audio", json.dumps(event.to_dict()))

    def test_invalid_event_type(self):
        with self.assertRaises(ValidationError):
            self.store.append("hacked", "call-1", "x")

    def test_invalid_actor(self):
        with self.assertRaises(ValidationError):
            self.store.append("call_started", "call-1", "x", actor="root")

    def test_thread_safety(self):
        errors: list = []

        def work(i: int) -> None:
            try:
                self.store.append("risk_update", f"call-{i % 4}", f"risk {i}")
            except Exception as exc:  # noqa: BLE001 - collected for assertion
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(32)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.store), 32)


if __name__ == "__main__":
    unittest.main()
