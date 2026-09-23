# VoiceGuard Production Readiness (Part 10)

## 0. The one honest sentence

**Production ML performance has not been established.** No production-trained
weights and no representative real dataset have been evaluated. Everything
below describes *engineering* readiness (integration, contracts, hardening);
ML validation remains at Parts 8 (adapters execute) and 9 (framework ready).

## 1. Architecture

```
Frontend (React 19 + Vite, demo-driven, self-contained)
    ↕  REST /api/v1/*  +  WS /ws/calls  (backend serves; frontend not yet wired)
Authentication (disabled | token-dev | strict-fail-closed)
    ↓
CallService — sessions, orchestration, views
    ↓
Backend4Service — Backend3Pipeline → RiskFusionEngine → RiskUpdate adapter
    ↓
Backend3 — mock detector/embedder (default) or real adapters (explicit)
    ↓
Alert / Evidence / Audit stores (memory default, SQLite available)
```

## 2. Startup / configuration

Backend entry: import `backend.api` (`api_router`, `ws_router`,
`get_call_service()`); mount routers in a FastAPI app. No startup command
ships yet — the next step is a small `uvicorn backend.app:app` module,
not a redesign.

| Variable | Default | Production rule |
|---|---|---|
| `VG_ENV` | `development` | `production` fails closed unless below hold |
| `VG_STORAGE_BACKEND` | `memory` | `sqlite` required in production |
| `VG_STORAGE_PATH` | `""` | required file path in production |
| `VG_AUTH_MODE` | `disabled` | `token` (dev) or real IdP; `strict` rejects all until an IdP exists |
| `VG_AUTH_TOKEN` / `VG_DEV_OWNER` | `""` | required for `token` mode |
| `VG_MODEL_NAME` / `VG_EMBEDDER_NAME` | `mock` | `real` requires `VG_DETECTOR_MODEL` / `VG_EMBEDDER_MODEL` paths, else fail-fast |
| `VG_MODEL_VERSION` / `VG_EMBEDDER_VERSION` | mock versions | must equal weights-file versions |
| `VG_SYNTHETIC_THRESHOLD` etc. | current values | unevaluated; do not tune by hand |

Frontend: `VITE_API_BASE_URL=http://localhost:8000/api/v1`,
`VITE_WS_URL=ws://localhost:8000/ws/calls` (nothing listens yet in this repo).

## 3. Authentication modes

- `disabled`: trusted-internal dev default; principal `None`; owner scoping
  still enforced when an owner is supplied explicitly.
- `token`: shared development/test token (`X-VoiceGuard-Token`,
  constant-time compare) asserting the configured `VG_DEV_OWNER`.
  Dev/test only — never production authentication.
- `strict`: rejects everything (401 / WS close 4401). Stays strict until a
  real identity provider is integrated. Never weaken it to make tests pass.

## 4. Storage modes

- `memory`: default; all current unit tests run here; restart loses state.
- `sqlite` (stdlib, WAL, parameterized SQL, per-op connections, RLock):
  calls (incl. bounded history + latest assessment), profiles (isolated
  vectors table), alerts (incl. cooldown + ack), evidence, ordered audit
  all survive restart. Misconfigured sqlite never falls back to memory.

## 5. Mock vs real models

Default `mock`/`mock` with `is_mock=true` end to end. `real` backends load
JSON weight files once per process (`is_mock=false` = real scoring path,
NOT validated recognition). Missing/mismatched weights fail loudly
(`ModelError`); silent mock fallback is forbidden and tested. Mixed
mock/real configurations are supported with per-signal provenance.

## 6. REST endpoints

`GET /calls/active|/calls/{id}|/calls/{id}/evidence|/calls/{id}/alerts|/calls/history|/system/status`,
`POST /calls|/calls/{id}/terminate|/alerts/{id}/acknowledge`, plus legacy
`POST /ml/v1/detect`, `GET /ml/v1/health`. Errors: 404 `{detail}` for
missing/foreign (indistinguishable), 400 malformed, 401 unauthenticated,
422 validation, 500 storage failure. Evidence returns
`{"call_id","evidence":[...]}` (empty, never fabricated); the frontend
`Evidence|null` type needs a future additive update before wiring.

## 7. WebSocket protocol

`/ws/calls?call_id=…`, one socket per call, ownership verified
pre-subscribe (4401 otherwise). Messages: `risk_update` (existing shape,
required keys always present) and `security_alert` (new additive type;
current frontend safely ignores unknown types). No embeddings, audio,
owners, or secrets on the wire — enforced by recursive guard.

## 8. Privacy boundaries

External payloads (REST/WS), logs, exceptions, and reprs never carry raw
audio, embeddings, `owner_id`, phone numbers, contacts, profile objects,
tokens, or secrets (recursive scan tests). Vectors live only in locked
stores / the isolated profiles table / transient inference; `owner_id`
lives only in server-side session/profile rows. Internal `CallSession`
reprs are never serialized.

## 9. Persistence behavior

Per-operation transactions with rollback; cross-store multi-step flows
(chunk processing) are ordered (store → evidence → alert → audit →
publish) but NOT atomic across stores — documented limitation. Failures
propagate, never fabricate success. History capped (`MAX_HISTORY`);
alerts bounded by 30s cooldown dedup; audit append-only.

## 10. Failure behavior

Malformed input → 400/422; unknown/foreign resource → 404; unauthenticated
→ 401; storage failure → 500; model failure → `ModelError` (never mock
fallback, never stale output); terminated/misrouted chunks rejected;
service recreation over SQLite resumes cleanly. No silent
real→mock, persistent→memory, or authenticated→anonymous downgrades
anywhere (each explicitly tested).

## 11. Testing status

Backend: 579 tests green (68 new Part 10 integration/hardening tests),
1 pre-existing skip (real weights unavailable). Frontend: `tsc -b` +
`vite build` pass; `oxlint` 0 errors (1111 pre-existing style warnings
only). No frontend test runner exists in this repo.

## 12. Known limitations

1. No trained production weights; no representative dataset → no ML validation.
2. Fusion weights (0.6/0.4), bands, HIGH=70, cooldown 30s unevaluated.
3. No real auth provider (`strict` rejects all); token mode is dev-only.
4. In-memory default loses state; unbounded audit/evidence growth there.
5. No telephony/SIP integration; chunks arrive via internal API only.
6. Frontend not wired to backend (REST client dead code; demo simulator
   drives UI); `Evidence`/`SystemStatus` type alignment pending.
7. Cross-store operations are ordered, not atomic.
8. No rate limiting, TLS termination, or deployment target in-repo.

## 13. What remains before real production deployment

Trained + evaluated models (Parts 8C/8D, 9C/9D) → calibrated thresholds
adopted by explicit decision → real IdP → persistent ops (backups,
retention, rate limits, TLS, hosting) → frontend wiring + type alignment
→ load/security testing. Engineering integration is done; ML validation
and deployment are not.
