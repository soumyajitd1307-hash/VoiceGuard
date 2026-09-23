"""Unit tests for Backend 2 audio preprocessing and window extraction.

Tests validation rules, PCM16 conversion, window extraction from SessionBufferManager,
and boundary conditions.
"""
from __future__ import annotations

import unittest

from backend2.buffer import (
    InvalidSessionError,
    SessionBufferManager,
)
from backend2.preprocessing import (
    AudioValidationError,
    PreprocessedAudioWindow,
    extract_audio_window,
    preprocess_pcm16,
    validate_pcm16_audio,
)


def _make_pcm16_bytes(sample_values: list[int]) -> bytes:
    """Helper to generate little-endian 16-bit signed PCM bytes."""
    data = bytearray()
    for val in sample_values:
        data.extend(int(val).to_bytes(2, byteorder="little", signed=True))
    return bytes(data)


def _make_constant_pcm16(value: int, num_samples: int) -> bytes:
    """Helper to generate uniform PCM16 bytes of given sample length."""
    sample_bytes = int(value).to_bytes(2, byteorder="little", signed=True)
    return sample_bytes * num_samples


class TestPreprocessPCM16(unittest.TestCase):
    def test_valid_preprocessing_1s_16khz(self):
        # 16,000 samples = 32,000 bytes
        raw_pcm = _make_constant_pcm16(value=1000, num_samples=16000)
        self.assertEqual(len(raw_pcm), 32000)

        window = preprocess_pcm16(
            raw_bytes=raw_pcm,
            session_id="session-1042",
            sample_rate=16000,
        )

        self.assertIsInstance(window, PreprocessedAudioWindow)
        self.assertEqual(window.session_id, "session-1042")
        self.assertEqual(window.sample_rate, 16000)
        self.assertEqual(window.num_samples, 16000)
        self.assertEqual(len(window.raw_bytes), 32000)
        self.assertEqual(window.raw_bytes, raw_pcm)
        self.assertEqual(len(window.samples), 16000)
        self.assertAlmostEqual(window.duration_s, 1.0, places=4)
        self.assertAlmostEqual(window.samples[0], 1000 / 32768.0, places=5)

    def test_pcm16_conversion_boundary_values(self):
        # Test extreme and midpoint PCM16 values: -32768, 0, 32767
        # Need at least 0.25s of audio to satisfy duration bounds (4000 samples at 16kHz)
        boundary_samples = [-32768, 0, 32767] + [0] * 3997
        raw_pcm = _make_pcm16_bytes(boundary_samples)

        window = preprocess_pcm16(
            raw_bytes=raw_pcm,
            session_id="test-boundary",
            sample_rate=16000,
        )

        self.assertEqual(len(window.samples), 4000)
        # -32768 / 32768.0 = -1.0
        self.assertEqual(window.samples[0], -1.0)
        # 0 / 32768.0 = 0.0
        self.assertEqual(window.samples[1], 0.0)
        # 32767 / 32768.0 = 0.999969482421875
        self.assertAlmostEqual(window.samples[2], 32767 / 32768.0, places=5)

    def test_invalid_odd_byte_count(self):
        # 8001 bytes is odd
        odd_bytes = b"\x00" * 8001
        with self.assertRaises(AudioValidationError) as ctx:
            validate_pcm16_audio(odd_bytes, sample_rate=16000)
        self.assertIn("even", str(ctx.exception).lower())

        with self.assertRaises(AudioValidationError):
            preprocess_pcm16(odd_bytes, session_id="sess-odd")

    def test_invalid_empty_input(self):
        with self.assertRaises(AudioValidationError) as ctx:
            validate_pcm16_audio(b"", sample_rate=16000)
        self.assertIn("empty", str(ctx.exception).lower())

    def test_invalid_non_bytes_input(self):
        with self.assertRaises(AudioValidationError):
            validate_pcm16_audio([0, 1, 2], sample_rate=16000)  # type: ignore[arg-type]

    def test_unsupported_sample_rate(self):
        raw_pcm = _make_constant_pcm16(0, 4000)
        with self.assertRaises(AudioValidationError) as ctx:
            validate_pcm16_audio(raw_pcm, sample_rate=12345)
        self.assertIn("Unsupported sample_rate", str(ctx.exception))

    def test_shorter_than_b3_minimum(self):
        # B3 min duration is 0.25s (4000 samples @ 16kHz = 8000 bytes)
        # 3999 samples = 0.2499375s < 0.25s
        too_short = _make_constant_pcm16(0, 3999)
        with self.assertRaises(AudioValidationError) as ctx:
            validate_pcm16_audio(too_short, sample_rate=16000)
        self.assertIn("too short", str(ctx.exception).lower())

    def test_longer_than_b3_maximum(self):
        # B3 max duration is 30.0s (480,000 samples @ 16kHz = 960,000 bytes)
        # 480,001 samples > 30.0s
        too_long = _make_constant_pcm16(0, 480001)
        with self.assertRaises(AudioValidationError) as ctx:
            validate_pcm16_audio(too_long, sample_rate=16000)
        self.assertIn("too long", str(ctx.exception).lower())

    def test_invalid_session_id(self):
        raw_pcm = _make_constant_pcm16(0, 16000)
        with self.assertRaises(InvalidSessionError):
            preprocess_pcm16(raw_pcm, session_id="")

        with self.assertRaises(InvalidSessionError):
            preprocess_pcm16(raw_pcm, session_id="   ")

        with self.assertRaises(InvalidSessionError):
            preprocess_pcm16(raw_pcm, session_id=None)  # type: ignore[arg-type]


