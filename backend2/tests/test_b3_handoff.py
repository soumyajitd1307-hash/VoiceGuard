"""Unit tests for Backend 2 -> Backend 3 handoff adapter (backend2/b3_handoff.py).

Tests ProcessedSpeechChunk forwarding to the real existing Backend 3
pipeline and detector, result propagation, error handling, and immutability.
"""
from __future__ import annotations

import math
import unittest
from unittest import mock

from backend.b2_contract import ProcessedSpeechChunk
from backend.detector import SyntheticVoiceDetector, reset_detector
from backend.models.registry import reset_model_registry
from backend.pipeline import Backend3Pipeline, reset_pipeline
from backend.schemas import Backend3Signals, DetectionResult, ModelError, ValidationError
from backend2.b3_handoff import detect_with_b3, handoff_to_b3


def _speech_floats(n: int = 16000) -> tuple[float, ...]:
    """1.0s deterministic 440 Hz tone at 16 kHz."""
    return tuple(0.5 * math.sin(2.0 * math.pi * 440.0 * i / 16000) for i in range(n))


def _valid_chunk(**overrides) -> ProcessedSpeechChunk:
    params = dict(
        audio=_speech_floats(),
        sample_rate=16000,
        session_id="user-1042",
        chunk_id="c0001",
        audio_encoding="auto",
        timestamp_s=0.0,
        language="en",
        is_speech=True,
        speech_ratio=0.85,
    )
    params.update(overrides)
    return ProcessedSpeechChunk(**params)


class TestB3Handoff(unittest.TestCase):
    def setUp(self):
        reset_model_registry()
        reset_detector()
        reset_pipeline()

    def tearDown(self):
        reset_model_registry()
        reset_detector()
        reset_pipeline()

    def test_valid_chunk_reaches_b3_pipeline(self):
        chunk = _valid_chunk()
        bundle = handoff_to_b3(chunk)

        self.assertIsInstance(bundle, Backend3Signals)
        self.assertEqual(bundle.session_id, "user-1042")
        self.assertEqual(bundle.chunk_id, "c0001")
        self.assertIsNotNone(bundle.synthetic)
        assert bundle.synthetic is not None
        self.assertIn(bundle.synthetic.label, ("real", "synthetic", "uncertain"))
        self.assertIsInstance(bundle.synthetic.synthetic_probability, float)
        self.assertIsNotNone(bundle.speaker)
        self.assertIsNone(bundle.similarity)

    def test_valid_chunk_reaches_b3_detector(self):
        chunk = _valid_chunk()
        result = detect_with_b3(chunk)

        self.assertIsInstance(result, DetectionResult)
        self.assertEqual(result.session_id, "user-1042")
        self.assertEqual(result.chunk_id, "c0001")
        self.assertIn(result.label, ("real", "synthetic", "uncertain"))
        self.assertGreaterEqual(result.synthetic_probability, 0.0)
        self.assertLessEqual(result.synthetic_probability, 1.0)
        self.assertTrue(result.is_mock)

    def test_handoff_with_reference_embedding(self):
        chunk = _valid_chunk()
        # Reference embedding of dimension 32 (matching mock spectral embedder)
        ref_vec = [0.1] * 32
        bundle = handoff_to_b3(chunk, reference_embedding=ref_vec, reference_id="usr-1042")

        self.assertIsNotNone(bundle.similarity)
        assert bundle.similarity is not None
        self.assertEqual(bundle.similarity.reference_id, "usr-1042")
        self.assertIsInstance(bundle.similarity.similarity, float)

    def test_invalid_type_raises_type_error(self):
        with self.assertRaises(TypeError):
            handoff_to_b3("not_a_chunk")  # type: ignore[arg-type]

        with self.assertRaises(TypeError):
            detect_with_b3({"session_id": "1042"})  # type: ignore[arg-type]

    def test_non_speech_chunk_rejected_by_b3_vad_policy(self):
        # B3 explicitly declines non-speech chunks (is_speech=False) with ValidationError
        non_speech_chunk = _valid_chunk(is_speech=False, speech_ratio=0.0)

        with self.assertRaises(ValidationError) as ctx:
            handoff_to_b3(non_speech_chunk)
        self.assertIn("non-speech", str(ctx.exception).lower())

        with self.assertRaises(ValidationError) as ctx:
            detect_with_b3(non_speech_chunk)
        self.assertIn("non-speech", str(ctx.exception).lower())

    def test_invalid_metadata_rejected_by_validation(self):
        bad_chunk = _valid_chunk(session_id="   ")
        with self.assertRaises(ValidationError):
            handoff_to_b3(bad_chunk)

        bad_rate = _valid_chunk(sample_rate=12345)
        with self.assertRaises(ValidationError):
            detect_with_b3(bad_rate)

    def test_model_errors_not_swallowed(self):
        chunk = _valid_chunk()
        mock_pipeline = mock.create_autospec(Backend3Pipeline, instance=True)
        mock_pipeline.process_chunk.side_effect = ModelError("inference timeout")

        with self.assertRaises(ModelError):
            handoff_to_b3(chunk, pipeline=mock_pipeline)

        mock_detector = mock.create_autospec(SyntheticVoiceDetector, instance=True)
        mock_detector.detect_chunk.side_effect = ModelError("weights missing")

        with self.assertRaises(ModelError):
            detect_with_b3(chunk, detector=mock_detector)

    def test_no_audio_samples_modified(self):
        original_audio = _speech_floats()
        chunk = _valid_chunk(audio=original_audio)

        handoff_to_b3(chunk)
        # Verify chunk audio identity and contents were untouched
        self.assertIs(chunk.audio, original_audio)
        self.assertEqual(chunk.audio[0], original_audio[0])

    def test_deterministic_repeated_calls(self):
        chunk = _valid_chunk()
        res1 = detect_with_b3(chunk)
        res2 = detect_with_b3(chunk)

        self.assertEqual(res1.label, res2.label)
        self.assertAlmostEqual(res1.synthetic_probability, res2.synthetic_probability, places=4)
        self.assertEqual(res1.session_id, res2.session_id)
        self.assertEqual(res1.chunk_id, res2.chunk_id)

    def test_custom_injected_pipeline_called_with_exact_chunk(self):
        chunk = _valid_chunk()
        mock_pipeline = mock.create_autospec(Backend3Pipeline, instance=True)
        expected_signals = Backend3Signals(session_id="user-1042", chunk_id="c0001")
        mock_pipeline.process_chunk.return_value = expected_signals

        result = handoff_to_b3(chunk, pipeline=mock_pipeline, reference_id="prof-1")

        self.assertIs(result, expected_signals)
        mock_pipeline.process_chunk.assert_called_once_with(
            chunk,
            reference_embedding=None,
            reference_id="prof-1",
        )


if __name__ == "__main__":
    unittest.main()
