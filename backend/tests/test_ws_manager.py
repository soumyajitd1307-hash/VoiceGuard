"""Tests for the Part 5 WebSocket manager. Stdlib unittest only."""
from __future__ import annotations

import threading
import unittest

from backend.schemas import ValidationError
from backend.ws_manager import WsConnectionManager, assert_wire_safe


class FakeWebSocket:
    """Minimal stand-in with the surface websocket_endpoint needs."""

    def __init__(self, script):
        import asyncio as _asyncio

        self._asyncio = _asyncio
        self.script = list(script)
        self.accepted = False
        self.sent = []

    async def accept(self):
        await self._asyncio.sleep(0)
        self.accepted = True

    async def receive_text(self):
        await self._asyncio.sleep(0)
        if not self.script:
            from starlette.websockets import WebSocketDisconnect

            raise WebSocketDisconnect()
        action = self.script.pop(0)
        if action == "disconnect":
            from starlette.websockets import WebSocketDisconnect

            raise WebSocketDisconnect()
        return action

    async def send_json(self, message):
        await self._asyncio.sleep(0)
        self.sent.append(message)


class TestWireSafety(unittest.TestCase):
    def test_clean_message_passes(self):
        assert_wire_safe({"type": "risk_update", "risk": 10})

    def test_embedding_rejected_anywhere(self):
        with self.assertRaises(ValidationError):
            assert_wire_safe({"speaker": {"embedding": [0.1]}})
        with self.assertRaises(ValidationError):
            assert_wire_safe([{"audio": "xyz"}])


class TestWsConnectionManager(unittest.TestCase):
    def setUp(self):
        self.manager = WsConnectionManager()

    def test_connect(self):
        token = self.manager.connect("call-1", lambda message: None)
        self.assertTrue(token)
        self.assertEqual(self.manager.active_connections(), 1)
        self.assertEqual(self.manager.subscribers_for("call-1"), 1)

    def test_disconnect(self):
        token = self.manager.connect("call-1", lambda message: None)
        self.assertTrue(self.manager.disconnect(token))
        self.assertFalse(self.manager.disconnect(token))  # idempotent
        self.assertEqual(self.manager.active_connections(), 0)

    def test_broadcast_risk_update(self):
        received: list = []
        self.manager.connect("call-1", received.append)
        message = {"type": "risk_update", "callId": "call-1", "risk": 55.0}
        delivered = self.manager.broadcast_risk_update(message)
        self.assertEqual(delivered, 1)
        self.assertEqual(received[0]["risk"], 55.0)
        message["risk"] = 0.0  # published copies are immune to mutation
        self.assertEqual(received[0]["risk"], 55.0)

    def test_no_raw_embedding(self):
        self.manager.connect("call-1", lambda message: None)
        with self.assertRaises(ValidationError):
            self.manager.publish_to_call("call-1", {"speaker": {"embedding": [1.0]}})
        with self.assertRaises(ValidationError):
            self.manager.broadcast_risk_update(
                {"type": "risk_update", "callId": "call-1", "embedding": []})

    def test_correct_shape_passthrough(self):
        received: list = []
        self.manager.connect("call-1", received.append)
        message = {"type": "risk_update", "callId": "call-1", "timestamp": 3.0,
                   "risk": 20.0, "confidence": "LOW", "monitoringState": "MONITORING_ACTIVE"}
        self.manager.broadcast_risk_update(message)
        self.assertEqual(received[0], message)

    def test_call_scoped_broadcast(self):
        first: list = []
        second: list = []
        self.manager.connect("call-1", first.append)
        self.manager.connect("call-2", second.append)
        self.manager.broadcast_risk_update(
            {"type": "risk_update", "callId": "call-1", "risk": 10.0})
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)  # other owner's call hears nothing

    def test_disconnected_client_cleanup(self):
        def _dead(message):
            raise RuntimeError("gone")

        received: list = []
        self.manager.connect("call-1", _dead)
        self.manager.connect("call-1", received.append)
        delivered = self.manager.publish_to_call("call-1", {"type": "x"})
        self.assertEqual(delivered, 1)
        self.assertEqual(self.manager.subscribers_for("call-1"), 1)

    def test_non_risk_update_rejected(self):
        with self.assertRaises(ValidationError):
            self.manager.broadcast_risk_update({"type": "ping"})
        with self.assertRaises(ValidationError):
            self.manager.broadcast_risk_update({"type": "risk_update"})  # no callId

    def test_thread_safety(self):
        errors: list = []

        def work(i: int) -> None:
            try:
                token = self.manager.connect(f"call-{i % 4}", lambda message: None)
                self.manager.publish_to_call(f"call-{i % 4}", {"type": "risk_update"})
                self.manager.disconnect(token)
            except Exception as exc:  # noqa: BLE001 - collected for assertion
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(32)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])

    def test_websocket_endpoint_adapter(self):
        import asyncio

        from backend.ws_manager import websocket_endpoint

        async def _run():
            manager = WsConnectionManager()
            socket = FakeWebSocket(["ping", "disconnect"])
            await websocket_endpoint(socket, "call-9", manager)
            return manager, socket

        manager, socket = asyncio.run(_run())
        self.assertTrue(socket.accepted)
        self.assertEqual(manager.active_connections(), 0)  # cleaned up
        manager2 = WsConnectionManager()
        socket2 = FakeWebSocket(["ping", "ping", "disconnect"])

        async def _run_publish():
            task = asyncio.ensure_future(websocket_endpoint(socket2, "call-9", manager2))
            for _ in range(1000):
                await asyncio.sleep(0)
                if manager2.subscribers_for("call-9"):
                    break
            manager2.publish_to_call(
                "call-9", {"type": "risk_update", "callId": "call-9", "risk": 33.0})
            await task

        asyncio.run(_run_publish())
        self.assertEqual(socket2.sent,
                         [{"type": "risk_update", "callId": "call-9", "risk": 33.0}])
        self.assertEqual(manager2.active_connections(), 0)


if __name__ == "__main__":
    unittest.main()