class TestExtractAudioWindow(unittest.TestCase):
    def setUp(self):
        self.mgr = SessionBufferManager(max_bytes_per_session=1_000_000)

    def tearDown(self):
        self.mgr.clear_all()

    def test_extract_window_4_frames_to_1s(self):
        session_id = "sess-window-1s"
        # Simulate 4 incoming 250ms frames (8000 bytes each)
        frame_0 = _make_constant_pcm16(100, 4000)
        frame_1 = _make_constant_pcm16(200, 4000)
        frame_2 = _make_constant_pcm16(300, 4000)
        frame_3 = _make_constant_pcm16(400, 4000)

        self.mgr.append(session_id, frame_0)
        self.mgr.append(session_id, frame_1)
        self.mgr.append(session_id, frame_2)

        # After 3 frames (24,000 bytes = 0.75s), insufficient for 1.0s window
        self.assertEqual(self.mgr.get_size(session_id), 24000)
        window = extract_audio_window(self.mgr, session_id, window_duration_s=1.0)
        self.assertIsNone(window)
        # Verify buffer was NOT drained or modified
        self.assertEqual(self.mgr.get_size(session_id), 24000)

        # Append 4th frame (total 32,000 bytes = 1.0s)
        self.mgr.append(session_id, frame_3)
        self.assertEqual(self.mgr.get_size(session_id), 32000)

        # Now extraction succeeds
        window = extract_audio_window(self.mgr, session_id, window_duration_s=1.0)
        self.assertIsNotNone(window)
        assert window is not None  # type narrowing
        self.assertEqual(window.num_samples, 16000)
        self.assertEqual(len(window.raw_bytes), 32000)
        self.assertAlmostEqual(window.duration_s, 1.0, places=4)
        # Buffer should now be empty
        self.assertEqual(self.mgr.get_size(session_id), 0)

        # Verify FIFO order across the 4 frames
        self.assertAlmostEqual(window.samples[0], 100 / 32768.0, places=5)
        self.assertAlmostEqual(window.samples[4000], 200 / 32768.0, places=5)
        self.assertAlmostEqual(window.samples[8000], 300 / 32768.0, places=5)
        self.assertAlmostEqual(window.samples[12000], 400 / 32768.0, places=5)

    def test_successive_windows_continuous_extraction(self):
        session_id = "sess-continuous"
        # Stream 8 frames (2 complete 1.0s windows)
        for i in range(8):
            frame = _make_constant_pcm16(value=(i + 1) * 1000, num_samples=4000)
            self.mgr.append(session_id, frame)

        self.assertEqual(self.mgr.get_size(session_id), 64000)

        # Window 1 (frames 0, 1, 2, 3)
        win1 = extract_audio_window(self.mgr, session_id, window_duration_s=1.0)
        self.assertIsNotNone(win1)
        assert win1 is not None
        self.assertEqual(len(win1.raw_bytes), 32000)
        self.assertAlmostEqual(win1.samples[0], 1000 / 32768.0, places=5)
        self.assertEqual(self.mgr.get_size(session_id), 32000)

        # Window 2 (frames 4, 5, 6, 7)
        win2 = extract_audio_window(self.mgr, session_id, window_duration_s=1.0)
        self.assertIsNotNone(win2)
        assert win2 is not None
        self.assertEqual(len(win2.raw_bytes), 32000)
        self.assertAlmostEqual(win2.samples[0], 5000 / 32768.0, places=5)
        self.assertEqual(self.mgr.get_size(session_id), 0)

        # Window 3 (no data left)
        win3 = extract_audio_window(self.mgr, session_id, window_duration_s=1.0)
        self.assertIsNone(win3)

    def test_session_isolation_in_window_extraction(self):
        # 1s for user-A, 0.5s for user-B
        pcm_a = _make_constant_pcm16(500, 16000)
        pcm_b = _make_constant_pcm16(900, 8000)

        self.mgr.append("user-A", pcm_a)
        self.mgr.append("user-B", pcm_b)

        win_a = extract_audio_window(self.mgr, "user-A", window_duration_s=1.0)
        self.assertIsNotNone(win_a)
        assert win_a is not None
        self.assertEqual(win_a.session_id, "user-A")
        self.assertEqual(self.mgr.get_size("user-A"), 0)

        # user-B only has 0.5s, should return None for 1.0s window
        win_b = extract_audio_window(self.mgr, "user-B", window_duration_s=1.0)
        self.assertIsNone(win_b)
        self.assertEqual(self.mgr.get_size("user-B"), 16000)

    def test_invalid_window_duration(self):
        with self.assertRaises(AudioValidationError):
            extract_audio_window(self.mgr, "user-A", window_duration_s=0.0)

        with self.assertRaises(AudioValidationError):
            extract_audio_window(self.mgr, "user-A", window_duration_s=-1.0)


if __name__ == "__main__":
    unittest.main()
