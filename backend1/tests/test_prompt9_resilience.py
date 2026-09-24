"""Prompt 9 hardening regression tests (no browser required).

Covers failure paths added or fixed in this milestone without TestClient
(unavailable: no httpx in this env — handlers are driven directly with
order-tracking fakes):
- B4 risk socket: accept() precedes any 4401 close (ASGI/uvicorn turns
  close-before-accept into an opaque HTTP 403, hiding the verdict).
- B1 ingest: malformed frames rejected with ack_invalid, never buffered,
  never spawn workers; valid frames still ack + buffer; disconnect drops
  the session buffer (bounded sessions).
"""
from __future__ import annotations

import asyncio
import unittest
from unittest import mock


class OrderTrackingSocket:
    """Fake starlette WebSocket recording accept/close ordering."""

    def __init__(self, script=(), headers=None, query_params=None):
        from starlette.websockets import WebSocketDisconnect

        self._WebSocketDisconnect = WebSocketDisconnect
        self.headers = headers or {}
        self.query_params = query_params or {}
        self.script = list(script)
        self.sent = []
        self.calls = []
        self.closed = None

    async def accept(self):
        self.calls.append("accept")

    async def receive(self):
        if not self.script:
            raise self._WebSocketDisconnect()
        action = self.script.pop(0)
        if action == "disconnect":
            raise self._WebSocketDisconnect()
        return action

    async def receive_text(self):
        # Only used by websocket_endpoint (not under test here).
        raise self._WebSocketDisconnect()

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self, code=1000):
        self.calls.append(("close", code))
        self.closed = code


class TestRiskSocketAcceptOrder(unittest.TestCase):
    def test_unknown_call_accepts_then_4401(self):
        import backend.api as api_module

        async def _run():
            ws = OrderTrackingSocket(headers={})
            await api_module.ws_calls(ws, "ghost-xyz-123")
            return ws

        ws = asyncio.run(_run())
        # Accept MUST precede close: otherwise uvicorn degrades the
        # designed 4401 verdict into an opaque HTTP 403 handshake failure.
        self.assertEqual(ws.calls[0], "accept")
        self.assertEqual(ws.closed, 4401)

    def test_known_call_accepts_without_close(self):
        import backend.api as api_module
        from backend.call_service import view_create_call

        async def _run():
            service = api_module.get_call_service()
            status, body = view_create_call(service, "owner-1")
            self.assertEqual(status, 200)
            ws = OrderTrackingSocket(headers={})
            # Drive only up to subscription: run handler briefly, then close.
            task = asyncio.ensure_future(api_module.ws_calls(ws, body["id"]))
            for _ in range(200):
                await asyncio.sleep(0)
                if service.ws.subscribers_for(body["id"]):
                    break
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return ws, body["id"]

        ws, call_id = asyncio.run(_run())
        self.assertEqual(ws.calls[0], "accept")
        self.assertIsNone(ws.closed)
        api_module.reset_api_service()


class TestB1MalformedFrames(unittest.TestCase):
    def test_invalid_frames_rejected_never_buffered_no_worker(self):
        from backend1 import app as b1_app
        from backend1 import pipeline_driver
        from backend2.buffer import get_buffer_manager

        async def _run():
            mgr = get_buffer_manager()
            mgr.clear_all()
            ws = OrderTrackingSocket(
                query_params={"session_id": "p9-malformed"})
            script = [
                {"bytes": b""},
                {"bytes": b"\x01\x02\x03"},
                {"bytes": bytes(2 * 1024 * 1024)},
            ]
            for frame in script:
                ws.script.append(frame)
            with mock.patch.object(
                    pipeline_driver, "ensure_worker") as ensure:
                await b1_app.ws_audio(ws)
                ensure_calls = ensure.call_count
            return ws, mgr, ensure_calls

        ws, mgr, ensure_calls = asyncio.run(_run())
        try:
            kinds = [m.get("type") for m in ws.sent]
            self.assertEqual(kinds, ["ack_invalid"] * 3, ws.sent)
            seqs = [m.get("seq") for m in ws.sent]
            self.assertEqual(seqs, [0, 1, 2])
            self.assertEqual(mgr.get_size("p9-malformed"), 0)
            self.assertEqual(ensure_calls, 0)
        finally:
            mgr.clear_all()

    def test_valid_frame_after_invalid_still_processed(self):
        from backend1 import app as b1_app
        from backend2.buffer import get_buffer_manager

        async def _run():
            mgr = get_buffer_manager()
            mgr.clear_all()
            ws = OrderTrackingSocket(
                query_params={"session_id": "p9-recover"})
            ws.script.extend([
                {"bytes": b"\x01"},
                {"bytes": bytes(8000)},
            ])
            with mock.patch.object(
                    __import__("backend1.pipeline_driver",
                               fromlist=["x"]), "ensure_worker") as ensure:
                await b1_app.ws_audio(ws)
                ensure_calls = ensure.call_count
            return ws, mgr, ensure_calls

        ws, mgr, ensure_calls = asyncio.run(_run())
        try:
            self.assertEqual(
                [m.get("type") for m in ws.sent], ["ack_invalid", "ack"])
            # Exact contracts: invalid carries reason + seq, valid is the
            # legacy ack shape (existing clients ignore anything else).
            self.assertEqual(ws.sent[0]["seq"], 0)
            self.assertIn("reason", ws.sent[0])
            self.assertEqual(ws.sent[1], {"type": "ack", "seq": 1})
            self.assertEqual(ensure_calls, 1)
            self.assertFalse(mgr.has_session("p9-recover"))
        finally:
            mgr.clear_all()

    def test_disconnect_drops_session_buffer(self):
        from backend1 import app as b1_app
        from backend2.buffer import get_buffer_manager

        async def _run():
            mgr = get_buffer_manager()
            mgr.clear_all()
            ws = OrderTrackingSocket(
                query_params={"session_id": "p9-cleanup"})
            ws.script.append({"bytes": bytes(8000)})
            # ensure_worker mocked: no real worker task is spawned, so the
            # real stop_session + remove_session path runs exactly as live.
            with mock.patch.object(
                    __import__("backend1.pipeline_driver",
                               fromlist=["x"]), "ensure_worker") as ensure:
                await b1_app.ws_audio(ws)
                ensure_calls = ensure.call_count
            return mgr, ensure_calls

        mgr, ensure_calls = asyncio.run(_run())
        try:
            self.assertEqual(ensure_calls, 1)
            self.assertEqual(mgr.get_size("p9-cleanup"), 0)
            self.assertFalse(mgr.has_session("p9-cleanup"))
        finally:
            mgr.clear_all()


if __name__ == "__main__":
    unittest.main()
