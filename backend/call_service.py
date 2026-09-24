"""Backend 4 Part 5: call application service + REST view logic.

``CallService`` is the single integration path for live chunks::

    start_call(owner_id, reference_id?, call_id?)
        -> CallSession (reference verified resolvable up front)
    process_call_chunk(call_id, chunk, timestamp?, owner_id?)
        1. load session (owner-scoped when owner given; terminated rejects)
        2. Backend4Service.process_chunk(chunk, owner_id, reference_id, ts)
        3. CallStore.update_latest(...) (safe copies, capped history)
        4. WsConnectionManager.broadcast_risk_update(...) (call-scoped)
        -> Backend4Result
    terminate_call(call_id, owner_id?) -> CallSession (session state only)

The ``view_*`` functions below are framework-free REST handlers returning
``(status_code, body)`` tuples; ``backend/api.py`` mounts them on FastAPI.
Bodies match the existing frontend contracts (``src/services/api.ts``,
``src/types/index.ts``); unknown values are explicit nulls, never
fabrications. Missing calls / wrong owners uniformly yield
``(404, {"detail": ...})`` so ownership cannot be probed.

Authentication is NOT implemented: ``owner_id`` arguments are trusted
internal parameters. External transport MUST add auth middleware; until
then every externally reachable use is development-only (said plainly in
``system_status`` output).
"""
from __future__ import annotations

import logging
from typing import Any

from backend.alert_store import AlertStore
from backend.audit_store import (
    AuditStore,
    EVENT_ALERT_ACKNOWLEDGED,
    EVENT_ALERT_CREATED,
    EVENT_CALL_STARTED,
    EVENT_CALL_TERMINATED,
    EVENT_EVIDENCE_CREATED,
    EVENT_RISK_UPDATE,
    summarize_assessment,
)
from backend.b4_service import Backend4Service
from backend.call_store import CallSession, CallStore
from backend.evidence_store import EvidenceStore, build_evidence_for
from backend.profile_store import ProfileStore
from backend.schemas import ValidationError
from backend.ws_manager import WsConnectionManager

log = logging.getLogger(__name__)

NOT_FOUND = (404, {"detail": "call not found"})


