"""Prompt 9 hardening regression tests (no browser required).

Covers, without TestClient (unavailable: no httpx in this env):
- B1 binary frame validation (reject malformed, accept existing sizes).
- Pipeline worker survival across B4 transport failure (pause, no exit,
  no posts, no buffer burn) and recovery afterwards.
- Unknown-call respawn cooloff (no per-frame B4 hot loop).
- Dead-worker respawn via ensure_worker.
- stop_session clearing the cooloff entry.
- B4 system-status view shape (route lambda verified live separately).
"""
from __future__ import annotations

import asyncio
import math
import unittest
from unittest import mock

from backend1 import pipeline_driver
from backend1.app import validate_audio_frame
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


class TestFrameValidation(unittest.TestCase):
    def test_empty_frame_rejected(self):
        self.assertIsNotNone(validate_audio_frame(b""))

    def test_odd_frame_rejected(self):
        self.assertIsNotNone(validate_audio_frame(b"\x01\x02\x03"))

    def test_oversize_frame_rejected(self):
        self.assertIsNotNone(validate_audio_frame(bytes(2 * 1024 * 1024)))

    def test_existing_valid_sizes_accepted(self):
        # Sizes the established contract + tests rely on (incl. 8000 B).
        for size in (200, 500, 800, 8000, 32000):
            with self.subTest(size=size):
                self.assertIsNone(validate_audio_frame(bytes(size)))


class DriverHarness(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mgr = SessionBufferManager()
        self._saved_workers = dict(pipeline_driver._workers)
        self._saved_cooloff = dict(pipeline_driver._unknown_cooloff)
        pipeline_driver._workers.clear()
        pipeline_driver._unknown_cooloff.clear()

    def tearDown(self):
        pipeline_driver._workers.clear()
        pipeline_driver._workers.update(self._saved_workers)
        pipeline_driver._unknown_cooloff.clear()
        pipeline_driver._unknown_cooloff.update(self._saved_cooloff)

    def make_worker(self, session_id: str) -> SessionWorker:
        return SessionWorker(session_id, self.mgr, base_url="http://b4.test/api/v1")


class TestTransportFailureSurvival(DriverHarness):
    async def test_worker_pauses_not_exits_when_b4_unreachable(self):
        worker = self.make_worker("call-A")
        self.mgr.append("call-A", _sine_pcm16())
        posted: list = []
        with (
            mock.patch.object(pipeline_driver, "_b4_get_status", return_value=None),
            mock.patch.object(
                pipeline_driver,
                "_b4_post_chunk",
                side_effect=lambda base, call, payload: posted.append(payload)
                or AssertionError("must not post while B4 unreachable"),
            ),
            mock.patch.object(pipeline_driver, "STATUS_POLL_S", 0.05),
            mock.patch.object(pipeline_driver, "IDLE_SLEEP_S", 0.01),
        ):
            task = asyncio.get_running_loop().create_task(worker.run())
            await asyncio.sleep(0.25)
            # Still alive, nothing posted, buffer untouched (no burn).
            self.assertTrue(worker.running)
            self.assertEqual(posted, [])
            self.assertEqual(worker.chunks_posted, 0)
            self.assertEqual(self.mgr.get_size("call-A"), 32000)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.assertFalse(worker.running)

    async def test_worker_recovers_after_b4_returns(self):
        worker = self.make_worker("call-A")
        self.mgr.append("call-A", _sine_pcm16())
        posted: list = []
        statuses = iter([None, None, "ACTIVE"])
        with (
            mock.patch.object(
                pipeline_driver,
                "_b4_get_status",
                side_effect=lambda base, call: next(statuses, "ACTIVE"),
            ),
            mock.patch.object(
                pipeline_driver,
                "_b4_post_chunk",
                side_effect=lambda base, call, payload: posted.append(payload)
                or {"risk": 10.0, "timestamp": 0.0},
            ),
            mock.patch.object(pipeline_driver, "STATUS_POLL_S", 0.05),
            mock.patch.object(pipeline_driver, "IDLE_SLEEP_S", 0.01),
        ):
            task = asyncio.get_running_loop().create_task(worker.run())
            await asyncio.sleep(0.4)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0]["session_id"], "call-A")


class TestRespawnCooloff(DriverHarness):
    async def test_unknown_call_suppresses_respawn_within_cooloff(self):
        pipeline_driver._note_unknown("ghost-1")
        mgr = SessionBufferManager()
        self.assertIsNone(pipeline_driver.ensure_worker("ghost-1", mgr))

    async def test_cooloff_expires(self):
        with mock.patch.object(pipeline_driver, "UNKNOWN_COOLOFF_S", -1.0):
            pipeline_driver._note_unknown("ghost-2")
            self.assertFalse(pipeline_driver._in_cooloff("ghost-2"))
        # Expired: a fresh worker may start again.
        worker = pipeline_driver.ensure_worker("ghost-2", self.mgr)
        self.assertIsNotNone(worker)
        if worker is not None and worker.task is not None:
            worker.task.cancel()
            try:
                await worker.task
            except asyncio.CancelledError:
                pass
            pipeline_driver._workers.pop("ghost-2", None)

    async def test_stop_session_clears_cooloff(self):
        pipeline_driver._note_unknown("ghost-3")
        self.assertTrue(pipeline_driver._in_cooloff("ghost-3"))
        await pipeline_driver.stop_session("ghost-3", flush=False)
        self.assertFalse(pipeline_driver._in_cooloff("ghost-3"))

    async def test_dead_worker_respawns(self):
        worker = self.make_worker("call-Z")
        worker.running = False
        worker.task = None
        pipeline_driver._workers["call-Z"] = worker
        fresh = pipeline_driver.ensure_worker("call-Z", self.mgr)
        self.assertIsNotNone(fresh)
        self.assertIsNot(fresh, worker)
        if fresh is not None and fresh.task is not None:
            fresh.task.cancel()
            try:
                await fresh.task
            except asyncio.CancelledError:
                pass
            pipeline_driver._workers.pop("call-Z", None)


class TestSystemStatusView(unittest.TestCase):
    def test_view_returns_200_ok_shape(self):
        from backend.api import get_call_service
        from backend.call_service import view_system_status

        status, body = view_system_status(get_call_service())
        self.assertEqual(status, 200)
        self.assertIsInstance(body, dict)
        self.assertEqual(body.get("status"), "ok")
        for key in (
            "backend", "b3_detector_version", "b3_embedder_version",
            "b3_is_mock", "b4_is_mock", "active_calls", "transport",
            "database", "authentication", "environment", "storage_backend",
        ):
            self.assertIn(key, body)


if __name__ == "__main__":
    unittest.main()
