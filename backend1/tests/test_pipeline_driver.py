"""Tests for the Backend 1 live pipeline driver (Prompt 5).

Uses a real SessionBufferManager plus real B2 extract/preprocess/VAD/
package stages; only the B4 HTTP boundary is faked (injected). Proves:
one session end-to-end, per-session isolation across two calls,
silence produces no detection, termination stops the worker, and one
session's failure does not touch the other.
"""
from __future__ import annotations

import asyncio
import math
import unittest
from unittest import mock

from backend1 import pipeline_driver
from backend1.pipeline_driver import SessionWorker
from backend2.buffer import SessionBufferManager


def _sine_pcm16(n_samples: int = 16000, amplitude: float = 0.5) -> bytes:
    import struct

    return b"".join(
        struct.pack(
            "<h", int(amplitude * 32767 * math.sin(2 * math.pi * 440 * i / 16000))
        )
        for i in range(n_samples)
    )


def _silence_pcm16(n_samples: int = 16000) -> bytes:
    return b"\x00\x00" * n_samples


class DriverTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mgr = SessionBufferManager()

    def make_worker(self, session_id: str) -> SessionWorker:
        return SessionWorker(session_id, self.mgr, base_url="http://b4.test/api/v1")


class TestSingleSession(DriverTestBase):
    async def test_audio_reaches_b4_with_same_call_id(self):
        worker = self.make_worker("call-A")
        self.mgr.append("call-A", _sine_pcm16())
        posted: list = []
        with mock.patch.object(
            pipeline_driver,
            "_b4_post_chunk",
            side_effect=lambda base, call, payload: posted.append((call, payload))
            or {"risk": 11.0, "timestamp": 0.0},
        ):
            outcome = await worker.drain_once()
        self.assertEqual(outcome, "posted")
        self.assertEqual(len(posted), 1)
        call_id, payload = posted[0]
        # Identity preserved end to end; chunk ids monotonic from zero.
        self.assertEqual(call_id, "call-A")
        self.assertEqual(payload["session_id"], "call-A")
        self.assertEqual(payload["chunk_id"], "c00000")
        self.assertEqual(payload["timestamp_s"], 0.0)
        self.assertEqual(len(payload["audio"]), 16000)
        self.assertEqual(worker.windows_extracted, 1)
        self.assertEqual(worker.chunks_posted, 1)
        # Cursor consumed: nothing left to reprocess.
        self.assertEqual(self.mgr.get_size("call-A"), 0)
        with mock.patch.object(
            pipeline_driver, "_b4_post_chunk", side_effect=AssertionError("repost!")
        ):
            self.assertEqual(await worker.drain_once(), "idle")

    async def test_second_window_advances_chunk_id_and_timestamp(self):
        worker = self.make_worker("call-A")
        self.mgr.append("call-A", _sine_pcm16() + _sine_pcm16())
        seen: list = []
        with mock.patch.object(
            pipeline_driver,
            "_b4_post_chunk",
            side_effect=lambda base, call, payload: seen.append(payload)
            or {"risk": 5.0, "timestamp": 1.0},
        ):
            self.assertEqual(await worker.drain_once(), "posted")
            self.assertEqual(await worker.drain_once(), "posted")
        self.assertEqual(
            [(p["chunk_id"], p["timestamp_s"]) for p in seen],
            [("c00000", 0.0), ("c00001", 1.0)],
        )


class TestMultiSessionIsolation(DriverTestBase):
    async def test_two_calls_stay_associated(self):
        worker_a = self.make_worker("call-A")
        worker_b = self.make_worker("call-B")
        self.mgr.append("call-A", _sine_pcm16())
        self.mgr.append("call-B", _sine_pcm16())
        posted: list = []
        with mock.patch.object(
            pipeline_driver,
            "_b4_post_chunk",
            side_effect=lambda base, call, payload: posted.append((call, payload))
            or {"risk": 1.0, "timestamp": 0.0},
        ):
            self.assertEqual(await worker_b.drain_once(), "posted")
            self.assertEqual(await worker_a.drain_once(), "posted")
        by_call = {call: payload for call, payload in posted}
        self.assertEqual(set(by_call), {"call-A", "call-B"})
        self.assertEqual(by_call["call-A"]["session_id"], "call-A")
        self.assertEqual(by_call["call-B"]["session_id"], "call-B")
        self.assertEqual(worker_a.windows_extracted, 1)
        self.assertEqual(worker_b.windows_extracted, 1)

    async def test_error_in_a_does_not_stop_b(self):
        worker_a = self.make_worker("call-A")
        worker_b = self.make_worker("call-B")
        self.mgr.append("call-A", _sine_pcm16())
        self.mgr.append("call-B", _sine_pcm16())

        def post(base, call, payload):
            if call == "call-A":
                raise RuntimeError("B4 down for A")
            return {"risk": 2.0, "timestamp": 0.0}

        with mock.patch.object(pipeline_driver, "_b4_post_chunk", side_effect=post):
            self.assertEqual(await worker_a.drain_once(), "error")
            self.assertEqual(worker_a.errors, 1)
            self.assertEqual(worker_a.chunks_posted, 0)
            self.assertEqual(await worker_b.drain_once(), "posted")
            self.assertEqual(worker_b.errors, 0)
            self.assertEqual(worker_b.chunks_posted, 1)


class TestSilence(DriverTestBase):
    async def test_silence_consumed_never_posted(self):
        worker = self.make_worker("call-A")
        self.mgr.append("call-A", _silence_pcm16())
        with mock.patch.object(
            pipeline_driver,
            "_b4_post_chunk",
            side_effect=AssertionError("silence must not reach B4"),
        ):
            self.assertEqual(await worker.drain_once(), "skipped")
        self.assertEqual(worker.silence_skipped, 1)
        self.assertEqual(worker.chunks_posted, 0)
        self.assertEqual(self.mgr.get_size("call-A"), 0)


class TestTermination(DriverTestBase):
    async def test_worker_stops_when_call_not_active(self):
        worker = self.make_worker("call-A")
        self.mgr.append("call-A", _sine_pcm16())
        statuses = iter(["ACTIVE", "ENDED"])
        posted: list = []
        with (
            mock.patch.object(
                pipeline_driver,
                "_b4_get_status",
                side_effect=lambda base, call: next(statuses, "ENDED"),
            ),
            mock.patch.object(
                pipeline_driver,
                "_b4_post_chunk",
                side_effect=lambda base, call, payload: posted.append(payload)
                or {"risk": 3.0, "timestamp": 0.0},
            ),
            mock.patch.object(pipeline_driver, "STATUS_POLL_S", 0.01),
            mock.patch.object(pipeline_driver, "IDLE_SLEEP_S", 0.01),
        ):
            worker.task = asyncio.get_running_loop().create_task(worker.run())
            await asyncio.wait_for(worker.task, timeout=10)
        self.assertFalse(worker.running)
        # One window processed while ACTIVE, then the ENDED poll stopped it.
        self.assertEqual(len(posted), 1)
        self.assertEqual(worker.chunks_posted, 1)

    async def test_worker_never_starts_for_unknown_call(self):
        worker = self.make_worker("ghost")
        self.mgr.append("ghost", _sine_pcm16())
        with mock.patch.object(
            pipeline_driver, "_b4_get_status", return_value="UNKNOWN"
        ):
            worker.task = asyncio.get_running_loop().create_task(worker.run())
            await asyncio.wait_for(worker.task, timeout=10)
        self.assertFalse(worker.running)
        self.assertEqual(worker.chunks_posted, 0)


if __name__ == "__main__":
    unittest.main()
