"""Unit tests for Backend 2 Voice Activity Detection (backend2/vad.py).

Verifies sub-frame RMS energy calculations, speech_ratio precision,
is_speech thresholding, and acoustic edge cases.
"""
from __future__ import annotations

import math
import unittest

from backend2.vad import (
    VADResult,
    compute_frame_rms,
    compute_vad,
)


def _generate_tone(amplitude: float, freq_hz: float, n_samples: int, sample_rate: int = 16000) -> list[float]:
    """Generate pure sinusoidal samples."""
    return [
        amplitude * math.sin(2.0 * math.pi * freq_hz * i / sample_rate)
        for i in range(n_samples)
    ]


class TestComputeFrameRMS(unittest.TestCase):
    def test_empty_frame(self):
        self.assertEqual(compute_frame_rms([]), 0.0)

    def test_zero_samples(self):
        self.assertEqual(compute_frame_rms([0.0] * 400), 0.0)

    def test_constant_value(self):
        # RMS of constant c is abs(c)
        self.assertAlmostEqual(compute_frame_rms([0.5] * 400), 0.5)
        self.assertAlmostEqual(compute_frame_rms([-0.25] * 400), 0.25)

    def test_sine_wave_rms(self):
        # RMS of A * sin(x) is A / sqrt(2) approx 0.7071 * A
        sine_samples = _generate_tone(amplitude=0.5, freq_hz=400, n_samples=16000)
        expected_rms = 0.5 / math.sqrt(2.0)
        self.assertAlmostEqual(compute_frame_rms(sine_samples), expected_rms, places=3)


class TestComputeVAD(unittest.TestCase):
    def test_complete_silence_all_zeros(self):
        # 16,000 zeros = 1.0 second of silence
        samples = [0.0] * 16000
        res = compute_vad(samples, sample_rate=16000)

        self.assertIsInstance(res, VADResult)
        self.assertFalse(res.is_speech)
        self.assertEqual(res.speech_ratio, 0.0)
        self.assertEqual(res.speech_frames, 0)
        self.assertEqual(res.total_frames, 40)  # 16000 / 400 = 40 frames

    def test_empty_samples(self):
        res = compute_vad([], sample_rate=16000)
        self.assertFalse(res.is_speech)
        self.assertEqual(res.speech_ratio, 0.0)
        self.assertEqual(res.speech_frames, 0)
        self.assertEqual(res.total_frames, 0)

    def test_continuous_speech_full_window(self):
        # 1.0s of continuous active speech (~400 Hz tone, amplitude 0.2 -> RMS ~ 0.141 >> 0.015)
        samples = _generate_tone(amplitude=0.2, freq_hz=400, n_samples=16000)
        res = compute_vad(samples, sample_rate=16000)

        self.assertTrue(res.is_speech)
        self.assertEqual(res.speech_ratio, 1.0)
        self.assertEqual(res.speech_frames, 40)
        self.assertEqual(res.total_frames, 40)

    def test_intermittent_speech_above_threshold(self):
        # 12 frames of speech (300 ms = 4800 samples) and 28 frames of silence (700 ms = 11200 samples)
        # speech_ratio = 12 / 40 = 0.30 >= 0.25 (min_speech_ratio) -> is_speech = True
        speech_part = _generate_tone(amplitude=0.2, freq_hz=400, n_samples=4800)
        silence_part = [0.0] * 11200
        samples = speech_part + silence_part

        res = compute_vad(samples, sample_rate=16000, min_speech_ratio=0.25)

        self.assertTrue(res.is_speech)
        self.assertAlmostEqual(res.speech_ratio, 0.30, places=4)
        self.assertEqual(res.speech_frames, 12)
        self.assertEqual(res.total_frames, 40)

    def test_brief_speech_below_threshold(self):
        # 4 frames of speech (100 ms = 1600 samples) and 36 frames of silence (900 ms = 14400 samples)
        # speech_ratio = 4 / 40 = 0.10 < 0.25 -> is_speech = False
        speech_part = _generate_tone(amplitude=0.2, freq_hz=400, n_samples=1600)
        silence_part = [0.0] * 14400
        samples = speech_part + silence_part

        res = compute_vad(samples, sample_rate=16000, min_speech_ratio=0.25)

        self.assertFalse(res.is_speech)
        self.assertAlmostEqual(res.speech_ratio, 0.10, places=4)
        self.assertEqual(res.speech_frames, 4)
        self.assertEqual(res.total_frames, 40)

    def test_very_quiet_noise_below_energy_threshold(self):
        # Continuous very low amplitude noise (amplitude 0.005 -> RMS ~ 0.0035 < 0.015)
        quiet_noise = [0.005] * 16000
        res = compute_vad(quiet_noise, sample_rate=16000, energy_threshold=0.015)

        self.assertFalse(res.is_speech)
        self.assertEqual(res.speech_ratio, 0.0)
        self.assertEqual(res.speech_frames, 0)
        self.assertEqual(res.total_frames, 40)

    def test_custom_frame_duration(self):
        # 20 ms frame duration at 16 kHz = 320 samples per frame -> 50 frames per 16,000 samples
        samples = _generate_tone(amplitude=0.2, freq_hz=400, n_samples=16000)
        res = compute_vad(samples, sample_rate=16000, frame_duration_ms=20)

        self.assertEqual(res.total_frames, 50)
        self.assertEqual(res.speech_frames, 50)
        self.assertEqual(res.speech_ratio, 1.0)
        self.assertTrue(res.is_speech)

    def test_invalid_parameters_raise(self):
        with self.assertRaises(ValueError):
            compute_vad([0.0] * 100, sample_rate=0)
        with self.assertRaises(ValueError):
            compute_vad([0.0] * 100, frame_duration_ms=0)
        with self.assertRaises(ValueError):
            compute_vad([0.0] * 100, energy_threshold=-0.1)
        with self.assertRaises(ValueError):
            compute_vad([0.0] * 100, min_speech_ratio=1.5)
        with self.assertRaises(ValueError):
            compute_vad([0.0] * 100, min_speech_ratio=-0.05)


if __name__ == "__main__":
    unittest.main()
