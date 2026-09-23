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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from backend2.buffer import AudioBufferError, get_buffer_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend1")

app = FastAPI(title="VoiceGuard Backend 1 — Audio Ingestion")
buffer_manager = get_buffer_manager()


@app.get("/health")
def health() -> dict:
    """Liveness probe for Backend 1."""
    return {"status": "ok"}


@app.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket) -> None:
    """Audio ingest endpoint: ``/ws/audio?session_id=<SESSION_ID>``."""
    await websocket.accept()

    session_id = websocket.query_params.get("session_id", "unknown")
    seq = 0
    logger.info("audio ws connected: session_id=%s", session_id)

    try:
        while True:
            message = await websocket.receive()

            if "bytes" in message and message["bytes"] is not None:
                data: bytes = message["bytes"]
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
        logger.info(
            "audio ws closed: session_id=%s frames_received=%d", session_id, seq
        )