class CallService:
    """Application service wiring sessions, profiles, B4 and pub/sub."""

    def __init__(
        self,
        call_store: CallStore | None = None,
        profile_store: ProfileStore | None = None,
        b4_service: Backend4Service | None = None,
        ws_manager: WsConnectionManager | None = None,
        alert_store: AlertStore | None = None,
        evidence_store: EvidenceStore | None = None,
        audit_store: AuditStore | None = None,
    ) -> None:
        # NOTE: explicit None checks (never `or`): store objects define
        # __len__, so an empty store is falsy and must not be replaced.
        self._profiles = profile_store if profile_store is not None else ProfileStore()
        self._calls = call_store if call_store is not None else CallStore()
        # Share the profile store so enrollment here is visible to analysis.
        self._b4 = (b4_service if b4_service is not None
                    else Backend4Service(profile_store=self._profiles))
        self._ws = ws_manager if ws_manager is not None else WsConnectionManager()
        self._alerts = alert_store if alert_store is not None else AlertStore()
        self._evidence = evidence_store if evidence_store is not None else EvidenceStore()
        self._audit = audit_store if audit_store is not None else AuditStore()

    @property
    def calls(self) -> CallStore:
        return self._calls

    @property
    def profiles(self) -> ProfileStore:
        return self._profiles

    @property
    def ws(self) -> WsConnectionManager:
        return self._ws

    @property
    def alerts(self) -> AlertStore:
        return self._alerts

    @property
    def evidence(self) -> EvidenceStore:
        return self._evidence

    @property
    def audit(self) -> AuditStore:
        return self._audit

    # -- lifecycle --

    def start_call(
        self,
        owner_id: str,
        reference_id: str = "",
        call_id: str | None = None,
    ) -> CallSession:
        """Create a session, verifying the reference resolves up front
        (owner-aware) so a bad reference fails fast, not mid-call."""
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValidationError("owner_id must be a non-empty string.")
        if reference_id:
            self._profiles.get_metadata_for_owner(reference_id, owner_id)
        session = self._calls.create_call(
            owner_id=owner_id, reference_id=reference_id or "", call_id=call_id)
        self._audit.append(EVENT_CALL_STARTED, session.call_id,
                           f"call started (reference: {reference_id or 'none'})",
                           actor="development", is_mock=True, timestamp=0.0)
        log.info("call started id=%s owner resolved reference=%s",
                 session.call_id, bool(reference_id))
        return session

    def process_call_chunk(
        self,
        call_id: str,
        chunk: Any,
        timestamp: float | None = None,
        owner_id: str | None = None,
    ):
        """Full live-chunk path: session -> B4 -> store -> publish."""
        session = self._calls.get_call(call_id, owner_id)
        if not session.is_active:
            raise ValidationError(f"call {session.call_id!r} is terminated.")
        # B2 must tag chunks with this call's ID; anything else is a
        # misrouted chunk and must not merge into another call's state.
        if isinstance(chunk, dict):
            chunk_session = chunk.get("session_id")
        else:
            chunk_session = getattr(chunk, "session_id", None)
        if chunk_session is not None and chunk_session != session.call_id:
            raise ValidationError(
                f"chunk session {chunk_session!r} does not belong to call "
                f"{session.call_id!r}.")
        result = self._b4.process_chunk(
            chunk,
            owner_id=session.owner_id,
            reference_id=session.reference_id or None,
            timestamp=timestamp,
        )
        # Deterministic order: store -> evidence -> alert -> audit -> publish.
        # Domain errors propagate; no fake success is ever fabricated.
        self._calls.update_latest(
            session.call_id, result.risk_update, result.assessment, session.owner_id)
        chunk_time = float(result.risk_update["timestamp"])
        records = self._evidence.add_all(build_evidence_for(
            result.signals, result.assessment, chunk_time))
        alert = self._alerts.create_if_new(result.assessment, chunk_time)
        self._audit.append(EVENT_RISK_UPDATE, session.call_id,
                           summarize_assessment(result.assessment),
                           actor="system", is_mock=result.assessment.is_mock,
                           timestamp=chunk_time)
        if records:
            self._audit.append(EVENT_EVIDENCE_CREATED, session.call_id,
                               f"{len(records)} evidence record(s) created",
                               actor="system", is_mock=result.assessment.is_mock,
                               timestamp=chunk_time)
        if alert is not None:
            self._audit.append(EVENT_ALERT_CREATED, session.call_id,
                               f"alert {alert.alert_id} ({alert.risk_level})",
                               actor="system", is_mock=alert.is_mock,
                               timestamp=chunk_time)
        self._ws.broadcast_risk_update(result.risk_update)
        if alert is not None:
            self._ws.publish_to_call(session.call_id, {
                "type": "security_alert",
                "callId": session.call_id,
                "alert_id": alert.alert_id,
                "risk": alert.risk,
                "risk_level": alert.risk_level,
                "title": alert.title,
                "is_mock": alert.is_mock,
                "timestamp": alert.timestamp,
            })
        return result

    def terminate_call(self, call_id: str, owner_id: str | None = None) -> CallSession:
        session = self._calls.terminate_call(call_id, owner_id)
        latest = session.latest_risk_update or {}
        timestamp = latest.get("timestamp", 0.0) or 0.0
        self._audit.append(EVENT_CALL_TERMINATED, session.call_id,
                           "call terminated (session tracking ended)",
                           actor="development", is_mock=True, timestamp=timestamp)
        return session

    def acknowledge_alert(self, alert_id: str,
                          owner_id: str | None = None):
        """Acknowledge an alert, enforcing call ownership when owner given.

        Missing alerts and wrong-owner alerts share one not-found error.
        """
        alert = self._alerts.get(alert_id)  # missing -> ValidationError
        try:
            self._calls.get_call(alert.call_id, owner_id)
        except ValidationError:
            raise ValidationError(f"alert {alert_id!r} not found.") from None
        acknowledged = self._alerts.acknowledge(alert_id)
        self._audit.append(EVENT_ALERT_ACKNOWLEDGED, acknowledged.call_id,
                           f"alert {alert_id} acknowledged",
                           actor="development", is_mock=acknowledged.is_mock,
                           timestamp=acknowledged.timestamp)
        return acknowledged

    # -- enrollment delegation (domain only) --

    def enroll_reference(self, reference_id: str, owner_id: str,
                         embedding: Any, embedder_version: str, is_mock: bool):
        return self._b4.enroll_reference(
            reference_id, owner_id, embedding, embedder_version, is_mock)

    def get_reference_metadata(self, reference_id: str, owner_id: str | None = None):
        """Owner-aware metadata lookup (wrong owner behaves as missing)."""
        if owner_id is not None:
            return self._profiles.get_metadata_for_owner(reference_id, owner_id)
        return self._profiles.get_metadata(reference_id)

    def delete_reference(self, reference_id: str) -> bool:
        """Delegate deletion to the profile store."""
        return self._profiles.delete_reference(reference_id)


# -- framework-free REST views: (status_code, body) --

def _not_found() -> tuple:
    return (404, {"detail": "call not found"})


def view_list_active(service: CallService, owner_id: str | None = None) -> tuple:
    return (200, [s.to_frontend_dict() for s in service.calls.list_active(owner_id)])


