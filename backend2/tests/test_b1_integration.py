"""Integration tests between Backend 1 audio ingestion and Backend 2 buffer.

Verifies that binary PCM16 frames ingested over /ws/audio are correctly
buffered into SessionBufferManager in FIFO order while preserving immediate
sequence ACKs and existing non-binary frame handling.
"""
from __future__ import annotations

import unittest

from backend2.buffer import get_buffer_manager, reset_buffer_manager

try:
    from fastapi.testclient import TestClient
    from backend1.app import app

    HAS_TESTCLIENT = True
except ImportError:
    HAS_TESTCLIENT = False


@unittest.skipUnless(HAS_TESTCLIENT, "fastapi or httpx not available for TestClient")
class TestBackend1BufferIntegration(unittest.TestCase):
    def setUp(self):
        self.buffer_manager = get_buffer_manager()
        self.buffer_manager.clear_all()
        self.client = TestClient(app)

    def tearDown(self):
        self.buffer_manager.clear_all()

    def test_single_binary_frame_buffered_and_acked(self):
        session_id = "test-session-1"
        pcm_frame = bytes([0x12, 0x34] * 4000)  # 8000 bytes (250ms at 16kHz mono)

        with self.client.websocket_connect(f"/ws/audio?session_id={session_id}") as ws:
            ws.send_bytes(pcm_frame)
            ack = ws.receive_json()

            self.assertEqual(ack, {"type": "ack", "seq": 0})
            self.assertEqual(self.buffer_manager.get_size(session_id), 8000)
            self.assertEqual(self.buffer_manager.extract(session_id, 8000), pcm_frame)
            self.assertEqual(self.buffer_manager.get_size(session_id), 0)

    def test_multiple_frames_preserve_fifo_order_and_seq(self):
        session_id = "test-session-multi"
        frame_0 = b"\x01\x02" * 100
        frame_1 = b"\x03\x04" * 100
        frame_2 = b"\x05\x06" * 100

        with self.client.websocket_connect(f"/ws/audio?session_id={session_id}") as ws:
            # Send Frame 0
            ws.send_bytes(frame_0)
            ack_0 = ws.receive_json()
            self.assertEqual(ack_0, {"type": "ack", "seq": 0})

            # Send Frame 1
            ws.send_bytes(frame_1)
            ack_1 = ws.receive_json()
            self.assertEqual(ack_1, {"type": "ack", "seq": 1})

            # Send Frame 2
            ws.send_bytes(frame_2)
            ack_2 = ws.receive_json()
            self.assertEqual(ack_2, {"type": "ack", "seq": 2})

        # Verify buffer size and exact sequential content
        self.assertEqual(self.buffer_manager.get_size(session_id), 600)
        expected_combined = frame_0 + frame_1 + frame_2
        extracted = self.buffer_manager.extract(session_id, 600)
        self.assertEqual(extracted, expected_combined)
        self.assertEqual(self.buffer_manager.get_size(session_id), 0)

    def test_text_frame_ignored_and_not_buffered(self):
        session_id = "test-session-text"

        with self.client.websocket_connect(f"/ws/audio?session_id={session_id}") as ws:
            ws.send_text('{"action": "ping"}')
            ack = ws.receive_json()

            self.assertEqual(ack, {"type": "ack_ignored", "seq": 0})
            self.assertEqual(self.buffer_manager.get_size(session_id), 0)

    def test_independent_sessions_isolated_in_buffer(self):
        pcm_a = b"\xaa" * 500
        pcm_b = b"\xbb" * 800

        with self.client.websocket_connect("/ws/audio?session_id=user-A") as ws_a:
            ws_a.send_bytes(pcm_a)
            ack_a = ws_a.receive_json()
            self.assertEqual(ack_a, {"type": "ack", "seq": 0})

        with self.client.websocket_connect("/ws/audio?session_id=user-B") as ws_b:
            ws_b.send_bytes(pcm_b)
            ack_b = ws_b.receive_json()
            self.assertEqual(ack_b, {"type": "ack", "seq": 0})

        self.assertEqual(self.buffer_manager.get_size("user-A"), 500)
        self.assertEqual(self.buffer_manager.get_size("user-B"), 800)
        self.assertEqual(self.buffer_manager.extract("user-A", 500), pcm_a)
        self.assertEqual(self.buffer_manager.extract("user-B", 800), pcm_b)


if __name__ == "__main__":
    unittest.main()
