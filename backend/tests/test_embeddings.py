"""Tests for Backend 3 Part 2: speaker embeddings.

Stdlib unittest only (no pytest dependency).

These tests assert plumbing, schemas and failure handling -- NOT
speaker-recognition accuracy. The wired encoder is the
development/mock descriptor (see backend/models/mock_embedder.py);
no test here claims its vectors identify real speakers.
"""
from __future__ import annotations

import base64
import math
import unittest
from unittest import mock

from backend.b2_contract import ProcessedSpeechChunk
from backend.config import Settings
from backend.embeddings import (
    SpeakerEmbeddingService,
    embed_chunk,
    get_embedding_service,
    reset_embedding_service,
)
from backend.models.embed_registry import reset_embedder_registry
from backend.schemas import ModelError, SpeakerEmbeddingResult, ValidationError


def _settings(**overrides) -> Settings:
    params = dict(
        model_name="mock",
        model_version="mock-heuristic-v0.1.0",
        embedder_name="mock",
        embedder_version="mock-spectral-v0.1.0",
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
    # tests only assert structure/geometry, never recognition quality.
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


def _norm(values) -> float:
    return math.sqrt(sum(v * v for v in values))


class TestSpeakerEmbeddings(unittest.TestCase):
    def setUp(self):
        reset_embedder_registry()
        reset_embedding_service()

    def tearDown(self):
        reset_embedder_registry()
        reset_embedding_service()

    def test_valid_processed_speech(self):
        service = SpeakerEmbeddingService(_settings())
        result = service.embed(_chunk())
        self.assertIsInstance(result, SpeakerEmbeddingResult)
        self.assertEqual(result.session_id, "1042")
        self.assertEqual(result.chunk_id, "c0018")

    def test_output_structure(self):
        service = SpeakerEmbeddingService(_settings())
        payload = service.embed(_chunk()).to_dict()
        self.assertEqual(
            set(payload),
            {
                "session_id", "chunk_id", "embedding", "dimension",
                "model_version", "is_mock", "processing_time_ms",
            },
        )
        self.assertIsInstance(payload["embedding"], list)
        self.assertTrue(all(isinstance(v, float) for v in payload["embedding"]))
        self.assertGreaterEqual(payload["processing_time_ms"], 0.0)

    def test_dimension_consistency(self):
        service = SpeakerEmbeddingService(_settings())
        first = service.embed(_chunk())
        other_audio = [0.3 * math.sin(2.0 * math.pi * 220.0 * i / 16000) for i in range(16000)]
        second = service.embed(_chunk(audio=other_audio, chunk_id="c0019"))
        self.assertEqual(first.dimension, service.embedding_dim)
        self.assertEqual(second.dimension, service.embedding_dim)
        self.assertEqual(len(first.embedding), first.dimension)
        self.assertNotEqual(first.dimension, 192)  # mock dim is its own, not ECAPA's

    def test_vectors_are_l2_normalised(self):
        service = SpeakerEmbeddingService(_settings())
        for audio in ([0.0] * 8000, _speech_floats()):
            result = service.embed(_chunk(audio=audio))
            self.assertAlmostEqual(_norm(result.embedding), 1.0, places=6)

    def test_empty_audio(self):
        service = SpeakerEmbeddingService(_settings())
        with self.assertRaises(ValidationError):
            service.embed(_chunk(audio=[]))

    def test_invalid_sample_rate(self):
        service = SpeakerEmbeddingService(_settings())
        with self.assertRaises(ValidationError):
            service.embed(_chunk(sample_rate=12345))

    def test_invalid_chunk(self):
        service = SpeakerEmbeddingService(_settings())
        with self.assertRaises(ValidationError):
            service.embed(_chunk(session_id="   "))
        with self.assertRaises(ValidationError):
            service.embed(None)  # type: ignore[arg-type]

    def test_non_speech_input_rejected(self):
        service = SpeakerEmbeddingService(_settings())
        with self.assertRaises(ValidationError):
            service.embed(_chunk(is_speech=False, speech_ratio=0.05))

    def test_insufficient_speech_rejected(self):
        service = SpeakerEmbeddingService(_settings(min_duration_s=0.25), min_speech_s=2.0)
        with self.assertRaises(ValidationError) as ctx:
            service.embed(_chunk())  # 0.5s < required 2.0s
        self.assertIn("Insufficient speech", str(ctx.exception))

    def test_model_initialization(self):
        service = SpeakerEmbeddingService(_settings())
        self.assertEqual(service.model_version, "mock-spectral-v0.1.0")
        self.assertTrue(service.is_mock)
        self.assertEqual(service.embedding_dim, len(service.embed(_chunk()).embedding))

    def test_model_loads_only_once(self):
        settings = _settings()
        first = SpeakerEmbeddingService(settings)
        second = SpeakerEmbeddingService(settings)
        self.assertIs(first.model, second.model)
        self.assertEqual(first.model.load_count, 1)
        self.assertIs(get_embedding_service(), get_embedding_service())

    def test_inference_failure_raises_model_error(self):
        service = SpeakerEmbeddingService(_settings())
        with mock.patch.object(service.model, "embed", side_effect=RuntimeError("boom")):
            with self.assertRaises(ModelError):
                service.embed(_chunk())

    def test_mock_explicitly_marked(self):
        service = SpeakerEmbeddingService(_settings())
        self.assertTrue(service.model.is_mock)
        result = service.embed(_chunk())
        self.assertTrue(result.is_mock)
        self.assertIn("mock", result.model_version)

    def test_deterministic_mock_output(self):
        service = SpeakerEmbeddingService(_settings())
        first = service.embed(_chunk())
        second = service.embed(_chunk())
        self.assertEqual(first.embedding, second.embedding)
        # Same signal via bytes vs floats must give the same vector.
        raw = b"".join(
            int(max(-1.0, min(1.0, v)) * 32767).to_bytes(2, byteorder="little", signed=True)
            for v in _speech_floats()
        )
        via_bytes = service.embed(_chunk(audio=raw))
        via_floats = service.embed(_chunk(audio=tuple(float(x) for x in _speech_floats())))
        _ = via_floats  # floats path sanity (vectors differ: PCM quantisation)
        self.assertEqual(len(via_bytes.embedding), first.dimension)
        self.assertAlmostEqual(_norm(via_bytes.embedding), 1.0, places=6)

    def test_malformed_wire_dict(self):
        service = SpeakerEmbeddingService(_settings())
        with self.assertRaises(ValidationError):
            service.embed({"sample_rate": 16000})  # missing IDs/audio
        raw = (int(1000).to_bytes(2, byteorder="little", signed=True)) * 8000
        result = service.embed(
            {
                "audio_base64": base64.b64encode(raw).decode("ascii"),
                "audio_encoding": "pcm16_base64",
                "sample_rate": 16000,
                "session_id": "1042",
                "chunk_id": "c0018",
                "is_speech": True,
            }
        )
        self.assertEqual(result.session_id, "1042")

    def test_functional_entry_point(self):
        result = embed_chunk(_chunk())
        self.assertIsInstance(result, SpeakerEmbeddingResult)


if __name__ == "__main__":
    unittest.main()
