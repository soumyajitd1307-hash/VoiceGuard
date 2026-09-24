"""Backend 1 — live B1 -> B2 -> B3 -> B4 pipeline driver (Prompt 5).

Runtime orchestrator only: it moves REAL audio bytes from the Backend 1
ingest buffer through the EXISTING Backend 2 / Backend 3 / Backend 4
stages while a call is active. It contains no detection math, no risk
math, and no storage logic of its own.

Per active ``session_id`` one asyncio worker loops::

    B2 extract 1.0 s window (consumes bytes: at-most-once cursor)
      -> B2 preprocess + VAD + package (existing backend2 modules)
      -> silence windows are consumed and counted, never sent onward
      -> speech windows POSTed to B4 ``POST /api/v1/calls/{id}/chunks``
         (existing ``process_call_chunk`` path: B3 + B4, same process
         boundary crossed by HTTP only because B1 and B4 are separate
         uvicorn processes with separate memory)

Identity: ``session_id`` is used verbatim as B2 session, B3 session and
B4 call id. Chunk ids (``c00000`` …) are per-session monotonic window
counters; timestamps are call-relative audio-clock seconds
(``window_index``), never wall-clock processing time.

Backpressure: pull-based, no queues. A worker extracts at most one
window per iteration and idles when fewer than 32000 bytes are buffered.
At most ``MAX_WORKERS`` concurrent sessions; CPU/HTTP work runs in
``asyncio.to_thread`` so the B1 WebSocket receive loop never stalls.

Lifecycle: a worker starts on the session's first audio frame, stops
when the B4 call is no longer ACTIVE (polled), when the B1 socket
disconnects (bounded flush of full windows first), or on server
shutdown. One session's failure never touches other sessions.

Config (env, all optional):
    B4_BASE_URL      Backend 4 API base (default http://localhost:8000/api/v1)
    P5_POLL_S        B4 status poll interval (default 5.0)
    P5_IDLE_S        idle sleep when no full window (default 0.1)
    P5_HTTP_TIMEOUT  B4 HTTP timeout seconds (default 10)
    P5_MAX_WORKERS   concurrent session cap (default 32)
    P5_MAX_FLUSH     full windows flushed on disconnect (default 3)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request

from backend2.buffer import SessionBufferManager
from backend2.packaging import build_processed_speech_chunk
from backend2.preprocessing import extract_audio_window
from backend2.vad import compute_vad

logger = logging.getLogger("backend1.pipeline")

WINDOW_S = 1.0
WINDOW_BYTES = 32000  # 1.0 s of 16 kHz mono Int16 PCM

B4_BASE_URL = os.getenv("B4_BASE_URL", "http://localhost:8000/api/v1")
STATUS_POLL_S = float(os.getenv("P5_POLL_S", "5.0"))
IDLE_SLEEP_S = float(os.getenv("P5_IDLE_S", "0.1"))
HTTP_TIMEOUT_S = float(os.getenv("P5_HTTP_TIMEOUT", "10"))
MAX_WORKERS = int(os.getenv("P5_MAX_WORKERS", "32"))
MAX_FLUSH_WINDOWS = int(os.getenv("P5_MAX_FLUSH", "3"))
# Unknown-call respawn cooloff: a session B4 does not know must not trigger
# a status GET on every audio frame. Transport failures (None) never set
# this — only definitive unknown/inactive verdicts do.
UNKNOWN_COOLOFF_S = float(os.getenv("P5_UNKNOWN_COOLOFF_S", "30.0"))
MAX_COOLOFF_ENTRIES = 1000


class DriverError(Exception):
    """B4 transport failure (distinct from audio/validation issues)."""


def _b4_get_status(base_url: str, call_id: str) -> str | None:
    """Return the B4 call status, "UNKNOWN" for missing calls, or None on
    transport failure (B4 down -> caller keeps the worker alive)."""
    url = f"{base_url}/calls/{call_id}"
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return "UNKNOWN"
        return None
    except Exception:  # noqa: BLE001 - timeouts/refused: stay alive, retry later
        return None
    if not isinstance(body, dict):
        return None
    status = body.get("status")
    return status if isinstance(status, str) else None


def _b4_post_chunk(base_url: str, call_id: str, payload: dict) -> dict:
    """POST one B2-packaged chunk dict; return the parsed risk_update.

    Raises DriverError on any transport/HTTP failure (message carries
    call_id context; never audio bytes).
    """
    url = f"{base_url}/calls/{call_id}/chunks"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")[:200]
        except Exception:  # noqa: BLE001 - best effort detail
            detail = ""
        raise DriverError(f"call_id={call_id} B4 chunk POST HTTP {exc.code} {detail}")
    except Exception as exc:  # noqa: BLE001 - timeouts/refused
        raise DriverError(f"call_id={call_id} B4 chunk POST failed: {exc}")
    if not isinstance(body, dict) or not body.get("ok"):
        raise DriverError(f"call_id={call_id} B4 chunk POST bad response")
    update = body.get("risk_update")
    if not isinstance(update, dict):
        raise DriverError(f"call_id={call_id} B4 response carried no risk_update")
    return update


class SessionWorker:
    """Continuous per-session drain: B1 buffer -> B2 -> B3 -> B4."""

    def __init__(
        self,
        session_id: str,
        buffer_manager: SessionBufferManager,
        base_url: str = B4_BASE_URL,
    ) -> None:
        self.session_id = session_id
        self.buffer_manager = buffer_manager
        self.base_url = base_url
        self.task: asyncio.Task | None = None
        self.running = False
        self.windows_extracted = 0
        self.chunks_posted = 0
        self.silence_skipped = 0
        self.errors = 0

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "running": self.running,
            "windows_extracted": self.windows_extracted,
            "chunks_posted": self.chunks_posted,
            "silence_skipped": self.silence_skipped,
            "errors": self.errors,
            "buffered_bytes": self.buffer_manager.get_size(self.session_id),
        }

    def process_window_sync(self, window) -> str:
        """One extracted window through B2 package + B4 POST.

        Returns "posted" or "skipped" (silence). Raises on failure;
        the cursor has already advanced (at-most-once: a failed window
        is dropped and counted, never retried, so B4 can never see a
        duplicate of it).
        """
        vad = compute_vad(window.samples, window.sample_rate)
        index = self.windows_extracted
        chunk_id = f"c{index:05d}"
        packaged = build_processed_speech_chunk(
            window,
            vad,
            chunk_id,
            timestamp_s=float(index),
            language=None,  # passthrough preserved; no detector in this milestone
            validate=True,
        )
        self.windows_extracted += 1
        if not packaged.is_speech_ready:
            self.silence_skipped += 1
            logger.debug(
                "pipeline silence: call_id=%s chunk_id=%s ratio=%s",
                self.session_id,
                chunk_id,
                vad.speech_ratio,
            )
            return "skipped"
        payload = packaged.to_dict()
        update = _b4_post_chunk(self.base_url, self.session_id, payload)
        self.chunks_posted += 1
        logger.info(
            "pipeline posted: call_id=%s chunk_id=%s risk=%s ts=%s",
            self.session_id,
            chunk_id,
            update.get("risk"),
            update.get("timestamp"),
        )
        return "posted"

    async def drain_once(self) -> str:
        """Extract at most one window and process it. Test seam.

        Returns "posted" | "skipped" | "idle" (no full window buffered).
        """
        window = extract_audio_window(
            self.buffer_manager, self.session_id, WINDOW_S
        )
        if window is None:
            return "idle"
        try:
            return await asyncio.to_thread(self.process_window_sync, window)
        except Exception as exc:  # noqa: BLE001 - isolate per-window failures
            self.errors += 1
            logger.warning(
                "pipeline window failed: call_id=%s error=%s",
                self.session_id,
                exc,
            )
            return "error"

    async def check_active(self) -> bool:
        """True while B4 reports this call ACTIVE ( polled, in a thread)."""
        status = await asyncio.to_thread(_b4_get_status, self.base_url, self.session_id)
        return status == "ACTIVE"

    async def run(self) -> None:
        """Main loop: poll lifecycle, drain windows, isolate errors.

        Transport failure (B4 unreachable) pauses draining and keeps
        polling: buffered audio waits (bounded by the session cap) instead
        of being burned through failing POSTs, so a B4 restart recovers
        the session instead of stalling it forever.
        """
        self.running = True
        logger.info("pipeline started: call_id=%s", self.session_id)
        try:
            status = await asyncio.to_thread(
                _b4_get_status, self.base_url, self.session_id
            )
            if status is None:
                logger.info(
                    "pipeline waiting (B4 unreachable): call_id=%s",
                    self.session_id,
                )
            elif status != "ACTIVE":
                _note_unknown(self.session_id)
                logger.info(
                    "pipeline stopped (unknown/inactive call): call_id=%s",
                    self.session_id,
                )
                return
            loop = asyncio.get_running_loop()
            last_poll = loop.time()
            b4_reachable = status == "ACTIVE"
            while self.running:
                if loop.time() - last_poll >= STATUS_POLL_S:
                    last_poll = loop.time()
                    status = await asyncio.to_thread(
                        _b4_get_status, self.base_url, self.session_id
                    )
                    if status is None:
                        if b4_reachable:
                            logger.info(
                                "pipeline waiting (B4 unreachable): call_id=%s",
                                self.session_id,
                            )
                        b4_reachable = False
                    elif status != "ACTIVE":
                        _note_unknown(self.session_id)
                        logger.info(
                            "pipeline stopped (call no longer active): call_id=%s",
                            self.session_id,
                        )
                        return
                    else:
                        b4_reachable = True
                if not b4_reachable:
                    # B4 down: hold buffered audio (bounded) instead of
                    # burning it through failing POSTs.
                    await asyncio.sleep(STATUS_POLL_S)
                    continue
                outcome = await self.drain_once()
                if outcome == "idle":
                    await asyncio.sleep(IDLE_SLEEP_S)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - worker must never kill the server
            self.errors += 1
            logger.exception("pipeline fatal: call_id=%s", self.session_id)
        finally:
            self.running = False
            logger.info(
                "pipeline stopped: call_id=%s extracted=%d posted=%d skipped=%d errors=%d",
                self.session_id,
                self.windows_extracted,
                self.chunks_posted,
                self.silence_skipped,
                self.errors,
            )

    async def stop(self, flush: bool = True) -> None:
        """Stop the loop; optionally flush bounded full windows first."""
        self.running = False
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - teardown never raises
                logger.warning(
                    "pipeline stop join failed: call_id=%s", self.session_id
                )
            self.task = None
        if flush:
            await self.flush_full_windows(MAX_FLUSH_WINDOWS)

    async def flush_full_windows(self, max_windows: int) -> int:
        """Process up to max_windows complete buffered windows once each."""
        flushed = 0
        try:
            for _ in range(max(0, max_windows)):
                window = extract_audio_window(
                    self.buffer_manager, self.session_id, WINDOW_S
                )
                if window is None:
                    break
                try:
                    await asyncio.to_thread(self.process_window_sync, window)
                    flushed += 1
                except Exception as exc:  # noqa: BLE001 - bounded best effort
                    self.errors += 1
                    logger.warning(
                        "pipeline flush window failed: call_id=%s error=%s",
                        self.session_id,
                        exc,
                    )
                    break
        except Exception:  # noqa: BLE001 - flush never raises
            logger.warning("pipeline flush failed: call_id=%s", self.session_id)
        if flushed:
            logger.info(
                "pipeline flushed: call_id=%s windows=%d", self.session_id, flushed
            )
        return flushed


_workers: dict[str, SessionWorker] = {}

# Sessions with a definitive unknown/inactive verdict: suppress worker
# respawns until the cooloff expires, so garbage session ids streaming
# audio cannot turn into a per-frame B4 status GET hot loop. Transport
# failures never land here (those workers stay alive and retry).
_unknown_cooloff: dict[str, float] = {}


def _note_unknown(session_id: str) -> None:
    """Record a definitive unknown/inactive verdict for respawn gating."""
    if len(_unknown_cooloff) >= MAX_COOLOFF_ENTRIES:
        now = time.monotonic()
        for sid in [s for s, until in _unknown_cooloff.items() if until <= now]:
            del _unknown_cooloff[sid]
        if len(_unknown_cooloff) >= MAX_COOLOFF_ENTRIES:
            _unknown_cooloff.clear()
    _unknown_cooloff[session_id] = time.monotonic() + UNKNOWN_COOLOFF_S


def _in_cooloff(session_id: str) -> bool:
    until = _unknown_cooloff.get(session_id)
    if until is None:
        return False
    if until <= time.monotonic():
        _unknown_cooloff.pop(session_id, None)
        return False
    return True


def get_worker(session_id: str) -> SessionWorker | None:
    return _workers.get(session_id)


def worker_count() -> int:
    return len(_workers)


def ensure_worker(
    session_id: str,
    buffer_manager: SessionBufferManager,
    base_url: str = B4_BASE_URL,
) -> SessionWorker | None:
    """Start (idempotently) the pipeline worker for a session.

    Returns None when the session cap is reached (audio still buffers;
    B1 ingestion is unaffected).
    """
    existing = _workers.get(session_id)
    if existing is not None and (existing.running or existing.task is not None):
        return existing
    if _in_cooloff(session_id):
        # Definitive unknown/inactive verdict still fresh: don't respawn
        # (and don't hit B4) until it expires. Audio keeps buffering.
        logger.debug(
            "pipeline respawn suppressed (cooloff): session %s", session_id
        )
        return None
    if len(_workers) >= MAX_WORKERS:
        logger.warning(
            "pipeline worker cap reached (%d): session %s not started",
            MAX_WORKERS,
            session_id,
        )
        return None
    worker = SessionWorker(session_id, buffer_manager, base_url)
    worker.task = asyncio.get_running_loop().create_task(
        worker.run(), name=f"pipeline-{session_id}"
    )

    def _reap(task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 - already logged in run(); don't crash loop
            logger.warning("pipeline task ended with error: session %s", session_id)
        _workers.pop(session_id, None)

    worker.task.add_done_callback(_reap)
    _workers[session_id] = worker
    return worker


async def stop_session(session_id: str, flush: bool = True) -> None:
    """Stop a session worker (flush bounded full windows); never raises."""
    worker = _workers.pop(session_id, None)
    # A disconnect is a fresh start for lifecycle purposes: a later
    # reconnect with the same id must re-verify against B4 immediately.
    _unknown_cooloff.pop(session_id, None)
    if worker is None:
        return
    try:
        await worker.stop(flush=flush)
    except Exception:  # noqa: BLE001 - teardown never raises
        logger.warning("pipeline session stop failed: %s", session_id)


async def shutdown_all() -> None:
    """Cancel all workers without flushing (server is going down)."""
    sessions = list(_workers)
    for session_id in sessions:
        await stop_session(session_id, flush=False)


def snapshot_all() -> dict[str, dict]:
    return {sid: w.snapshot() for sid, w in _workers.items()}
