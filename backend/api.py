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
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover - fastapi is optional
    raise ImportError("Install fastapi + pydantic to use backend.api (pip install fastapi pydantic).")

from backend.schemas import ModelError, ValidationError
from backend.service import SyntheticVoiceDetectionService

router = APIRouter(prefix="/ml/v1", tags=["ml-synthetic-voice"])
_service = SyntheticVoiceDetectionService()


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
