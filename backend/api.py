"""Optional HTTP adapter for Backend 3.

Mount this router in the host FastAPI app (Backend 2 or standalone)::

    from fastapi import FastAPI
    from backend.api import router as ml_router
    app = FastAPI()
    app.include_router(ml_router)

Endpoint: POST /ml/v1/detect  (JSON body)

This module imports fastapi lazily so the core service has no web dependency.
"""
from __future__ import annotations

try:
    from typing import Any

    from fastapi import APIRouter, HTTPException, Request, WebSocket
    from pydantic import BaseModel, Field

    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - fastapi is optional
    Any = None  # type: ignore[assignment]
    APIRouter = HTTPException = Request = WebSocket = None  # type: ignore[assignment]
    BaseModel = Field = None  # type: ignore[assignment]
    _FASTAPI_AVAILABLE = False

from backend.schemas import ModelError, ValidationError
from backend.service import SyntheticVoiceDetectionService

router = APIRouter(prefix="/ml/v1", tags=["ml-synthetic-voice"]) if _FASTAPI_AVAILABLE else None
_service = SyntheticVoiceDetectionService()

# Shared Part 5 application service (framework-free; safe to build always).
from backend.auth import (
    AuthError,
    authenticate,
    request_owner,
    require_production_ready,
)
from backend.call_service import CallService  # noqa: E402
from backend.call_service import (  # noqa: E402
    view_acknowledge_alert,
    view_create_call,
    view_get_call,
    view_get_evidence,
    view_get_history,
    view_list_active,
    view_list_alerts,
    view_system_status,
    view_terminate,
)
from backend.config import get_settings  # noqa: E402
from backend.storage import StorageError, open_storage  # noqa: E402
from backend.ws_manager import WsConnectionManager  # noqa: E402

_settings = get_settings()
require_production_ready(_settings)  # fail closed in production misconfig


def _build_call_service() -> CallService:
    from backend.b4_service import Backend4Service

    bundle = open_storage(_settings.storage_backend, _settings.storage_path)
    return CallService(
        call_store=bundle.calls,
        profile_store=bundle.profiles,
        b4_service=Backend4Service(profile_store=bundle.profiles),
        ws_manager=WsConnectionManager(),
        alert_store=bundle.alerts,
        evidence_store=bundle.evidence,
        audit_store=bundle.audit,
    )


_call_service: CallService | None = None


def get_call_service() -> CallService:
    """Process-wide application service (storage-wired, lazily built)."""
    global _call_service
    if _call_service is None:
        _call_service = _build_call_service()
    return _call_service


def reset_api_service() -> None:
    """Test helper: drop the cached service so tests can rebuild it."""
    global _call_service
    _call_service = None


if _FASTAPI_AVAILABLE:

    class DetectBody(BaseModel):
        audio_base64: str = Field(description="Base64 of 16-bit LE PCM mono speech.")
        sample_rate: int = Field(examples=[16000])
        session_id: str
        chunk_id: str

    @router.post("/detect")
    def detect(body: DetectBody) -> dict:
        try:
            result = _service.detect(
                audio=body.audio_base64,
                sample_rate=body.sample_rate,
                session_id=body.session_id,
                chunk_id=body.chunk_id,
                audio_encoding="pcm16_base64",
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ModelError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return result.to_dict()

    @router.get("/health")
    def health() -> dict:
        model = _service.model
        return {"status": "ok", "model_version": model.version, "is_mock": model.is_mock}

    # -- Part 5: frontend-compatible B4 routes (development transport) --

    api_router = APIRouter(prefix="/api/v1", tags=["voiceguard-b4"])

    def _as_response(make_result) -> dict | list | None:
        try:
            status, body = make_result()
        except StorageError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if status == 404:
            raise HTTPException(status_code=404, detail=body.get("detail"))
        if status == 400:
            raise HTTPException(status_code=400, detail=body.get("detail"))
        return body

    def _principal(request) -> Any | None:
        """Authenticate the request (None in disabled dev mode).

        Raises HTTP 401 when credentials are missing/invalid/misconfigured.
        """
        try:
            return authenticate(dict(request.headers), _settings)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    def _owner(request) -> str | None:
        """Authoritative owner: principal wins; client values never trusted."""
        principal = _principal(request)
        return request_owner(principal)

    class CreateCallBody(BaseModel):
        owner_id: str = ""  # ignored whenever a principal exists (anti-spoof)
        reference_id: str = ""
        call_id: str | None = None

    @api_router.get("/calls/active")
    def get_active_calls(request: Request) -> list:
        return _as_response(lambda: view_list_active(get_call_service(), _owner(request)))

    @api_router.get("/calls/history")
    def get_call_history(request: Request) -> list:
        return _as_response(lambda: view_get_history(get_call_service(), _owner(request)))

    @api_router.get("/calls/{call_id}")
    def get_call(call_id: str, request: Request) -> dict:
        return _as_response(lambda: view_get_call(get_call_service(), call_id, _owner(request)))

    @api_router.get("/calls/{call_id}/evidence")
    def get_evidence(call_id: str, request: Request):
        return _as_response(lambda: view_get_evidence(get_call_service(), call_id, _owner(request)))

    @api_router.get("/calls/{call_id}/alerts")
    def get_alerts(call_id: str, request: Request):
        return _as_response(lambda: view_list_alerts(get_call_service(), call_id, _owner(request)))

    @api_router.post("/alerts/{alert_id}/acknowledge")
    def acknowledge_alert(alert_id: str, request: Request):
        return _as_response(
            lambda: view_acknowledge_alert(get_call_service(), alert_id, _owner(request)))

    @api_router.post("/calls/{call_id}/terminate")
    def terminate_call(call_id: str, request: Request) -> dict:
        return _as_response(lambda: view_terminate(get_call_service(), call_id, _owner(request)))

    @api_router.post("/calls")
    def create_call(body: CreateCallBody, request: Request) -> dict:
        # Body owner_id is ignored under authentication (anti-spoofing).
        owner = _owner(request) or body.owner_id
        return _as_response(lambda: view_create_call(
            get_call_service(), owner, body.reference_id, body.call_id))

    @api_router.get("/system/status")
    def get_system_status() -> dict:
        return _as_response(view_system_status(get_call_service()))

    ws_router = APIRouter(tags=["voiceguard-ws"])

    @ws_router.websocket("/ws/calls")
    async def ws_calls(websocket: WebSocket, call_id: str = ""):
        """One socket per call (``?call_id=...``); streams RiskUpdate JSON.

        Ownership is verified before subscribing: unauthenticated or
        foreign calls close with 4401 (indistinguishable by design).
        """
        try:
            principal = authenticate(dict(websocket.headers), _settings)
        except AuthError:
            await websocket.close(code=4401)
            return
        owner = request_owner(principal)
        service = get_call_service()
        try:
            service.calls.get_call(call_id, owner)
        except (ValidationError, StorageError):
            await websocket.close(code=4401)
            return
        from backend.ws_manager import websocket_endpoint

        await websocket_endpoint(websocket, call_id, service.ws)

else:  # pragma: no cover - import-safe without fastapi
    api_router = None
    ws_router = None
