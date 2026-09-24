"""Backend 1 — Live Audio Transport / Audio Ingestion (Milestone 1 skeleton).

Scope for this milestone ONLY:
- Accept a WebSocket connection for live audio ingest.
- Accept arbitrary BINARY frames, log session_id + byte count.
- Reply with a per-connection sequence-number ACK per binary frame.

Explicitly NOT in scope yet: decoding, resampling, chunking,
rolling buffer, Backend 2 forwarding, ML, DB, auth.

Run (dev):
    uvicorn backend1.app:app --reload --port 8001
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from backend1 import pipeline_driver
from backend2.buffer import AudioBufferError, get_buffer_manager
from backend1.signaling import SignalingHub

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await pipeline_driver.shutdown_all()


app = FastAPI(title="VoiceGuard Backend 1 — Audio Ingestion", lifespan=lifespan)
buffer_manager = get_buffer_manager()
signal_hub = SignalingHub()

# Single binary frames larger than a whole session budget are never
# legitimate audio (a 250 ms frame is 8000 bytes); reject before buffering.
MAX_FRAME_BYTES = 1_048_576
MAX_SESSION_ID_LENGTH = 128


def validate_audio_frame(data: bytes) -> str | None:
    """Return a rejection reason for a malformed binary frame, else None.

    Pure (unit-testable): empty, odd-length (not Int16 PCM), and
    over-cap frames are refused so malformed bytes can never enter the
    B2 buffer or reach B3/B4. Existing valid sizes (any even length)
    are unaffected.
    """
    if len(data) == 0:
        return "empty frame"
    if len(data) % 2 != 0:
        return f"odd byte count ({len(data)} is not Int16 PCM)"
    if len(data) > MAX_FRAME_BYTES:
        return f"frame exceeds {MAX_FRAME_BYTES} byte cap"
    return None


@app.get("/health")
def health() -> dict:
    """Liveness probe for Backend 1."""
    return {"status": "ok"}


@app.websocket("/ws/signal")
async def ws_signal(websocket: WebSocket) -> None:
    """Two-person WebRTC signaling.

    ``/ws/signal?call_id=<CALL_ID>&participant_id=<PARTICIPANT_ID>``
    Relays SDP offer/answer and ICE JSON envelopes between the call's
    participants (see ``backend1.signaling``). No media flows here.
    """
    await signal_hub.handle(
        websocket,
        call_id=websocket.query_params.get("call_id", ""),
        participant_id=websocket.query_params.get("participant_id", ""),
    )


@app.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket) -> None:
    """Audio ingest endpoint: ``/ws/audio?session_id=<SESSION_ID>``."""
    await websocket.accept()

    raw_session_id = websocket.query_params.get("session_id", "unknown") or "unknown"
    session_id = raw_session_id.strip() or "unknown"
    if len(session_id) > MAX_SESSION_ID_LENGTH:
        logger.warning(
            "audio ws rejected: session_id exceeds %d chars", MAX_SESSION_ID_LENGTH
        )
        await websocket.close(code=4400)
        return
    seq = 0
    logger.info("audio ws connected: session_id=%s", session_id)

    try:
        while True:
            message = await websocket.receive()

            if "bytes" in message and message["bytes"] is not None:
                data: bytes = message["bytes"]
                invalid_reason = validate_audio_frame(data)
                if invalid_reason is not None:
                    # Reject safely: never buffer, never forward, never start
                    # a worker for garbage. The distinct ack type keeps the
                    # per-message sequence honest without faking acceptance
                    # (existing clients ignore non-"ack" frames).
                    logger.warning(
                        "audio invalid frame rejected: session_id=%s seq=%d bytes=%d reason=%s",
                        session_id,
                        seq,
                        len(data),
                        invalid_reason,
                    )
                    await websocket.send_json(
                        {"type": "ack_invalid", "seq": seq, "reason": invalid_reason}
                    )
                    seq += 1
                    continue
                logger.info(
                    "audio binary received: session_id=%s seq=%d bytes=%d",
                    session_id,
                    seq,
                    len(data),
                )
                try:
                    buffer_manager.append(session_id, data)
                except AudioBufferError as exc:
                    logger.warning(
                        "audio buffer append failed: session_id=%s seq=%d error=%s",
                        session_id,
                        seq,
                        exc,
                    )
                # (Re)start the live B1->B2->B3->B4 worker whenever none is
                # alive for this session: covers first frame, worker fatal
                # exits, and B4-restart recovery. Idempotent and capped, so
                # per-frame lookup is cheap and cannot duplicate workers.
                worker = pipeline_driver.get_worker(session_id)
                if worker is None or (not worker.running and worker.task is None):
                    pipeline_driver.ensure_worker(session_id, buffer_manager)
                await websocket.send_json({"type": "ack", "seq": seq})
                seq += 1
            elif "text" in message and message["text"] is not None:
                # Text/JSON frames are not audio; acknowledge safely, never crash.
                logger.info(
                    "audio ws non-binary frame ignored: session_id=%s text=%r",
                    session_id,
                    message["text"][:200],
                )
                await websocket.send_json({"type": "ack_ignored", "seq": seq})
            elif message.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        logger.info("audio ws disconnected: session_id=%s", session_id)
    except Exception:
        logger.exception("audio ws error: session_id=%s", session_id)
        try:
            await websocket.close()
        except Exception:
            pass
    finally:
        # Socket gone: stop the session worker (bounded flush of full
        # windows first). Never raises; ingestion stays unaffected.
        await pipeline_driver.stop_session(session_id)
        # Drop the session buffer so disconnected sessions cannot
        # accumulate toward the session cap. Buffered bytes were either
        # processed (extracted) or are stale partial windows — both safe
        # to discard now that no socket feeds this session.
        try:
            buffer_manager.remove_session(session_id)
        except Exception:
            logger.warning(
                "audio buffer cleanup failed: session_id=%s", session_id
            )
        logger.info(
            "audio ws closed: session_id=%s frames_received=%d", session_id, seq
        )
