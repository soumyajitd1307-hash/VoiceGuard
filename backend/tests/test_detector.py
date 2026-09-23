"""Tests for Backend 3 Part 1: synthetic voice detection.

Stdlib unittest only (no pytest dependency).

These tests assert plumbing, schemas and failure handling -- NOT
scientific accuracy. The wired model is the development/mock heuristic
(see backend/models/mock_model.py); no test here claims it detects
real spoofs.
"""
from __future__ import annotations

import math
import unittest
from unittest import mock

from backend.b2_contract import ProcessedSpeechChunk
from backend.config import Settings
from backend.detector import SyntheticVoiceDetector, get_detector, reset_detector
from backend.models.registry import reset_model_registry
from backend.schemas import DetectionResult, ModelError, ValidationError


def _settings(**overrides) -> Settings:
    params = dict(
        model_name="mock",
        model_version="mock-heuristic-v0.1.0",
        synthetic_threshold=0.7,
        real_threshold=0.3,
        min_duration_s=0.25,
        max_duration_s=30.0,
        max_id_length=128,
        log_level="CRITICAL",
    )
    params.update(overrides)
    return Settings(**params)


def _speech_floats(n: int = 8000) -> list:
    # 0.5s deterministic 440Hz tone at 16kHz; content is arbitrary --
    # tests only assert range/schema behaviour, never detection quality.
    return [0.5 * math.sin(2.0 * math.pi * 440.0 * i / 16000) for i in range(n)]


def _chunk(**overrides) -> ProcessedSpeechChunk:
    params = dict(
        audio=_speech_floats(),
        sample_rate=16000,
        session_id="1042",
        chunk_id="c0018",
        timestamp_s=18.0,
        language="en",
        is_speech=True,
        speech_ratio=0.92,
    )
    params.update(overrides)
    return ProcessedSpeechChunk(**params)


class TestSyntheticVoiceDetector(unittest.TestCase):
    def setUp(self):
        reset_model_registry()
        reset_detector()

    def tearDown(self):
        reset_model_registry()
        reset_detector()

    def test_valid_chunk_returns_result(self):
        detector = SyntheticVoiceDetector(_settings())
        result = detector.detect_chunk(_chunk())
        self.assertIsInstance(result, DetectionResult)
        self.assertEqual(result.session_id, "1042")
        self.assertEqual(result.chunk_id, "c0018")
        self.assertIn(result.label, ("real", "synthetic", "uncertain"))

    def test_invalid_sample_rate(self):
        detector = SyntheticVoiceDetector(_settings())
        with self.assertRaises(ValidationError):
            detector.detect_chunk(_chunk(sample_rate=12345))

    def test_empty_audio(self):
        detector = SyntheticVoiceDetector(_settings())
        with self.assertRaises(ValidationError):
            detector.detect_chunk(_chunk(audio=[]))

    def test_invalid_session_and_chunk_ids(self):
        detector = SyntheticVoiceDetector(_settings())
        with self.assertRaises(ValidationError):
            detector.detect_chunk(_chunk(session_id="   "))
        with self.assertRaises(ValidationError):
            detector.detect_chunk(_chunk(chunk_id=""))

    def test_probability_range(self):
        detector = SyntheticVoiceDetector(_settings())
        for audio in (
            [0.0] * 8000,                       # silence
            _speech_floats(),                   # tone
            [0.9 if i % 2 else -0.9 for i in range(8000)],  # square-ish
        ):
            result = detector.detect_chunk(_chunk(audio=audio))
            self.assertGreaterEqual(result.synthetic_probability, 0.0)
            self.assertLessEqual(result.synthetic_probability, 1.0)

    def test_result_schema(self):
        detector = SyntheticVoiceDetector(_settings())
        result = detector.detect_chunk(_chunk())
        payload = result.to_dict()
        self.assertEqual(
            set(payload),
            {
                "label", "synthetic_probability", "model_version",
                "processing_time_ms", "session_id", "chunk_id", "is_mock",
            },
        )
        self.assertIsInstance(payload["synthetic_probability"], float)
        self.assertIsInstance(payload["processing_time_ms"], float)
        self.assertGreaterEqual(payload["processing_time_ms"], 0.0)

    def test_detector_initialization_loads_model_once(self):
        settings = _settings()
        first = SyntheticVoiceDetector(settings)
        second = SyntheticVoiceDetector(settings)
        # Singleton behind both instances: same object, loaded exactly once.
        self.assertIs(first.model, second.model)
        self.assertEqual(first.model.load_count, 1)
        self.assertEqual(first.model_version, "mock-heuristic-v0.1.0")
        # Process-wide convenience accessor is also a singleton.
        self.assertIs(get_detector(), get_detector())

    def test_model_inference_failure_raises_model_error(self):
        detector = SyntheticVoiceDetector(_settings())
        with mock.patch.object(
            detector.model, "predict_proba", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(ModelError):
                detector.detect_chunk(_chunk())

    def test_mock_implementation_is_explicitly_labeled(self):
        detector = SyntheticVoiceDetector(_settings())
        self.assertTrue(detector.is_mock)
        self.assertTrue(detector.model.is_mock)
        result = detector.detect_chunk(_chunk())
        self.assertTrue(result.is_mock)

    def test_non_speech_chunk_is_skipped(self):
        detector = SyntheticVoiceDetector(_settings())
        with self.assertRaises(ValidationError):
            detector.detect_chunk(_chunk(is_speech=False, speech_ratio=0.05))

    def test_wire_dict_input_accepted(self):
        import base64

        raw = (int(1000).to_bytes(2, byteorder="little", signed=True)) * 8000
        detector = SyntheticVoiceDetector(_settings())
        result = detector.detect_chunk(
            {
                "audio_base64": base64.b64encode(raw).decode("ascii"),
                "audio_encoding": "pcm16_base64",
                "sample_rate": 16000,
                "session_id": "1042",
                "chunk_id": "c0018",
                "timestamp_s": 18.0,
                "language": "en",
                "is_speech": True,
                "speech_ratio": 0.92,
            }
        )
        self.assertEqual(result.session_id, "1042")

    def test_malformed_chunk_raises_validation_error(self):
        detector = SyntheticVoiceDetector(_settings())
        with self.assertRaises(ValidationError):
            detector.detect_chunk(None)  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            detector.detect_chunk({"sample_rate": 16000})  # missing IDs/audio


if __name__ == "__main__":
    unittest.main()
