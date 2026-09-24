"""VoiceGuard unified cloud runtime — ONE process serving every backend.

Mounts the existing, unchanged endpoint contracts side by side:

    REST  /ml/v1/*    (Backend 3 detection adapter — ``backend.api``)
    REST  /api/v1/*   (Backend 4 calls/alerts/evidence/system)
    WS    /ws/calls   (Backend 4 per-call RiskUpdate stream)
    WS    /ws/signal  (Backend 1 WebRTC signaling — ``backend1.app``)
    WS    /ws/audio   (Backend 1 audio ingest)
    GET   /health     (liveness probe for the hosting platform)

Backend 2 (buffer/preprocess/VAD/package) and Backend 3 (detection) stay
in-process Python calls exactly as in local development. The only hop that
was ever HTTP — Backend 1 pipeline driver -> Backend 4 — becomes loopback
HTTP to this same process: ``B4_BASE_URL`` defaults to
``http://127.0.0.1:<PORT>/api/v1`` unless explicitly overridden, so no
localhost assumption escapes and no code path changes shape.

Run locally (production simulation):
    PORT=8000 python -m uvicorn backend.cloud:app --host 0.0.0.0 --port 8000

Run on Render (Docker, see Dockerfile / render.yaml):
    uvicorn backend.cloud:app --host 0.0.0.0 --port $PORT --workers 1

Exactly ONE worker: all call/evidence/alert/audio state is in-memory, so
more workers would split (not share) state and break the demo.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager


def resolve_port(raw: str | None = None) -> int:
    """Port this process serves. Render injects ``PORT``; default 8000."""
    try:
        return int((raw if raw is not None else os.getenv("PORT", "8000")).strip())
    except (TypeError, ValueError):
        return 8000


def resolve_b4_base_url(port: int | None = None) -> str:
    """Base URL the pipeline driver uses to reach Backend 4.

    Explicit ``B4_BASE_URL`` wins (split-process development). Otherwise the
    driver talks to this same process over loopback — no public hostname,
    no localhost leak, no second process to run.
    """
    explicit = (os.getenv("B4_BASE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    return f"http://127.0.0.1:{port if port is not None else resolve_port()}/api/v1"


# Must run before backend1.pipeline_driver is imported: the module reads
# B4_BASE_URL once at import time into worker defaults.
os.environ.setdefault("B4_BASE_URL", resolve_b4_base_url())

from fastapi import FastAPI  # noqa: E402

from backend.api import api_router  # noqa: E402
from backend.api import router as ml_router  # noqa: E402
from backend.api import ws_router  # noqa: E402
from backend.cors import add_cors_middleware  # noqa: E402
from backend1 import pipeline_driver  # noqa: E402
from backend1.app import b1_router  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await pipeline_driver.shutdown_all()


def create_app() -> FastAPI:
    """Build the unified application (factory kept for tests)."""
    app = FastAPI(title="VoiceGuard Cloud — Unified Backend", lifespan=lifespan)
    add_cors_middleware(app)
    app.include_router(ml_router)
    app.include_router(api_router)
    app.include_router(ws_router)
    # Backend 1 routes (/health, /ws/signal, /ws/audio) — identical paths.
    app.include_router(b1_router)
    return app


app = create_app()
