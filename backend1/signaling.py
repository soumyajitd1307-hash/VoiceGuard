"""Backend 1 — minimal two-person WebRTC signaling hub.

Two browser peers join the same call room; this hub relays SDP
offer/answer and ICE candidates between them. It performs NO media
handling, NO detection, and stores NO audio.

Endpoint (mounted by ``backend1.app``):
    WS /ws/signal?call_id=<CALL_ID>&participant_id=<PARTICIPANT_ID>

Client -> server (JSON text frames):
    {"type": "join", "display_name": "<name>"}
    {"type": "offer" | "answer" | "ice", "to": "<participant_id>",
     "payload": {...}}
    {"type": "leave"}

Server -> client (JSON text frames):
    {"type": "joined", "call_id": ..., "participant_id": ...,
     "peers": [{"participant_id": ..., "display_name": ...}]}
    {"type": "peer-joined", "participant_id": ..., "display_name": ...}
    {"type": "offer" | "answer" | "ice",
     "from": "<participant_id>", "payload": {...}}
    {"type": "peer-left", "participant_id": ...}
    {"type": "error", "detail": ...}

RTCPeerConnection/SDP/ICE themselves live entirely in the browsers;
this hub only routes their JSON envelopes within one call room.
"""
from __future__ import annotations

import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("backend1.signaling")

MAX_DISPLAY_NAME_LENGTH = 64
MAX_PARTICIPANTS_PER_ROOM = 8


class SignalingHub:
    """In-memory call rooms mapping call_id -> participant_id -> peer."""

    def __init__(self) -> None:
        self._rooms: dict[str, dict[str, dict]] = {}

    def _room(self, call_id: str) -> dict[str, dict]:
        return self._rooms.setdefault(call_id, {})

    async def _send(self, websocket: WebSocket, message: dict) -> None:
        await websocket.send_json(message)

    async def handle(
        self, websocket: WebSocket, call_id: str, participant_id: str
    ) -> None:
        """Serve one signaling connection for its whole lifetime."""
        await websocket.accept()

        if not call_id or not participant_id:
            await self._send(
                websocket,
                {"type": "error", "detail": "call_id and participant_id are required"},
            )
            await websocket.close(code=4400)
            return

        room = self._room(call_id)
        if participant_id in room:
            await self._send(
                websocket,
                {"type": "error", "detail": "participant_id already in this call"},
            )
            await websocket.close(code=4400)
            return
        if len(room) >= MAX_PARTICIPANTS_PER_ROOM:
            await self._send(
                websocket, {"type": "error", "detail": "call room is full"}
            )
            await websocket.close(code=4400)
            return

        display_name = ""
        joined = False
        logger.info(
            "signal connected: call_id=%s participant_id=%s", call_id, participant_id
        )
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                text = message.get("text")
                if text is None:  # binary frames are not signaling
                    await self._send(
                        websocket,
                        {"type": "error", "detail": "signaling accepts JSON text only"},
                    )
                    continue
                try:
                    data = json.loads(text)
                except (ValueError, TypeError):
                    await self._send(
                        websocket, {"type": "error", "detail": "malformed JSON"}
                    )
                    continue
                if not isinstance(data, dict):
                    await self._send(
                        websocket, {"type": "error", "detail": "message must be an object"}
                    )
                    continue

                msg_type = data.get("type")
                if msg_type == "join":
                    if joined:
                        continue
                    display_name = str(data.get("display_name", ""))[
                        :MAX_DISPLAY_NAME_LENGTH
                    ]
                    peers = [
                        {
                            "participant_id": pid,
                            "display_name": peer["display_name"],
                        }
                        for pid, peer in room.items()
                    ]
                    room[participant_id] = {
                        "display_name": display_name,
                        "websocket": websocket,
                    }
                    joined = True
                    await self._send(
                        websocket,
                        {
                            "type": "joined",
                            "call_id": call_id,
                            "participant_id": participant_id,
                            "peers": peers,
                        },
                    )
                    for pid, peer in room.items():
                        if pid != participant_id:
                            try:
                                await self._send(
                                    peer["websocket"],
                                    {
                                        "type": "peer-joined",
                                        "call_id": call_id,
                                        "participant_id": participant_id,
                                        "display_name": display_name,
                                    },
                                )
                            except Exception:  # noqa: BLE001 - best effort notify
                                logger.warning(
                                    "signal notify failed: call_id=%s to=%s",
                                    call_id,
                                    pid,
                                )
                    logger.info(
                        "signal join: call_id=%s participant_id=%s name=%r peers=%d",
                        call_id,
                        participant_id,
                        display_name,
                        len(room),
                    )
                elif msg_type in ("offer", "answer", "ice"):
                    if not joined:
                        await self._send(
                            websocket,
                            {"type": "error", "detail": "join first"},
                        )
                        continue
                    target_id = data.get("to")
                    payload = data.get("payload")
                    target = room.get(target_id) if isinstance(target_id, str) else None
                    if target is None or not isinstance(payload, dict):
                        await self._send(
                            websocket,
                            {"type": "error", "detail": "unknown peer or bad payload"},
                        )
                        continue
                    try:
                        await self._send(
                            target["websocket"],
                            {
                                "type": msg_type,
                                "call_id": call_id,
                                "from": participant_id,
                                "payload": payload,
                            },
                        )
                    except Exception:  # noqa: BLE001 - report, don't crash
                        logger.warning(
                            "signal relay failed: call_id=%s from=%s to=%s kind=%s",
                            call_id,
                            participant_id,
                            target_id,
                            msg_type,
                        )
                        await self._send(
                            websocket,
                            {"type": "error", "detail": "peer unreachable"},
                        )
                elif msg_type == "leave":
                    break
                else:
                    await self._send(
                        websocket,
                        {"type": "error", "detail": f"unknown message type {msg_type!r}"},
                    )
        except WebSocketDisconnect:
            logger.info(
                "signal disconnected: call_id=%s participant_id=%s",
                call_id,
                participant_id,
            )
        except Exception:
            logger.exception(
                "signal error: call_id=%s participant_id=%s", call_id, participant_id
            )
            try:
                await websocket.close()
            except Exception:  # noqa: BLE001 - already closing
                pass
        finally:
            removed = room.pop(participant_id, None)
            if not room:
                self._rooms.pop(call_id, None)
            if joined and removed is not None:
                for pid, peer in room.items():
                    try:
                        await self._send(
                            peer["websocket"],
                            {
                                "type": "peer-left",
                                "call_id": call_id,
                                "participant_id": participant_id,
                            },
                        )
                    except Exception:  # noqa: BLE001 - best effort notify
                        logger.warning(
                            "signal peer-left notify failed: call_id=%s to=%s",
                            call_id,
                            pid,
                        )
            logger.info(
                "signal closed: call_id=%s participant_id=%s", call_id, participant_id
            )
