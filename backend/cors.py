"""Shared environment-aware CORS configuration for VoiceGuard FastAPI apps.

Used by the standalone dev apps (``backend.app``, ``backend1.app``) and the
unified cloud app (``backend.cloud``) so browser origins behave identically
everywhere. No credentials/cookies are used by the frontend, so
``allow_credentials`` stays False and origins are listed explicitly (never
``["*"]``).

Environment:
    CORS_ORIGINS  Optional comma-separated extra origins, e.g.
                  "https://staging.example.com". Merged with the built-ins.
    FRONTEND_ORIGIN Optional single origin (e.g. the Render dashboard value
                  for the GitHub Pages site). Merged with the built-ins.

Built-in origins (always allowed):
    - https://soumyajitd1307-hash.github.io  (production frontend)
    - http://localhost:5173                  (local Vite dev)
    - http://127.0.0.1:5173                 (local Vite dev, loopback)
"""
from __future__ import annotations

import os

PRODUCTION_FRONTEND_ORIGIN = "https://soumyajitd1307-hash.github.io"
LOCAL_DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")

ALLOW_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
ALLOW_HEADERS = ("Content-Type", "Authorization", "X-VoiceGuard-Token")


def get_allowed_origins() -> list[str]:
    """Build the CORS origin list from built-ins plus environment extras."""
    origins: list[str] = [PRODUCTION_FRONTEND_ORIGIN, *LOCAL_DEV_ORIGINS]
    single = (os.getenv("FRONTEND_ORIGIN") or "").strip()
    if single and single not in origins:
        origins.append(single)
    extra = (os.getenv("CORS_ORIGINS") or "").strip()
    for origin in (o.strip() for o in extra.split(",")):
        if origin and origin not in origins:
            origins.append(origin)
    return origins


def add_cors_middleware(app) -> None:
    """Attach CORSMiddleware with the shared policy. Idempotent per app."""
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_allowed_origins(),
        allow_credentials=False,
        allow_methods=list(ALLOW_METHODS),
        allow_headers=list(ALLOW_HEADERS),
    )