def view_get_call(service: CallService, call_id: str,
                  owner_id: str | None = None) -> tuple:
    try:
        session = service.calls.get_call(call_id, owner_id)
    except ValidationError:
        return _not_found()
    payload = session.to_frontend_dict()
    # Additive safe summaries (frontend ignores unknown keys).
    payload["alerts"] = [a.to_dict() for a in service.alerts.list_for_call(call_id)]
    payload["evidence_count"] = len(service.evidence.list_for_call(call_id))
    return (200, payload)


def view_get_evidence(service: CallService, call_id: str,
                      owner_id: str | None = None) -> tuple:
    """Structured evidence wrapper. Empty list when no records exist --
    never fabricated audio/spectrogram/voiceprint "proof"."""
    try:
        service.calls.get_call(call_id, owner_id)
    except ValidationError:
        return _not_found()
    return (200, {
        "call_id": call_id,
        "evidence": [r.to_dict() for r in service.evidence.list_for_call(call_id)],
    })


def view_list_alerts(service: CallService, call_id: str,
                     owner_id: str | None = None) -> tuple:
    """Additive alerts listing (no pre-existing contract to conflict with)."""
    try:
        service.calls.get_call(call_id, owner_id)
    except ValidationError:
        return _not_found()
    return (200, {
        "call_id": call_id,
        "alerts": [a.to_dict() for a in service.alerts.list_for_call(call_id)],
    })


def view_acknowledge_alert(service: CallService, alert_id: str,
                           owner_id: str | None = None) -> tuple:
    """Development-only acknowledgement (no auth yet); owner-blind 404."""
    try:
        alert = service.acknowledge_alert(alert_id, owner_id)
    except ValidationError:
        return (404, {"detail": "alert not found"})
    return (200, alert.to_dict())


def view_get_history(service: CallService, owner_id: str | None = None) -> tuple:
    return (200, [s.to_frontend_dict() for s in service.calls.list_history(owner_id)])


def view_terminate(service: CallService, call_id: str,
                   owner_id: str | None = None) -> tuple:
    try:
        session = service.terminate_call(call_id, owner_id)
    except ValidationError:
        return _not_found()
    return (200, session.to_frontend_dict())


def view_create_call(service: CallService, owner_id: str,
                     reference_id: str = "", call_id: str | None = None) -> tuple:
    """Development-only creation endpoint helper (no auth yet)."""
    try:
        session = service.start_call(owner_id, reference_id, call_id)
    except ValidationError as exc:
        return (400, {"detail": str(exc)})
    return (200, session.to_frontend_dict())


def view_ingest_chunk(service: CallService, call_id: str,
                      payload: Any, owner_id: str | None = None) -> tuple:
    """Live-driver ingest: one B2-packaged chunk dict through the full
    B3+B4 path (detection, risk, evidence, alert, audit, publish).

    The payload must be the B2 ``ProcessedSpeechChunk`` wire form
    (``from_dict``-compatible); the call must exist and be active.
    Unknown calls -> 404, terminated/malformed/misrouted chunks -> 400.
    Storage/model failures propagate to the adapter (500), unchanged.
    """
    if not isinstance(payload, dict):
        return (400, {"detail": "chunk payload must be a JSON object"})
    try:
        service.calls.get_call(call_id, owner_id)
    except ValidationError:
        return _not_found()
    try:
        result = service.process_call_chunk(call_id, payload, owner_id=owner_id)
    except ValidationError as exc:
        return (400, {"detail": str(exc)})
    return (200, {
        "ok": True,
        "call_id": call_id,
        "chunk_id": result.assessment.chunk_id,
        "risk_update": result.risk_update,
    })


def view_system_status(service: CallService) -> tuple:
    """Development-safe status with real B3 provenance and honest flags."""
    from backend.detector import get_detector
    from backend.embeddings import get_embedding_service

    from backend.config import get_settings

    detector = get_detector()
    embedder = get_embedding_service()
    mock = detector.is_mock or embedder.is_mock
    settings = get_settings()
    return (200, {
        "status": "ok",
        "backend": "VoiceGuard",
        "b3_detector_version": detector.model_version,
        "b3_embedder_version": embedder.model_version,
        "b3_is_mock": mock,
        "b4_is_mock": mock,  # B4 outputs derive from B3 mock inputs
        "active_calls": len(service.calls.list_active()),
        "transport": "development",
        "database": "in_memory" if settings.storage_backend == "memory" else "sqlite",
        "authentication": "not_configured" if settings.auth_mode == "disabled"
                          else settings.auth_mode,
        "environment": settings.env,
        "storage_backend": settings.storage_backend,
    })
