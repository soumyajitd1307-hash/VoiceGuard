"""Prompt 9 regression: B4 risk socket must accept() before any close.

ASGI/uvicorn translates close-before-accept into an opaque HTTP 403 at
handshake time, hiding the designed 4401 verdict. These tests pin the
accept-first ordering with an order-tracking fake (no TestClient needed).
"""
from __future__ import annotations

import asyncio
import unittest


def _settings(**overrides):
    from backend.config import Settings

    params = dict(
        model_name="mock", model_version="mock-heuristic-v0.1.0",
        embedder_name="mock", embedder_version="mock-spectral-v0.1.0",
        synthetic_threshold=0.7, real_threshold=0.3,
        min_duration_s=0.25, max_duration_s=30.0,
        max_id_length=128, log_level="CRITICAL")
    params.update(overrides)
    return Settings(**params)


class OrderTrackingSocket:
    """Fake starlette WebSocket recording accept/close call order."""

    def __init__(self, headers=None):
        from starlette.websockets import WebSocketDisconnect

        self._WebSocketDisconnect = WebSocketDisconnect
        self.headers = headers or {}
        self.calls = []
        self.sent = []

    async def accept(self):
        self.calls.append("accept")

    async def receive_text(self):
        # No inbound traffic: disconnect immediately after subscription.
        raise self._WebSocketDisconnect()

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self, code=1000):
        self.calls.append(("close", code))


class TestWsAcceptOrder(unittest.TestCase):
    def test_unknown_call_accepts_then_4401(self):
        import backend.api as api_module

        async def _run():
            ws = OrderTrackingSocket(headers={})
            await api_module.ws_calls(ws, "ghost-xyz-123")
            return ws

        ws = asyncio.run(_run())
        # Accept MUST precede close: otherwise the client sees HTTP 403.
        self.assertEqual(ws.calls[0], "accept")
        self.assertIn(("close", 4401), ws.calls)
        self.assertLess(
            ws.calls.index("accept"),
            ws.calls.index(("close", 4401)),
        )

    def test_known_call_accepts_and_stays_subscribed(self):
        import backend.api as api_module
        from backend.call_service import view_create_call

        async def _run():
            service = api_module.get_call_service()
            status, body = view_create_call(service, "owner-1")
            assert status == 200, body
            ws = OrderTrackingSocket(headers={})
            await api_module.ws_calls(ws, body["id"])
            return ws, body["id"], service

        ws, call_id, service = asyncio.run(_run())
        try:
            self.assertEqual(ws.calls[0], "accept")
            # Clean close (fake disconnects immediately): no 4401 verdict.
            self.assertNotIn(("close", 4401), ws.calls)
            self.assertEqual(service.ws.subscribers_for(call_id), 0)
        finally:
            api_module.reset_api_service()


if __name__ == "__main__":
    unittest.main()
