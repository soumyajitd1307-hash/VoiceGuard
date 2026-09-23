"""Backend 4 Part 7: storage abstraction (stdlib sqlite3, no ORM).

Two backends behind one domain API:

    memory (default):
        The existing in-memory stores, unchanged. All current unit tests
        keep running against these with zero behavior change.
    sqlite:
        Drop-in ``*Store`` subclasses persisting the same domain objects
        to a file database. Same validation, same semantics, plus restart
        recovery. Embeddings live in ONE isolated ``profiles`` table and
        leave it only through the existing owner-scoped lookups.

Design notes:
    * Subclasses inherit domain behavior and reuse the sibling modules'
      validators/constructors (intra-package reuse, documented here) --
      no duplicated rules, no forked semantics.
    * Parameterized SQL only. WAL mode. One RLock per database; short
      connections per operation (never shared across threads unsafely).
    * ``Database.transaction()`` gives explicit commit/rollback
      boundaries; failures roll back instead of half-writing state.
    * ``schema_version`` table guards against unknown layouts (no
      migrations framework; unknown version -> ``StorageError``).
    * ``open_storage(backend, path)`` builds a full store bundle; memory
      needs no path, sqlite refuses an empty one. Misconfigured sqlite
      NEVER silently falls back to memory.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from backend.alert_store import (
    AlertStore,
    SecurityAlert,
    build_alert,
)
from backend.audit_store import _VALID_ACTORS, _VALID_EVENTS, AuditEvent, AuditStore
from backend.b4_schemas import RiskAssessment, RiskProvenance, RiskReason
from backend.call_store import MAX_HISTORY, CallSession, CallStore, _check_id, _utcnow_iso
from backend.evidence_store import EvidenceRecord, EvidenceStore
from backend.profile_store import (
    ProfileReference,
    ProfileStore,
    ReferenceMetadata,
    ReferenceVector,
    _check_id as _check_profile_id,
)
from backend.profile_store import (
    _check_mock as _check_profile_mock,
)
from backend.profile_store import (
    _check_version as _check_profile_version,
)
from backend.profile_store import (
    _copy_vector as _copy_profile_vector,
)
from backend.schemas import ValidationError

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class StorageError(RuntimeError):
    """Persistence failure (maps to HTTP 500; never a fake success)."""


@dataclass
class StorageBundle:
    """One store per domain, memory or sqlite backed."""

    calls: CallStore
    profiles: ProfileStore
    alerts: AlertStore
    evidence: EvidenceStore
    audit: AuditStore


class Database:
    """Tiny sqlite helper: WAL, locking, transactions, schema guard."""

    def __init__(self, path: str) -> None:
        if not isinstance(path, str) or not path.strip():
            raise StorageError("sqlite storage requires a VG_STORAGE_PATH.")
        self.path = path
        self._lock = threading.RLock()
        try:
            self._init_schema()
        except sqlite3.Error as exc:
            raise StorageError(f"sqlite initialization failed: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA foreign_keys=ON;")
        return connection

    def _init_schema(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(f"""
                CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS calls (
                    call_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                    reference_id TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL, ended_at TEXT,
                    monitoring_state TEXT NOT NULL DEFAULT 'MONITORING_ACTIVE',
                    latest_risk_update TEXT, latest_assessment TEXT,
                    risk_history TEXT NOT NULL DEFAULT '[]', seq INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS profiles (
                    reference_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                    embedding TEXT NOT NULL, dimension INTEGER NOT NULL,
                    embedder_version TEXT NOT NULL, is_mock INTEGER NOT NULL,
                    created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY, call_id TEXT NOT NULL,
                    timestamp REAL NOT NULL, risk REAL NOT NULL,
                    risk_level TEXT NOT NULL, alert_type TEXT NOT NULL,
                    title TEXT NOT NULL, message TEXT NOT NULL,
                    reasons TEXT NOT NULL DEFAULT '[]', is_mock INTEGER NOT NULL,
                    provenance TEXT NOT NULL DEFAULT '{{}}',
                    acknowledged INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY, call_id TEXT NOT NULL,
                    timestamp REAL NOT NULL, evidence_type TEXT NOT NULL,
                    description TEXT NOT NULL, risk REAL,
                    source TEXT NOT NULL, is_mock INTEGER NOT NULL,
                    provenance TEXT NOT NULL DEFAULT '{{}}', created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (
                    event_id TEXT PRIMARY KEY, call_id TEXT NOT NULL,
                    timestamp REAL NOT NULL, event_type TEXT NOT NULL,
                    actor TEXT NOT NULL, summary TEXT NOT NULL,
                    is_mock INTEGER NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_calls_owner ON calls(owner_id);
                CREATE INDEX IF NOT EXISTS idx_alerts_call ON alerts(call_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_call ON evidence(call_id);
                CREATE INDEX IF NOT EXISTS idx_audit_call ON audit(call_id);
            """)
            row = connection.execute(
                "SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,))
            elif row[0] != SCHEMA_VERSION:
                raise StorageError(
                    f"unsupported schema version {row[0]} "
                    f"(expected {SCHEMA_VERSION}).")
            connection.commit()
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection; commit on success, rollback on failure."""
        with self._lock:
            connection = self._connect()
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        try:
            with self.transaction() as connection:
                return connection.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"sqlite query failed: {exc}") from exc

    def write(self, sql: str, params: tuple = ()) -> int:
        try:
            with self.transaction() as connection:
                cursor = connection.execute(sql, params)
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise StorageError(f"sqlite write failed: {exc}") from exc


def _loads(text: str | None, default: Any) -> Any:
    if text is None:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError) as exc:
        raise StorageError(f"stored JSON is malformed: {exc}") from exc


def _dumps(value: Any) -> str:
    return json.dumps(value)


# ---------------------------------------------------------------- calls

def _assessment_from_dict(payload: dict) -> RiskAssessment:
    try:
        return RiskAssessment(
            session_id=payload["session_id"], chunk_id=payload["chunk_id"],
            risk_score=payload["risk_score"], risk_level=payload["risk_level"],
            confidence=payload["confidence"],
            synthetic_probability=payload["synthetic_probability"],
            speaker_consistency=payload["speaker_consistency"],
            context_risk=payload["context_risk"],
            reasons=tuple(RiskReason(**reason) for reason in payload["reasons"]),
            provenance=RiskProvenance(**payload["provenance"]),
            is_mock=payload["is_mock"],
            processing_time_ms=payload["processing_time_ms"])
    except (KeyError, TypeError) as exc:
        raise StorageError(f"stored assessment is malformed: {exc}") from exc


def _session_from_row(row: sqlite3.Row | tuple) -> CallSession:
    (call_id, owner_id, reference_id, started_at, ended_at,
     monitoring_state, latest_update, latest_assessment,
     risk_history, seq) = row
    assessment_payload = _loads(latest_assessment, None)
    return CallSession(
        call_id=call_id, owner_id=owner_id, reference_id=reference_id,
        started_at=started_at, ended_at=ended_at,
        monitoring_state=monitoring_state,
        latest_risk_update=_loads(latest_update, None),
        latest_assessment=(_assessment_from_dict(assessment_payload)
                           if assessment_payload is not None else None),
        risk_history=_loads(risk_history, []),
        _seq=seq)


class SqliteCallStore(CallStore):
    """CallStore semantics, sqlite persistence."""

    def __init__(self, db: Database) -> None:
        super().__init__()
        self._db = db
        rows = self._db.query("SELECT MAX(seq) FROM calls")
        self._seq = rows[0][0] or 0

    def __len__(self) -> int:
        return self._db.query("SELECT COUNT(*) FROM calls")[0][0]

    def _write_session(self, session: CallSession) -> None:
        self._db.write(
            """INSERT INTO calls
               (call_id, owner_id, reference_id, started_at, ended_at,
                monitoring_state, latest_risk_update, latest_assessment,
                risk_history, seq)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(call_id) DO UPDATE SET
               owner_id=excluded.owner_id, reference_id=excluded.reference_id,
               started_at=excluded.started_at, ended_at=excluded.ended_at,
               monitoring_state=excluded.monitoring_state,
               latest_risk_update=excluded.latest_risk_update,
               latest_assessment=excluded.latest_assessment,
               risk_history=excluded.risk_history, seq=excluded.seq""",
            (session.call_id, session.owner_id, session.reference_id,
             session.started_at, session.ended_at, session.monitoring_state,
             _dumps(session.latest_risk_update),
             _dumps(session.latest_assessment.to_dict())
             if session.latest_assessment else None,
             _dumps(session.risk_history), session._seq))

    def _fetch(self, call_id: str) -> CallSession | None:
        rows = self._db.query(
            """SELECT call_id, owner_id, reference_id, started_at, ended_at,
                      monitoring_state, latest_risk_update, latest_assessment,
                      risk_history, seq FROM calls WHERE call_id = ?""",
            (call_id,))
        return _session_from_row(rows[0]) if rows else None

    def create_call(self, owner_id: str, reference_id: str = "",
                    call_id: str | None = None) -> CallSession:
        owner = _check_id(owner_id, "owner_id")
        if not isinstance(reference_id, str):
            raise ValidationError("reference_id must be a string.")
        import uuid as _uuid

        resolved = (_check_id(call_id, "call_id") if call_id is not None
                    else _uuid.uuid4().hex[:12])
        with self._db._lock:
            if self._fetch(resolved) is not None:
                raise ValidationError(f"call_id {resolved!r} already exists.")
            self._seq += 1
            session = CallSession(
                call_id=resolved, owner_id=owner,
                reference_id=reference_id, _seq=self._seq)
            self._write_session(session)
            return session

    def get_call(self, call_id: str, owner_id: str | None = None) -> CallSession:
        cleaned_id = _check_id(call_id, "call_id")
        if owner_id is not None:
            _check_id(owner_id, "owner_id")
        session = self._fetch(cleaned_id)
        if session is None:
            raise ValidationError(f"call {cleaned_id!r} not found.")
        if owner_id is not None and session.owner_id != owner_id:
            raise ValidationError(f"call {cleaned_id!r} not found.")
        return session

    def list_active(self, owner_id: str | None = None) -> list[CallSession]:
        rows = self._db.query(
            """SELECT call_id, owner_id, reference_id, started_at, ended_at,
                      monitoring_state, latest_risk_update, latest_assessment,
                      risk_history, seq FROM calls WHERE ended_at IS NULL""")
        sessions = [_session_from_row(row) for row in rows]
        if owner_id is not None:
            sessions = [s for s in sessions if s.owner_id == owner_id]
        return sorted(sessions, key=lambda s: (s.started_at, s._seq))

    def list_history(self, owner_id: str | None = None) -> list[CallSession]:
        rows = self._db.query(
            """SELECT call_id, owner_id, reference_id, started_at, ended_at,
                      monitoring_state, latest_risk_update, latest_assessment,
                      risk_history, seq FROM calls WHERE ended_at IS NOT NULL""")
        sessions = [_session_from_row(row) for row in rows]
        if owner_id is not None:
            sessions = [s for s in sessions if s.owner_id == owner_id]
        return sorted(sessions, key=lambda s: (s.started_at, s._seq), reverse=True)

    def update_latest(self, call_id: str, risk_update: dict,
                      assessment: Any = None,
                      owner_id: str | None = None) -> CallSession:
        if not isinstance(risk_update, dict):
            raise ValidationError("risk_update must be a dict.")
        import copy as _copy

        session = self.get_call(call_id, owner_id)
        if not session.is_active:
            raise ValidationError(f"call {session.call_id!r} is terminated.")
        snapshot = _copy.deepcopy(risk_update)
        session.latest_risk_update = snapshot
        session.latest_assessment = assessment
        session.risk_history.append(snapshot)
        del session.risk_history[:-MAX_HISTORY]
        state = snapshot.get("monitoringState")
        if isinstance(state, str) and state:
            session.monitoring_state = state
        self._write_session(session)
        return session

    def terminate_call(self, call_id: str,
                       owner_id: str | None = None) -> CallSession:
        from backend.call_store import _utcnow_iso as _now

        session = self.get_call(call_id, owner_id)
        if session.ended_at is None:
            session.ended_at = _now()
            session.monitoring_state = "COMPLETED"
            self._write_session(session)
        return session

    def clear(self) -> None:
        self._db.write("DELETE FROM calls")


# --------------------------------------------------------------- profiles

class SqliteProfileStore(ProfileStore):
    """ProfileStore semantics, sqlite persistence (vectors isolated)."""

    def __init__(self, db: Database) -> None:
        super().__init__()
        self._db = db

    def __len__(self) -> int:
        return self._db.query("SELECT COUNT(*) FROM profiles")[0][0]

    @staticmethod
    def _row_to_record(row: tuple) -> ProfileReference:
        (reference_id, owner_id, embedding_json, dimension,
         embedder_version, is_mock, created_at) = row
        try:
            vector = tuple(float(value) for value in json.loads(embedding_json))
        except (TypeError, ValueError) as exc:
            raise StorageError(f"stored embedding is malformed: {exc}") from exc
        if len(vector) != dimension:
            raise StorageError("stored embedding dimension mismatch.")
        return ProfileReference(
            reference_id=reference_id, owner_id=owner_id, embedding=vector,
            dimension=dimension, embedder_version=embedder_version,
            is_mock=bool(is_mock), created_at=created_at)

    def _fetch(self, reference_id: str) -> ProfileReference | None:
        rows = self._db.query(
            """SELECT reference_id, owner_id, embedding, dimension,
                      embedder_version, is_mock, created_at
               FROM profiles WHERE reference_id = ?""", (reference_id,))
        return self._row_to_record(rows[0]) if rows else None

    def enroll_reference(self, reference_id: str, owner_id: str,
                         embedding: Any, embedder_version: str,
                         is_mock: bool):
        cleaned_id = _check_profile_id(reference_id, "reference_id")
        cleaned_owner = _check_profile_id(owner_id, "owner_id")
        vector = _copy_profile_vector(embedding)
        version = _check_profile_version(embedder_version)
        mock = _check_profile_mock(is_mock)
        import time as _time

        with self._db._lock:
            if self._fetch(cleaned_id) is not None:
                raise ValidationError(
                    f"reference_id {cleaned_id!r} is already enrolled.")
            record = ProfileReference(
                reference_id=cleaned_id, owner_id=cleaned_owner,
                embedding=vector, dimension=len(vector),
                embedder_version=version,
                is_mock=mock, created_at=_time.time())
            self._db.write(
                """INSERT INTO profiles
                   (reference_id, owner_id, embedding, dimension,
                    embedder_version, is_mock, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (record.reference_id, record.owner_id, _dumps(list(vector)),
                 record.dimension, record.embedder_version,
                 int(record.is_mock), record.created_at))
        return ProfileStore._metadata_of(record)

    def _get_record(self, reference_id: str) -> ProfileReference:
        cleaned_id = _check_profile_id(reference_id, "reference_id")
        record = self._fetch(cleaned_id)
        if record is None:
            raise ValidationError(f"reference_id {cleaned_id!r} not found.")
        return record

    def _get_record_for_owner(self, reference_id: str,
                              owner_id: str) -> ProfileReference:
        cleaned_owner = _check_profile_id(owner_id, "owner_id")
        try:
            record = self._get_record(reference_id)
        except ValidationError as exc:
            raise ValidationError(f"reference_id {reference_id!r} not found.") from exc
        if record.owner_id != cleaned_owner:
            raise ValidationError(f"reference_id {reference_id!r} not found.")
        return record

    def get_metadata(self, reference_id: str):
        return ProfileStore._metadata_of(self._get_record(reference_id))

    def get_metadata_for_owner(self, reference_id: str, owner_id: str):
        return ProfileStore._metadata_of(
            self._get_record_for_owner(reference_id, owner_id))

    def get_reference_vector(self, reference_id: str):
        return ProfileStore._vector_of(self._get_record(reference_id))

    def get_reference_vector_for_owner(self, reference_id: str, owner_id: str):
        return ProfileStore._vector_of(
            self._get_record_for_owner(reference_id, owner_id))

    def delete_reference(self, reference_id: str) -> bool:
        cleaned_id = _check_profile_id(reference_id, "reference_id")
        return self._db.write(
            "DELETE FROM profiles WHERE reference_id = ?", (cleaned_id,)) > 0

    def clear(self) -> None:
        self._db.write("DELETE FROM profiles")


# ----------------------------------------------------------------- alerts

def _alert_from_row(row: tuple) -> SecurityAlert:
    (alert_id, call_id, timestamp, risk, risk_level, alert_type, title,
     message, reasons_json, is_mock, provenance_json,
     acknowledged, created_at) = row
    return SecurityAlert(
        alert_id=alert_id, call_id=call_id, timestamp=timestamp, risk=risk,
        risk_level=risk_level, alert_type=alert_type, title=title,
        message=message, reasons=_loads(reasons_json, []),
        is_mock=bool(is_mock), provenance=_loads(provenance_json, {}),
        acknowledged=bool(acknowledged), created_at=created_at)


class SqliteAlertStore(AlertStore):
    """AlertStore semantics (incl. cooldown dedup), sqlite persistence."""

    def __init__(self, db: Database, cooldown_s: float = 30.0) -> None:
        super().__init__(cooldown_s=cooldown_s)
        self._db = db

    def __len__(self) -> int:
        return self._db.query("SELECT COUNT(*) FROM alerts")[0][0]

    def _insert(self, alert: SecurityAlert) -> None:
        self._db.write(
            """INSERT INTO alerts
               (alert_id, call_id, timestamp, risk, risk_level, alert_type,
                title, message, reasons, is_mock, provenance, acknowledged,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (alert.alert_id, alert.call_id, alert.timestamp, alert.risk,
             alert.risk_level, alert.alert_type, alert.title, alert.message,
             _dumps(alert.reasons), int(alert.is_mock),
             _dumps(alert.provenance), int(alert.acknowledged),
             alert.created_at))

    def create_if_new(self, assessment, timestamp: float):
        candidate = build_alert(assessment, timestamp)
        if candidate is None:
            return None
        with self._db._lock:
            rows = self._db.query(
                """SELECT alert_id, call_id, timestamp, risk, risk_level,
                          alert_type, title, message, reasons, is_mock,
                          provenance, acknowledged, created_at
                   FROM alerts WHERE call_id = ? AND alert_type = ?""",
                (candidate.call_id, candidate.alert_type))
            for row in rows:
                existing = _alert_from_row(row)
                if abs(existing.timestamp - candidate.timestamp) <= self.cooldown_s:
                    return existing
            self._insert(candidate)
            return candidate

    def get(self, alert_id: str):
        rows = self._db.query(
            """SELECT alert_id, call_id, timestamp, risk, risk_level,
                      alert_type, title, message, reasons, is_mock,
                      provenance, acknowledged, created_at
               FROM alerts WHERE alert_id = ?""", (alert_id,))
        if not rows:
            raise ValidationError(f"alert {alert_id!r} not found.")
        return _alert_from_row(rows[0])

    def list_for_call(self, call_id: str):
        rows = self._db.query(
            """SELECT alert_id, call_id, timestamp, risk, risk_level,
                      alert_type, title, message, reasons, is_mock,
                      provenance, acknowledged, created_at
               FROM alerts WHERE call_id = ? ORDER BY timestamp""", (call_id,))
        return [_alert_from_row(row) for row in rows]

    def list_active(self):
        rows = self._db.query(
            """SELECT alert_id, call_id, timestamp, risk, risk_level,
                      alert_type, title, message, reasons, is_mock,
                      provenance, acknowledged, created_at
               FROM alerts WHERE acknowledged = 0 ORDER BY timestamp""")
        return [_alert_from_row(row) for row in rows]

    def acknowledge(self, alert_id: str):
        with self._db._lock:
            alert = self.get(alert_id)
            self._db.write("UPDATE alerts SET acknowledged = 1 WHERE alert_id = ?",
                           (alert_id,))
            alert.acknowledged = True
            return alert

    def clear(self) -> None:
        self._db.write("DELETE FROM alerts")


# --------------------------------------------------------------- evidence

def _evidence_from_row(row: tuple):
    from backend.evidence_store import EvidenceRecord as _EvidenceRecord

    (evidence_id, call_id, timestamp, evidence_type, description, risk,
     source, is_mock, provenance_json, created_at) = row
    return _EvidenceRecord(
        evidence_id=evidence_id, call_id=call_id, timestamp=timestamp,
        evidence_type=evidence_type, description=description, risk=risk,
        source=source, is_mock=bool(is_mock),
        provenance=_loads(provenance_json, {}), created_at=created_at)


class SqliteEvidenceStore(EvidenceStore):
    """EvidenceStore semantics, sqlite persistence."""

    def __init__(self, db: Database) -> None:
        super().__init__()
        self._db = db

    def __len__(self) -> int:
        return self._db.query("SELECT COUNT(*) FROM evidence")[0][0]

    def add_all(self, records):
        for record in records:
            from backend.evidence_store import EvidenceRecord as _EvidenceRecord

            if not isinstance(record, _EvidenceRecord):
                raise ValidationError("Only EvidenceRecord objects can be stored.")
            self._db.write(
                """INSERT INTO evidence
                   (evidence_id, call_id, timestamp, evidence_type,
                    description, risk, source, is_mock, provenance, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record.evidence_id, record.call_id, record.timestamp,
                 record.evidence_type, record.description, record.risk,
                 record.source, int(record.is_mock),
                 _dumps(record.provenance), record.created_at))
        return list(records)

    def get(self, evidence_id: str):
        rows = self._db.query(
            """SELECT evidence_id, call_id, timestamp, evidence_type,
                      description, risk, source, is_mock, provenance, created_at
               FROM evidence WHERE evidence_id = ?""", (evidence_id,))
        if not rows:
            raise ValidationError(f"evidence {evidence_id!r} not found.")
        return _evidence_from_row(rows[0])

    def list_for_call(self, call_id: str):
        rows = self._db.query(
            """SELECT evidence_id, call_id, timestamp, evidence_type,
                      description, risk, source, is_mock, provenance, created_at
               FROM evidence WHERE call_id = ? ORDER BY timestamp""", (call_id,))
        return [_evidence_from_row(row) for row in rows]

    def clear(self) -> None:
        self._db.write("DELETE FROM evidence")


# ------------------------------------------------------------------ audit

class SqliteAuditStore(AuditStore):
    """AuditStore semantics (append-only), sqlite persistence."""

    def __init__(self, db: Database) -> None:
        super().__init__()
        self._db = db

    def __len__(self) -> int:
        return self._db.query("SELECT COUNT(*) FROM audit")[0][0]

    def append(self, event_type: str, call_id: str, summary: str,
               actor: str = "system", is_mock: bool = True,
               timestamp: float = 0.0):
        if event_type not in _VALID_EVENTS:
            raise ValidationError(f"Unknown audit event type {event_type!r}.")
        for field_name, value in (("call_id", call_id), ("summary", summary)):
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"{field_name} must be a non-empty string.")
        if actor not in _VALID_ACTORS:
            raise ValidationError(f"actor must be one of {list(_VALID_ACTORS)}.")
        if not isinstance(is_mock, bool):
            raise ValidationError("is_mock must be a boolean.")
        if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                or not 0.0 <= float(timestamp) < 1e9):
            raise ValidationError("timestamp must be call-relative seconds >= 0.")
        import uuid as _uuid
        from backend.audit_store import AuditEvent as _AuditEvent
        from backend.call_store import _utcnow_iso as _now

        event = _AuditEvent(
            event_id=_uuid.uuid4().hex[:12], call_id=call_id,
            timestamp=float(timestamp), event_type=event_type, actor=actor,
            summary=summary, is_mock=is_mock, created_at=_now())
        self._db.write(
            """INSERT INTO audit
               (event_id, call_id, timestamp, event_type, actor, summary,
                is_mock, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (event.event_id, event.call_id, event.timestamp, event.event_type,
             event.actor, event.summary, int(event.is_mock), event.created_at))
        return event

    def get(self, event_id: str):
        from backend.audit_store import AuditEvent as _AuditEvent

        rows = self._db.query(
            """SELECT event_id, call_id, timestamp, event_type, actor,
                      summary, is_mock, created_at
               FROM audit WHERE event_id = ?""", (event_id,))
        if not rows:
            raise ValidationError(f"audit event {event_id!r} not found.")
        (eid, cid, ts, etype, actor, summary, mock, created) = rows[0]
        return _AuditEvent(
            event_id=eid, call_id=cid, timestamp=ts, event_type=etype,
            actor=actor, summary=summary, is_mock=bool(mock), created_at=created)

    def list_for_call(self, call_id: str):
        from backend.audit_store import AuditEvent as _AuditEvent

        rows = self._db.query(
            """SELECT event_id, call_id, timestamp, event_type, actor,
                      summary, is_mock, created_at
               FROM audit WHERE call_id = ? ORDER BY rowid""", (call_id,))
        return [_AuditEvent(
            event_id=r[0], call_id=r[1], timestamp=r[2], event_type=r[3],
            actor=r[4], summary=r[5], is_mock=bool(r[6]), created_at=r[7])
            for r in rows]

    def clear(self) -> None:
        self._db.write("DELETE FROM audit")


# ---------------------------------------------------------------- factory

def open_storage(backend: str, path: str = "") -> StorageBundle:
    """Build a full store bundle. Memory needs no path; sqlite refuses an
    empty one and NEVER silently falls back to memory."""
    from backend.alert_store import AlertStore as _AlertStore
    from backend.audit_store import AuditStore as _AuditStore
    from backend.call_store import CallStore as _CallStore
    from backend.evidence_store import EvidenceStore as _EvidenceStore
    from backend.profile_store import ProfileStore as _ProfileStore

    if backend == "memory":
        return StorageBundle(
            calls=_CallStore(), profiles=_ProfileStore(), alerts=_AlertStore(),
            evidence=_EvidenceStore(), audit=_AuditStore())
    if backend == "sqlite":
        db = Database(path)  # raises StorageError on empty path / bad file
        return StorageBundle(
            calls=SqliteCallStore(db), profiles=SqliteProfileStore(db),
            alerts=SqliteAlertStore(db), evidence=SqliteEvidenceStore(db),
            audit=SqliteAuditStore(db))
    raise StorageError(f"unknown storage backend {backend!r}.")
