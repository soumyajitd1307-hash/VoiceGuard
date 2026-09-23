"""Unit tests for Backend 2 in-memory audio buffer (backend2/buffer.py).

Verifies FIFO order preservation, independent per-session isolation,
memory protection, thread-safety, async concurrency, and session lifecycle.
"""
from __future__ import annotations

import asyncio
import threading
import unittest

from backend2.buffer import (
    AudioBufferError,
    BufferOverflowError,
    InvalidSessionError,
    SessionAudioBuffer,
    SessionBufferManager,
    SessionNotFoundError,
    get_buffer_manager,
    reset_buffer_manager,
)


def _sample_pcm_chunk(pattern_byte: int, length: int = 8000) -> bytes:
    """Generate a dummy PCM chunk of specific byte value and length."""
    return bytes([pattern_byte] * length)


class TestSessionAudioBuffer(unittest.TestCase):
    def test_init_and_properties(self):
        buf = SessionAudioBuffer("sess-1", max_bytes=16000)
        self.assertEqual(buf.session_id, "sess-1")
        self.assertEqual(buf.size, 0)
        self.assertEqual(len(buf), 0)
        self.assertEqual(buf.total_bytes_appended, 0)
        self.assertEqual(buf.total_bytes_extracted, 0)
        self.assertEqual(buf.dropped_bytes, 0)

    def test_preserve_frame_order_and_unmodified_bytes(self):
        buf = SessionAudioBuffer("sess-1")
        chunk_a = b"\x01\x02\x03\x04"
        chunk_b = b"\x05\x06\x07\x08"
        chunk_c = b"\x09\x10\x11\x12"

        buf.append(chunk_a)
        buf.append(chunk_b)
        buf.append(chunk_c)

        self.assertEqual(buf.size, 12)
        # Extract first 6 bytes
        part1 = buf.extract(6)
        self.assertEqual(part1, b"\x01\x02\x03\x04\x05\x06")
        self.assertEqual(buf.size, 6)

        # Extract remaining 6 bytes
        part2 = buf.extract(6)
        self.assertEqual(part2, b"\x07\x08\x09\x10\x11\x12")
        self.assertEqual(buf.size, 0)

    def test_extract_exact(self):
        buf = SessionAudioBuffer("sess-1")
        buf.append(b"12345")

        with self.assertRaises(ValueError):
            buf.extract(10, exact=True)

        self.assertEqual(buf.extract(3, exact=True), b"123")
        self.assertEqual(buf.size, 2)
        self.assertEqual(buf.extract(10, exact=False), b"45")
        self.assertEqual(buf.size, 0)

    def test_peek_does_not_consume(self):
        buf = SessionAudioBuffer("sess-1")
        data = b"abcdef"
        buf.append(data)

        self.assertEqual(buf.peek(3), b"abc")
        self.assertEqual(buf.size, 6)
        self.assertEqual(buf.peek(), b"abcdef")
        self.assertEqual(buf.size, 6)

    def test_overflow_policy_drop_oldest(self):
        # Buffer capacity 10 bytes
        buf = SessionAudioBuffer("sess-1", max_bytes=10, overflow_policy="drop_oldest")
        buf.append(b"12345678")  # 8 bytes
        self.assertEqual(buf.size, 8)

        # Appending 6 bytes -> total 14 bytes -> drops oldest 4 bytes
        buf.append(b"abcdef")
        self.assertEqual(buf.size, 10)
        self.assertEqual(buf.dropped_bytes, 4)
        # Remaining: "5678" + "abcdef"
        self.assertEqual(buf.extract(10), b"5678abcdef")

    def test_overflow_policy_reject(self):
        buf = SessionAudioBuffer("sess-1", max_bytes=10, overflow_policy="reject")
        buf.append(b"12345678")
        with self.assertRaises(BufferOverflowError):
            buf.append(b"abcdef")
        # Ensure state unchanged
        self.assertEqual(buf.size, 8)

    def test_clear_buffer(self):
        buf = SessionAudioBuffer("sess-1")
        buf.append(b"hello world")
        self.assertEqual(buf.size, 11)
        buf.clear()
        self.assertEqual(buf.size, 0)
        self.assertEqual(buf.extract(5), b"")

    def test_type_validation(self):
        buf = SessionAudioBuffer("sess-1")
        with self.assertRaises(TypeError):
            buf.append("string is not bytes")  # type: ignore[arg-type]


