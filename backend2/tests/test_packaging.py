"""Unit tests for Backend 2 packaging layer (backend2/packaging.py).

Verifies packaging PreprocessedAudioWindow and VADResult into Backend 3
ProcessedSpeechChunk, contract compliance, immutability, determinism, and validation.
"""
from __future__ import annotations

import unittest

from backend.b2_contract import ProcessedSpeechChunk, validate_chunk
from backend.schemas import ValidationError
from backend2.packaging import build_processed_speech_chunk
from backend2.preprocessing import PreprocessedAudioWindow
from backend2.vad import VADResult


def _make_window(
    session_id: str = "sess-1042",
    sample_rate: int = 16000,
    n_samples: int = 16000,
    sample_val: float = 0.05,
) -> PreprocessedAudioWindow:
    """Helper to construct a valid PreprocessedAudioWindow."""
    samples = tuple([sample_val] * n_samples)
    raw_pcm = (int(sample_val * 32768.0).to_bytes(2, "little", signed=True)) * n_samples
    duration_s = n_samples / sample_rate
    return PreprocessedAudioWindow(
        session_id=session_id,
        raw_bytes=raw_pcm,
        samples=samples,
        sample_rate=sample_rate,
        duration_s=duration_s,
        num_samples=n_samples,
    )


class TestPackaging(unittest.TestCase):
    def test_normal_speech_window_packaging(self):
        window = _make_window(session_id="user-1042", sample_rate=16000, n_samples=16000)
        vad = VADResult(is_speech=True, speech_ratio=0.85, speech_frames=34, total_frames=40)

        chunk = build_processed_speech_chunk(
            window=window,
            vad_result=vad,
            chunk_id="chunk-001",
            timestamp_s=12.5,
            language="en",
        )

        self.assertIsInstance(chunk, ProcessedSpeechChunk)
        self.assertEqual(chunk.session_id, "user-1042")
        self.assertEqual(chunk.chunk_id, "chunk-001")
        self.assertEqual(chunk.sample_rate, 16000)
        self.assertEqual(chunk.audio, window.samples)
        self.assertEqual(chunk.audio_encoding, "auto")
        self.assertEqual(chunk.timestamp_s, 12.5)
        self.assertEqual(chunk.language, "en")
        self.assertTrue(chunk.is_speech)
        self.assertTrue(chunk.is_speech_ready)
        self.assertEqual(chunk.speech_ratio, 0.85)
        self.assertAlmostEqual(chunk.duration_s(), 1.0)

    def test_silence_window_packaging(self):
        window = _make_window(session_id="user-silence", n_samples=16000, sample_val=0.0)
        vad = VADResult(is_speech=False, speech_ratio=0.0, speech_frames=0, total_frames=40)

        chunk = build_processed_speech_chunk(
            window=window,
            vad_result=vad,
            chunk_id="chunk-silence",
            timestamp_s=0.0,
        )

        self.assertFalse(chunk.is_speech)
        self.assertFalse(chunk.is_speech_ready)
        self.assertEqual(chunk.speech_ratio, 0.0)
        self.assertIsNone(chunk.language)

    def test_mixed_speech_silence_exact_ratio(self):
        window = _make_window(n_samples=16000)
        vad = VADResult(is_speech=True, speech_ratio=0.425, speech_frames=17, total_frames=40)

        chunk = build_processed_speech_chunk(
            window=window,
            vad_result=vad,
            chunk_id="chunk-mixed",
        )

        self.assertTrue(chunk.is_speech)
        self.assertEqual(chunk.speech_ratio, 0.425)

    def test_audio_encoding_default_and_validation(self):
        window = _make_window()
        vad = VADResult(is_speech=True, speech_ratio=0.9, speech_frames=36, total_frames=40)

        chunk = build_processed_speech_chunk(
            window=window,
            vad_result=vad,
            chunk_id="c1",
            audio_encoding="auto",
        )
        self.assertEqual(chunk.audio_encoding, "auto")

        with self.assertRaises(ValidationError):
            build_processed_speech_chunk(
                window=window,
                vad_result=vad,
                chunk_id="c1",
                audio_encoding="invalid_encoding",
            )

    def test_invalid_chunk_id_rejected(self):
        window = _make_window()
        vad = VADResult(is_speech=True, speech_ratio=0.9, speech_frames=36, total_frames=40)

        for bad_id in ["", "   ", None, 123, "a" * 129]:
            with self.assertRaises(ValidationError):
                build_processed_speech_chunk(
                    window=window,
                    vad_result=vad,
                    chunk_id=bad_id,  # type: ignore[arg-type]
                )

    def test_invalid_timestamp_rejected(self):
        window = _make_window()
        vad = VADResult(is_speech=True, speech_ratio=0.9, speech_frames=36, total_frames=40)

        for bad_ts in [-1.0, -0.001, float("inf"), float("nan"), "10.0"]:
            with self.assertRaises(ValidationError):
                build_processed_speech_chunk(
                    window=window,
                    vad_result=vad,
                    chunk_id="c1",
                    timestamp_s=bad_ts,  # type: ignore[arg-type]
                )

    def test_invalid_input_types_rejected(self):
        window = _make_window()
        vad = VADResult(is_speech=True, speech_ratio=0.9, speech_frames=36, total_frames=40)

        with self.assertRaises(TypeError):
            build_processed_speech_chunk(
                window="not_a_window",  # type: ignore[arg-type]
                vad_result=vad,
                chunk_id="c1",
            )

        with self.assertRaises(TypeError):
            build_processed_speech_chunk(
                window=window,
                vad_result="not_a_vad_result",  # type: ignore[arg-type]
                chunk_id="c1",
            )

    def test_passes_existing_b3_validate_chunk(self):
        window = _make_window(session_id="contract-test", n_samples=16000)
        vad = VADResult(is_speech=True, speech_ratio=0.8, speech_frames=32, total_frames=40)

        # Build with validate=True (internal validation)
        chunk = build_processed_speech_chunk(
            window=window,
            vad_result=vad,
            chunk_id="chk-valid",
            timestamp_s=2.5,
            language="en",
            validate=True,
        )

        # Independently pass through B3 validate_chunk again
        verified = validate_chunk(chunk)
        self.assertEqual(verified, chunk)

    def test_immutability_and_no_mutation(self):
        window = _make_window(session_id="orig-sess", n_samples=16000)
        vad = VADResult(is_speech=True, speech_ratio=0.75, speech_frames=30, total_frames=40)

        samples_before = window.samples
        raw_bytes_before = window.raw_bytes

        chunk = build_processed_speech_chunk(
            window=window,
            vad_result=vad,
            chunk_id="c-immut",
        )

        # Ensure original window and vad_result were not mutated
        self.assertIs(window.samples, samples_before)
        self.assertIs(window.raw_bytes, raw_bytes_before)
        self.assertEqual(vad.is_speech, True)
        self.assertEqual(vad.speech_ratio, 0.75)

        # Ensure chunk is frozen dataclass
        with self.assertRaises((AttributeError, TypeError)):
            chunk.chunk_id = "new-id"  # type: ignore[misc]

    def test_determinism(self):
        window = _make_window(session_id="det-sess", n_samples=16000)
        vad = VADResult(is_speech=True, speech_ratio=0.6, speech_frames=24, total_frames=40)

        chunk1 = build_processed_speech_chunk(
            window=window,
            vad_result=vad,
            chunk_id="c-det",
            timestamp_s=1.0,
            language="en",
        )
        chunk2 = build_processed_speech_chunk(
            window=window,
            vad_result=vad,
            chunk_id="c-det",
            timestamp_s=1.0,
            language="en",
        )

        self.assertEqual(chunk1, chunk2)
        self.assertEqual(chunk1.to_detect_kwargs(), chunk2.to_detect_kwargs())
        self.assertEqual(chunk1.to_dict(), chunk2.to_dict())


if __name__ == "__main__":
    unittest.main()
