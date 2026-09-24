"""VoiceGuard Backend host application (Backend 3 ML + Backend 4 API/WS).

This module is a thin launcher: it creates the single FastAPI application
and mounts the routers already implemented in ``backend.api``. It contains
no business logic and duplicates no endpoints.

Serves (development defaults):
    REST  /ml/v1/*    (Backend 3 detection adapter)
    REST  /api/v1/*   (Backend 4 calls/alerts/evidence/system)
    WS    /ws/calls   (Backend 4 per-call RiskUpdate stream)

Run (dev):
    python -m uvicorn backend.app:app --reload --port 8000
"""

from fastapi import FastAPI

from backend.api import api_router
from backend.api import router as ml_router
from backend.api import ws_router
from backend.cors import add_cors_middleware

app = FastAPI(title="VoiceGuard Backend")
add_cors_middleware(app)

app.include_router(ml_router)
app.include_router(api_router)
app.include_router(ws_router)
