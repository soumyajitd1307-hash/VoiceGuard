"""Backend 4 Part 5: WebSocket connection manager (development transport).

Two layers, kept separate so domain tests never need a server:

1. ``WsConnectionManager`` -- framework-free core: call-scoped
   subscriptions over plain callbacks, thread-safe. ``publish`` delivers
   deep copies; failing subscribers are pruned, never fatal.
2. ``websocket_endpoint`` -- thin Starlette/FastAPI adapter (imports the
   framework lazily, so this module imports cleanly without it). One
   socket subscribes to exactly one ``call_id``; no global broadcast of
   all calls exists.

Wire-safety guard: any outbound payload containing an ``embedding`` or
``audio`` key (at any depth) is rejected before send. Only
application-level ``RiskUpdate`` dicts travel the socket -- never
vectors, audio, profiles, owners or debug objects.
"""
from __future__ import annotations

import copy
import logging
import threading
import uuid
from typing import Any, Callable

from backend.schemas import ValidationError

log = logging.getLogger(__name__)

SendFn = Callable[[dict], None]


def assert_wire_safe(message: Any) -> None:
    """Reject payloads carrying embeddings/audio anywhere in the structure."""
    stack = [message]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("embedding", "audio"):
                    raise ValidationError(
                        f"Refusing to publish wire message containing {key!r}.")
                stack.append(value)
        elif isinstance(node, (list, tuple)):
            stack.extend(node)


class WsConnectionManager:
    """In-memory call-scoped pub/sub for RiskUpdate delivery."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # token -> {"call_id": str, "send": SendFn}
        self._connections: dict[str, dict] = {}

    def connect(self, call_id: str, send: SendFn) -> str:
        """Register a subscriber for one call. Returns a connection token."""
        if not isinstance(call_id, str) or not call_id.strip():
            raise ValidationError("call_id must be a non-empty string.")
        if not callable(send):
            raise ValidationError("send must be callable.")
        token = uuid.uuid4().hex
        with self._lock:
            self._connections[token] = {"call_id": call_id, "send": send}
        log.info("ws connect call=%s connections=%d", call_id, len(self._connections))
        return token

    def disconnect(self, token: str) -> bool:
        """Remove a subscriber. True when one existed (idempotent)."""
        with self._lock:
            existed = self._connections.pop(token, None) is not None
        if existed:
            log.info("ws disconnect connections=%d", len(self._connections))
        return existed

    def active_connections(self) -> int:
        with self._lock:
            return len(self._connections)

    def subscribers_for(self, call_id: str) -> int:
        with self._lock:
            return sum(1 for conn in self._connections.values()
                       if conn["call_id"] == call_id)

    def publish_to_call(self, call_id: str, message: dict) -> int:
        """Deliver a wire-safe copy to this call's subscribers only.

        Returns the delivery count. Failing subscribers are pruned.
        """
        if not isinstance(message, dict):
            raise ValidationError("message must be a dict.")
        assert_wire_safe(message)
        with self._lock:
            targets = [(token, conn["send"]) for token, conn in
                       self._connections.items() if conn["call_id"] == call_id]
        delivered = 0
        for token, send in targets:
            try:
                send(copy.deepcopy(message))
                delivered += 1
            except Exception:  # noqa: BLE001 - prune dead subscriber, keep rest
                log.warning("ws pruning dead subscriber for call=%s", call_id)
                self.disconnect(token)
        return delivered

    def broadcast_risk_update(self, risk_update: dict) -> int:
        """Route a RiskUpdate to its own call's subscribers (via callId)."""
        if not isinstance(risk_update, dict) or risk_update.get("type") != "risk_update":
            raise ValidationError("Only risk_update messages can be broadcast.")
        call_id = risk_update.get("callId")
        if not isinstance(call_id, str) or not call_id:
            raise ValidationError("risk_update needs a callId for routing.")
        return self.publish_to_call(call_id, risk_update)

    def clear(self) -> None:
        """Drop all subscriptions (tests / controlled reset)."""
        with self._lock:
            self._connections.clear()


async def websocket_endpoint(websocket: Any, call_id: str,
                             manager: WsConnectionManager) -> None:
    """Starlette/FastAPI adapter: one socket, one call subscription.

    Imported framework-free; the ``websocket`` object only needs
    ``accept()``, ``send_json()`` and ``receive_text()`` (a fake covers
    tests). Closes cleanly when the client disconnects.
    """
    try:
        from starlette.websockets import WebSocketDisconnect  # lazy: optional dep
    except ImportError as exc:
        raise ImportError("Install fastapi/starlette for WebSocket transport.") from exc
    await websocket.accept()
    queue: list = []

    def _send(message: dict) -> None:
        queue.append(message)

    token = manager.connect(call_id, _send)
    try:
        while True:
            try:
                await websocket.receive_text()  # heartbeat/ignore inbound
            except WebSocketDisconnect:
                break
            while queue:
                await websocket.send_json(queue.pop(0))
    finally:
        manager.disconnect(token)
