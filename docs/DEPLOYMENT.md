# VoiceGuard Cloud Deployment Guide

One public backend for the live demo: GitHub Pages frontend talks to a
single Render web service that runs Backend 1–4 in one process. No laptop
runs Python during the demo; two different devices open the public URL and
make a real call.

> Status: repository is deployment-ready. The backend is **not** publicly
> deployed until the Render steps below are completed and verified.

## 1. Architecture

```
Internet
  |
  v
GitHub Pages frontend (static React build)
  |  HTTPS fetch + WSS sockets (CORS allow-listed)
  v
ONE Render web service (Docker, `backend.cloud:app`, 1 worker)
  |-- REST /ml/v1/*          Backend 3 detection adapter
  |-- REST /api/v1/*         Backend 4 calls / risk / evidence / alerts
  |-- WS   /ws/calls         Backend 4 per-call RiskUpdate stream (?call_id=)
  |-- WS   /ws/signal        Backend 1 WebRTC signaling (?call_id=&participant_id=)
  |-- WS   /ws/audio         Backend 1 audio ingest (?session_id=)
  |-- GET  /health           liveness probe (Render health check)
  +-- in-process: B2 buffer/preprocess/VAD/package, B3 detection,
      B4 stores; B1->B4 hop is loopback HTTP to self (127.0.0.1:$PORT)
```

Endpoint contracts are unchanged from local development; only the origin
moves from `localhost:8000/8001` to `https://<service>.onrender.com`.

## 2. Render configuration

Option A — Blueprint (recommended): this repo ships `render.yaml`
(runtime Docker, `Dockerfile`, health check `/health`). In Render:
New → Blueprint → select the repo → Apply.

Option B — manual: New → Web Service → this repo → Runtime: Docker,
Dockerfile Path: `./Dockerfile`, Health Check Path: `/health`,
add the environment variables from section 3, Deploy.

Build/start are defined by the Dockerfile:
`uvicorn backend.cloud:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers`.
Keep exactly **1 worker** (see section 10).

## 3. Environment variables

Backend service (Render dashboard → Environment):

| Variable | Required | Value |
|---|---|---|
| `PORT` | auto (Render) | injected by Render; code defaults to 8000 locally |
| `FRONTEND_ORIGIN` | yes | `https://soumyajitd1307-hash.github.io` |
| `VG_ENV` | no | leave `development` (see section 10) |
| `VG_STORAGE_BACKEND` | no | leave `memory` |
| `VG_AUTH_MODE` | no | leave `disabled` |
| `B4_BASE_URL` | no | leave unset → loopback self (`127.0.0.1:$PORT`) |
| `CORS_ORIGINS` | no | comma-separated extra origins if needed |

No secrets exist in this project; never commit `.env` files.

Frontend build (GitHub Actions variables — repo Settings → Secrets and
variables → Actions → **Variables**, so fork builds keep working):

| Variable | Example |
|---|---|
| `VITE_API_BASE_URL` | `https://<service>.onrender.com/api/v1` |
| `VITE_WS_URL` | `wss://<service>.onrender.com/ws/calls` |
| `VITE_AUDIO_WS_URL` | `wss://<service>.onrender.com/ws/audio` |
| `VITE_SIGNAL_WS_URL` | `wss://<service>.onrender.com/ws/signal` |

Unset variables fall back to localhost defaults, so local `npm run build`
is unaffected. (Empty strings also fall back — the services use `||`.)

## 4. Build command

Backend: Docker build (`pip install -r requirements.txt`; Python 3.12-slim).
Frontend: `npm run build` (`.github/workflows/deploy.yml` injects the four
`VITE_*` variables from Actions variables, then deploys `dist/` to Pages).

## 5. Start command

`uvicorn backend.cloud:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers`
(inside Docker; binds all interfaces, honors Render's `PORT`, supports HTTP
+ WebSocket, single worker, correct scheme behind Render's TLS proxy).

## 6. Health-check path

`GET /health` → `{"status": "ok"}` (Backend 1 liveness route, served by the
unified app). Deeper check: `GET /api/v1/system/status` (B4 status shape).
Render uses `/health` (`render.yaml` + Dockerfile notes).

## 7. WebSocket paths

| Path | Query | Direction |
|---|---|---|
| `/ws/signal` | `?call_id=<B4 id>&participant_id=<id>` | browser ↔ browser envelopes (SDP/ICE) |
| `/ws/audio` | `?session_id=<B4 id>` | browser → server binary PCM + `ack` |
| `/ws/calls` | `?call_id=<B4 id>` | server → browser `risk_update`; unknown id → clean `4401` close |

All use `wss://` in production. `call_id` propagation, participant ids, B4
call-id authority, real WebRTC/audio/risk behavior are unchanged — no
polling, no fake data (verified by `backend/tests/test_cloud_deploy.py`
live smoke + the Phase-12 chain simulation).

## 8. GitHub Pages configuration

Workflow `.github/workflows/deploy.yml` builds on push to `main` with the
`VITE_*` variables and publishes `dist/`. Base stays `./` (relative asset
URLs), which works under `https://soumyajitd1307-hash.github.io/VoiceGuard/`
with no config change. After setting the four Actions variables, push to
`main` (or re-run the workflow) so the live site picks up the Render origin.

## 9. Two-device test

1. Deploy backend on Render; confirm `https://<service>.onrender.com/health`.
2. Set the four Actions variables; re-run Deploy workflow; open the Pages URL
   on **two different devices**.
3. Device A: create/join a call (B4 id shown); Device B: join with that id.
4. Speak on either device → risk telemetry, evidence, and alerts accrue live
   on both; acknowledge an alert; either side leaves; history shows ENDED.
5. Failure honesty: with the backend asleep/down, the UI shows explicit
   error/empty states — never fabricated data.

## 10. What remains in-memory

Active calls, call history, evidence, alerts, audit trail, risk history,
audio buffers, signaling rooms, and pipeline workers are **all in-memory**.
A Render restart, redeploy, or free-tier sleep **wipes everything**; in-flight
calls drop and both devices must start a new call. This matches local
development behavior exactly (no database was introduced).

`VG_ENV=production` is deliberately **not** set: it fail-closes at import
(`require_production_ready` demands sqlite storage + non-disabled auth).
Token/strict auth would require frontend credential plumbing that does not
exist; for the hackathon demo the honest configuration is the documented
development-grade default above.

## 11. Limitations

* One worker only — do not raise `--workers` (state would split per worker).
* Render free tier sleeps after inactivity: first request/WS after sleep is
  slow (~1 min cold start); in-memory state is lost on sleep.
* B3 detection is the documented mock heuristic (`is_mock=true`); no TURN
  server (symmetric-NAT pairs may fail WebRTC); no authentication on the API.
* CORS allow-list is explicit (Pages origin + localhost dev); `allow_origins`
  never uses `"*"` with credentials.
