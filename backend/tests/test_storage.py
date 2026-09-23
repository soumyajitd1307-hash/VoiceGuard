"""Tests for Part 7 storage abstraction (memory + sqlite). Stdlib only."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import unittest

from backend.b4_schemas import RiskAssessment, RiskProvenance
from backend.schemas import ValidationError
from backend.storage import (
    Database,
    StorageError,
    open_storage,
)


def _assessment(score: float = 91.0) -> RiskAssessment:
    return RiskAssessment(
        session_id="call-1", chunk_id="c0018", risk_score=score,
        risk_level="HIGH", confidence=0.8, synthetic_probability=0.91,
        speaker_consistency=64.0, context_risk=None, reasons=(),
        provenance=RiskProvenance("cm", "enc", "enc", "usr-1", True),
        is_mock=True, processing_time_ms=1.0)


def _temp_path() -> str:
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    os.unlink(path)  # sqlite creates it fresh on connect
    return path


def _remove_db(path: str) -> None:
    for candidate in (path, path + "-wal", path + "-shm", path + "-journal"):
        try:
            if os.path.exists(candidate):
                os.unlink(candidate)
        except PermissionError:
            pass  # Windows: transient handle release; suite recreates fresh


class TestStorageBackends(unittest.TestCase):
    def test_schema_initialization(self):
        path = _temp_path()
        try:
            db = Database(path)
            tables = {row[0] for row in db.query(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for expected in ("schema_version", "calls", "profiles", "alerts",
                             "evidence", "audit"):
                self.assertIn(expected, tables)
            version = db.query("SELECT version FROM schema_version")[0][0]
            self.assertEqual(version, 1)
        finally:
            _remove_db(path)

    def test_malformed_db_file(self):
        handle, path = tempfile.mkstemp(suffix=".db")
        try:
            os.write(handle, b"this is not a database")
            os.close(handle)
            with self.assertRaises(StorageError):
                Database(path)
        finally:
            _remove_db(path)

    def test_empty_path_rejected(self):
        with self.assertRaises(StorageError):
            Database("   ")

    def test_unknown_backend(self):
        with self.assertRaises(StorageError):
            open_storage("postgres")

    def test_sqlite_empty_path_never_falls_back(self):
        with self.assertRaises(StorageError):
            open_storage("sqlite", "")

    def test_memory_backend_compatibility(self):
        bundle = open_storage("memory")
        session = bundle.calls.create_call("owner-1")
        self.assertTrue(session.is_active)
        bundle.profiles.enroll_reference("r", "o", [0.1] * 4, "v", True)
        self.assertEqual(len(bundle.profiles), 1)


class TestSqliteCalls(unittest.TestCase):
    def setUp(self):
        self.path = _temp_path()
        self.addCleanup(_remove_db, self.path)
        self.bundle = open_storage("sqlite", self.path)

    def _reopen(self):
        return open_storage("sqlite", self.path)

    def test_call_persistence_reload(self):
        created = self.bundle.calls.create_call("owner-1", reference_id="usr-1")
        update = {"type": "risk_update", "callId": created.call_id,
                  "timestamp": 5.0, "risk": 42.0}
        self.bundle.calls.update_latest(created.call_id, update, _assessment())
        self.bundle.calls.terminate_call(created.call_id)
        reloaded = self._reopen().calls.get_call(created.call_id)
        self.assertEqual(reloaded.owner_id, "owner-1")
        self.assertEqual(reloaded.reference_id, "usr-1")
        self.assertEqual(reloaded.status, "ENDED")
        self.assertIsNotNone(reloaded.ended_at)
        self.assertEqual(reloaded.latest_risk_update["risk"], 42.0)
        self.assertEqual(reloaded.latest_assessment.to_dict(),
                         _assessment().to_dict())
        self.assertEqual(len(reloaded.risk_history), 1)

    def test_bounded_risk_history(self):
        import backend.storage as storage_module

        created = self.bundle.calls.create_call("owner-1")
        original = storage_module.MAX_HISTORY
        storage_module.MAX_HISTORY = 4
        try:
            for i in range(7):
                self.bundle.calls.update_latest(
                    created.call_id,
                    {"type": "risk_update", "timestamp": float(i), "risk": 1.0})
            reloaded = self._reopen().calls.get_call(created.call_id)
            self.assertEqual(len(reloaded.risk_history), 4)
            self.assertEqual(reloaded.risk_history[0]["timestamp"], 3.0)
        finally:
            storage_module.MAX_HISTORY = original

    def test_owner_scoping_preserved(self):
        created = self.bundle.calls.create_call("owner-1")
        reloaded_calls = self._reopen().calls
        self.assertIsNotNone(reloaded_calls.get_call(created.call_id, "owner-1"))
        with self.assertRaises(ValidationError):
            reloaded_calls.get_call(created.call_id, "owner-2")

    def test_duplicate_rejected_after_reload(self):
        self.bundle.calls.create_call("owner-1", call_id="c1")
        with self.assertRaises(ValidationError):
            self._reopen().calls.create_call("owner-1", call_id="c1")


class TestSqliteProfiles(unittest.TestCase):
    def setUp(self):
        self.path = _temp_path()
        self.addCleanup(_remove_db, self.path)
        self.bundle = open_storage("sqlite", self.path)

    def _reopen(self):
        return open_storage("sqlite", self.path)

    def test_profile_persistence_reload(self):
        vector = [0.1 * (i + 1) for i in range(8)]
        self.bundle.profiles.enroll_reference(
            "usr-1", "owner-1", vector, "enc-v1", False)
        ref = self._reopen().profiles.get_reference_vector("usr-1")
        self.assertEqual(list(ref.embedding), vector)
        self.assertEqual(ref.dimension, 8)
        self.assertEqual(ref.embedder_version, "enc-v1")
        self.assertFalse(ref.is_mock)
        meta = self._reopen().profiles.get_metadata("usr-1")
        self.assertNotIn("embedding", meta.__dict__)

    def test_owner_scoping_preserved(self):
        self.bundle.profiles.enroll_reference(
            "usr-1", "owner-1", [0.1] * 4, "v", True)
        reopened = self._reopen().profiles
        reopened.get_reference_vector_for_owner("usr-1", "owner-1")
        with self.assertRaises(ValidationError):
            reopened.get_reference_vector_for_owner("usr-1", "owner-2")

    def test_delete_persists(self):
        self.bundle.profiles.enroll_reference(
            "usr-1", "owner-1", [0.1] * 4, "v", True)
        self.bundle.profiles.delete_reference("usr-1")
        with self.assertRaises(ValidationError):
            self._reopen().profiles.get_metadata("usr-1")


class TestSqliteAlertsEvidenceAudit(unittest.TestCase):
    def setUp(self):
        self.path = _temp_path()
        self.addCleanup(_remove_db, self.path)
        self.bundle = open_storage("sqlite", self.path)

    def _reopen(self):
        return open_storage("sqlite", self.path)

    def test_alert_persistence_reload(self):
        created = self.bundle.alerts.create_if_new(_assessment(), timestamp=10.0)
        assert created is not None
        reloaded = self._reopen().alerts.get(created.alert_id)
        self.assertEqual(reloaded.to_dict(), created.to_dict())
        self.assertTrue(reloaded.is_mock)

    def test_cooldown_survives_restart(self):
        first = self.bundle.alerts.create_if_new(_assessment(), timestamp=10.0)
        second = self._reopen().alerts.create_if_new(_assessment(), timestamp=20.0)
        assert first is not None and second is not None
        self.assertEqual(first.alert_id, second.alert_id)  # deduped via disk
        self.assertEqual(len(self._reopen().alerts), 1)

    def test_acknowledge_persists(self):
        created = self.bundle.alerts.create_if_new(_assessment(), timestamp=1.0)
        assert created is not None
        self.bundle.alerts.acknowledge(created.alert_id)
        self.assertTrue(self._reopen().alerts.get(created.alert_id).acknowledged)
        self.assertEqual(self._reopen().alerts.list_active(), [])

    def test_evidence_persistence_reload(self):
        from backend.evidence_store import EvidenceRecord

        record = EvidenceRecord(
            evidence_id="e1", call_id="call-1", timestamp=5.0,
            evidence_type="risk_assessment", description="risk 91.0/100 (HIGH)",
            risk=91.0, source="risk_fusion", is_mock=True,
            provenance={"a": "b"}, created_at="t")
        self.bundle.evidence.add_all([record])
        self.assertEqual(self._reopen().evidence.get("e1").to_dict(),
                         record.to_dict())

    def test_audit_persistence_ordering(self):
        self.bundle.audit.append("call_started", "call-1", "started")
        self.bundle.audit.append("risk_update", "call-1", "risk 10")
        listed = self._reopen().audit.list_for_call("call-1")
        self.assertEqual([e.event_type for e in listed],
                         ["call_started", "risk_update"])

    def test_concurrent_duplicate_suppression(self):
        errors: list = []

        def work() -> None:
            try:
                self.bundle.alerts.create_if_new(_assessment(), timestamp=10.0)
            except Exception as exc:  # noqa: BLE001 - collected for assertion
                errors.append(exc)

        threads = [threading.Thread(target=work) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.bundle.alerts), 1)

    def test_concurrent_writes(self):
        errors: list = []

        def work(i: int) -> None:
            try:
                session = self.bundle.calls.create_call(f"owner-{i % 4}")
                self.bundle.evidence.add_all([])
                self.bundle.audit.append("risk_update", session.call_id,
                                         f"risk {i}")
            except Exception as exc:  # noqa: BLE001 - collected for assertion
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(24)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.bundle.calls), 24)
        self.assertEqual(len(self.bundle.audit), 24)


class TestTransactions(unittest.TestCase):
    def test_rollback_on_failure(self):
        path = _temp_path()
        self.addCleanup(_remove_db, path)
        db = Database(path)
        with self.assertRaises(RuntimeError):
            with db.transaction() as connection:
                connection.execute(
                    "INSERT INTO audit (event_id, call_id, timestamp, event_type,"
                    " actor, summary, is_mock, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("e1", "c", 0.0, "risk_update", "system", "x", 1, "t"))
                raise RuntimeError("boom")
        self.assertEqual(db.query("SELECT COUNT(*) FROM audit")[0][0], 0)

    def test_storage_error_on_bad_sql(self):
        path = _temp_path()
        self.addCleanup(_remove_db, path)
        db = Database(path)
        with self.assertRaises(StorageError):
            db.write("INSERT INTO no_such_table VALUES (1)")


if __name__ == "__main__":
    unittest.main()