class TestSessionBufferManager(unittest.TestCase):
    def setUp(self):
        self.mgr = SessionBufferManager(max_bytes_per_session=10000, max_sessions=5)

    def tearDown(self):
        self.mgr.clear_all()
        reset_buffer_manager()

    def test_independent_sessions(self):
        chunk1 = b"AAAA"
        chunk2 = b"BBBBBB"

        self.mgr.append("session-1", chunk1)
        self.mgr.append("session-2", chunk2)

        self.assertEqual(self.mgr.get_size("session-1"), 4)
        self.assertEqual(self.mgr.get_size("session-2"), 6)
        self.assertEqual(self.mgr.get_total_buffered_bytes(), 10)

        # Extract from session-1 only
        out1 = self.mgr.extract("session-1", 4)
        self.assertEqual(out1, chunk1)
        self.assertEqual(self.mgr.get_size("session-1"), 0)
        self.assertEqual(self.mgr.get_size("session-2"), 6)

        # Extract from session-2
        out2 = self.mgr.extract("session-2", 6)
        self.assertEqual(out2, chunk2)
        self.assertEqual(self.mgr.get_size("session-2"), 0)

    def test_session_lifecycle_and_removal(self):
        self.mgr.append("sess-1", b"data1")
        self.mgr.append("sess-2", b"data2")
        self.assertTrue(self.mgr.has_session("sess-1"))
        self.assertTrue(self.mgr.has_session("sess-2"))
        self.assertEqual(set(self.mgr.list_sessions()), {"sess-1", "sess-2"})

        # Clear session
        self.mgr.clear_session("sess-1")
        self.assertEqual(self.mgr.get_size("sess-1"), 0)
        self.assertTrue(self.mgr.has_session("sess-1"))

        # Remove session completely
        removed = self.mgr.remove_session("sess-1")
        self.assertTrue(removed)
        self.assertFalse(self.mgr.has_session("sess-1"))
        self.assertEqual(self.mgr.list_sessions(), ["sess-2"])

        # Removing again returns False
        self.assertFalse(self.mgr.remove_session("sess-1"))

    def test_extract_non_existent_session(self):
        self.assertEqual(self.mgr.extract("non-existent", 10), b"")
        with self.assertRaises(SessionNotFoundError):
            self.mgr.extract("non-existent", 10, exact=True)

    def test_invalid_session_ids_rejected(self):
        invalid_ids = ["", "   ", None, 123, True, "a" * 129]
        for bad_id in invalid_ids:
            with self.assertRaises(InvalidSessionError):
                self.mgr.get_or_create_buffer(bad_id)  # type: ignore[arg-type]
            with self.assertRaises(InvalidSessionError):
                self.mgr.append(bad_id, b"audio")  # type: ignore[arg-type]
            with self.assertRaises(InvalidSessionError):
                self.mgr.get_size(bad_id)  # type: ignore[arg-type]

    def test_max_sessions_limit(self):
        mgr = SessionBufferManager(max_sessions=2)
        mgr.append("s1", b"1")
        mgr.append("s2", b"2")
        with self.assertRaises(AudioBufferError):
            mgr.append("s3", b"3")

    def test_concurrent_multithreaded_access(self):
        mgr = SessionBufferManager(max_bytes_per_session=1_000_000)
        session_id = "concurrent-sess"
        num_threads = 8
        chunks_per_thread = 50
        chunk_size = 100

        def worker(thread_idx: int):
            for i in range(chunks_per_thread):
                data = bytes([thread_idx % 256] * chunk_size)
                mgr.append(session_id, data)

        threads = [
            threading.Thread(target=worker, args=(t,))
            for t in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected_total = num_threads * chunks_per_thread * chunk_size
        self.assertEqual(mgr.get_size(session_id), expected_total)
        extracted = mgr.extract(session_id, expected_total)
        self.assertEqual(len(extracted), expected_total)
        self.assertEqual(mgr.get_size(session_id), 0)

    def test_concurrent_async_access(self):
        mgr = SessionBufferManager(max_bytes_per_session=1_000_000)
        session_id = "async-sess"

        async def producer(coro_id: int):
            for _ in range(20):
                await asyncio.sleep(0.001)
                mgr.append(session_id, bytes([coro_id] * 50))

        async def consumer():
            total_extracted = 0
            for _ in range(30):
                await asyncio.sleep(0.002)
                chunk = mgr.extract(session_id, 100)
                total_extracted += len(chunk)
            # Drain remaining
            total_extracted += len(mgr.extract(session_id, 10000))
            return total_extracted

        async def run_async():
            producers = [producer(i) for i in range(5)]
            c_task = asyncio.create_task(consumer())
            await asyncio.gather(*producers)
            return await c_task

        total = asyncio.run(run_async())
        expected = 5 * 20 * 50  # 5000 bytes
        self.assertEqual(total, expected)
        self.assertEqual(mgr.get_size(session_id), 0)

    def test_singleton_get_and_reset(self):
        m1 = get_buffer_manager()
        m2 = get_buffer_manager()
        self.assertIs(m1, m2)
        m1.append("test-sess", b"test")
        self.assertEqual(m2.get_size("test-sess"), 4)

        reset_buffer_manager()
        m3 = get_buffer_manager()
        self.assertIsNot(m1, m3)
        self.assertEqual(m3.get_size("test-sess"), 0)


if __name__ == "__main__":
    unittest.main()
