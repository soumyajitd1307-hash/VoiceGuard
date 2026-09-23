"""Tests for the Backend 3 runtime orchestration layer.

Stdlib unittest only. Uses the existing mock detector/embedder (fast,
offline, deterministic). Fixtures are TEST FIXTURES for plumbing; they
assert orchestration mechanics, never model quality or risk.
"""
from __future__ import annotations

import io
import json
import logging
import math
import unittest
from unittest import mock

from backend.config import Settings
from backend.pipeline import Backend3Pipeline, get_pipeline, reset_pipeline
from backend.schemas import Backend3Signals, ValidationError
from backend.schemas import ModelError


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
    return [0.5 * math.sin(2.0 * math.pi * 440.0 * i / 16000) for i in range(n)]


def _chunk(**overrides) -> dict:
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
    return params


def _strip_timings(payload: dict) -> dict:
    payload = json.loads(json.dumps(payload))
    payload["metadata"].pop("processing_time_ms", None)
    for key in ("synthetic", "speaker", "similarity"):
        if payload.get(key):
            payload[key].pop("processing_time_ms", None)
    return payload


class TestBackend3Pipeline(unittest.TestCase):
    def setUp(self):
        from backend.detector import reset_detector
        from backend.embeddings import reset_embedding_service
        from backend.models.embed_registry import reset_embedder_registry
        from backend.models.registry import reset_model_registry

        reset_detector()
        reset_embedding_service()
        reset_embedder_registry()
        reset_model_registry()
        reset_pipeline()

    def tearDown(self):
        from backend.detector import reset_detector
        from backend.embeddings import reset_embedding_service
        from backend.models.embed_registry import reset_embedder_registry
        from backend.models.registry import reset_model_registry

        reset_detector()
        reset_embedding_service()
        reset_embedder_registry()
        reset_model_registry()
        reset_pipeline()

    def _pipeline(self) -> Backend3Pipeline:
        return Backend3Pipeline(_settings())

    def test_detection_and_embedding_pipeline(self):
        bundle = self._pipeline().process_chunk(_chunk())
        self.assertIsInstance(bundle, Backend3Signals)
        self.assertIsNotNone(bundle.synthetic)
        self.assertIsNotNone(bundle.speaker)

    def test_full_pipeline_with_reference(self):
        pipeline = self._pipeline()
        first = pipeline.process_chunk(_chunk())
        assert first.speaker is not None
        bundle = pipeline.process_chunk(
            _chunk(), reference_embedding=first.speaker, reference_id="usr-1042"
        )
        self.assertIsNotNone(bundle.similarity)

    def test_detection_result_exists(self):
        bundle = self._pipeline().process_chunk(_chunk())
        assert bundle.synthetic is not None
        self.assertIn(bundle.synthetic.label, ("real", "synthetic", "uncertain"))
        self.assertGreaterEqual(bundle.synthetic.synthetic_probability, 0.0)
        self.assertLessEqual(bundle.synthetic.synthetic_probability, 1.0)

    def test_embedding_result_exists(self):
        bundle = self._pipeline().process_chunk(_chunk())
        assert bundle.speaker is not None
        self.assertEqual(bundle.speaker.dimension, len(bundle.speaker.embedding))

    def test_similarity_none_without_reference(self):
        bundle = self._pipeline().process_chunk(_chunk())
        self.assertIsNone(bundle.similarity)
        self.assertIsNone(bundle.to_dict()["similarity"])

    def test_similarity_exists_with_reference(self):
        bundle = self._pipeline().process_chunk(
            _chunk(), reference_embedding=[0.0] * 31 + [1.0], reference_id="usr-1042"
        )
        assert bundle.similarity is not None
        self.assertGreaterEqual(bundle.similarity.similarity, -1.0)
        self.assertLessEqual(bundle.similarity.similarity, 1.0)

    def test_session_id_preserved(self):
        bundle = self._pipeline().process_chunk(_chunk())
        self.assertEqual(bundle.session_id, "1042")

    def test_chunk_id_preserved(self):
        bundle = self._pipeline().process_chunk(_chunk())
        self.assertEqual(bundle.chunk_id, "c0018")

    def test_reference_id_preserved(self):
        pipeline = self._pipeline()
        first = pipeline.process_chunk(_chunk())
        assert first.speaker is not None
        bundle = pipeline.process_chunk(
            _chunk(), reference_embedding=first.speaker, reference_id="usr-1042"
        )
        assert bundle.similarity is not None
        self.assertEqual(bundle.similarity.reference_id, "usr-1042")

    def test_model_version_preserved(self):
        bundle = self._pipeline().process_chunk(_chunk())
        payload = bundle.to_dict()
        self.assertEqual(payload["synthetic"]["model_version"], "mock-heuristic-v0.1.0")
        self.assertEqual(payload["speaker"]["model_version"], "mock-spectral-v0.1.0")

    def test_is_mock_preserved(self):
        bundle = self._pipeline().process_chunk(_chunk())
        payload = bundle.to_dict()
        self.assertTrue(payload["synthetic"]["is_mock"])
        self.assertTrue(payload["speaker"]["is_mock"])

    def test_processing_time_propagated(self):
        bundle = self._pipeline().process_chunk(_chunk())
        payload = bundle.to_dict()
        self.assertGreaterEqual(payload["synthetic"]["processing_time_ms"], 0.0)
        self.assertGreaterEqual(payload["speaker"]["processing_time_ms"], 0.0)
        self.assertAlmostEqual(
            payload["metadata"]["processing_time_ms"],
            payload["synthetic"]["processing_time_ms"]
            + payload["speaker"]["processing_time_ms"],
            places=2,
        )

    def test_malformed_input_rejected(self):
        with self.assertRaises(ValidationError):
            self._pipeline().process_chunk({"sample_rate": 16000})
        with self.assertRaises(ValidationError):
            self._pipeline().process_chunk(None)  # type: ignore[arg-type]

    def test_invalid_reference_embedding_rejected(self):
        with self.assertRaises(ValidationError):
            self._pipeline().process_chunk(_chunk(), reference_embedding=[float("nan")] * 32)
        with self.assertRaises(ValidationError):
            self._pipeline().process_chunk(_chunk(), reference_embedding=[1.0, 0.0])  # dim 2 vs 32

    def test_cross_session_mismatch_rejected(self):
        # A detector honouring a different session must not merge downstream.
        pipeline = self._pipeline()
        tampered = pipeline._detector.detect_chunk(_chunk())
        mismatched = tampered.to_dict() | {"session_id": "OTHER"}
        with mock.patch.object(
            pipeline._detector, "detect_chunk",
            side_effect=ValidationError("injected"),
        ):
            with self.assertRaises(ValidationError):
                pipeline.process_chunk(_chunk())
        # Direct contract-level mismatch also raises (no silent merge).
        from backend.signals import build_backend3_signals

        with self.assertRaises(ValidationError):
            build_backend3_signals(
                detection_result=mismatched,
                embedding_result=pipeline._embedder.embed(_chunk()).to_dict(),
            )

    def test_detector_errors_propagate(self):
        pipeline = self._pipeline()
        with mock.patch.object(
            pipeline._detector, "detect_chunk", side_effect=ModelError("detector down")
        ):
            with self.assertRaises(ModelError):
                pipeline.process_chunk(_chunk())

    def test_embedding_errors_propagate(self):
        pipeline = self._pipeline()
        with mock.patch.object(
            pipeline._embedder, "embed", side_effect=ModelError("encoder down")
        ):
            with self.assertRaises(ModelError):
                pipeline.process_chunk(_chunk())

    def test_no_fake_similarity_generated(self):
        bundle = self._pipeline().process_chunk(_chunk())
        self.assertIsNone(bundle.similarity)
        # No zero-vector / self-comparison shortcuts anywhere in the path.
        self.assertNotIn("similarity", json.dumps(bundle.to_dict()["speaker"]))

    def test_no_risk_fields_generated(self):
        bundle = self._pipeline().process_chunk(_chunk())
        text = json.dumps(bundle.to_dict()).lower()
        for invented in ("risk", "scam", "impersonation", "trusted", "malicious", "alert"):
            self.assertNotIn(invented, text)

    def test_deterministic_behavior(self):
        pipeline = self._pipeline()
        first = _strip_timings(pipeline.process_chunk(_chunk()).to_dict())
        second = _strip_timings(pipeline.process_chunk(_chunk()).to_dict())
        self.assertEqual(first, second)

    def test_process_chunk_object_input(self):
        from backend.b2_contract import from_dict

        pipeline = self._pipeline()
        bundle = pipeline.process_chunk(from_dict(_chunk(), _settings()))
        self.assertEqual(bundle.session_id, "1042")

    def test_singleton_accessor(self):
        self.assertIs(get_pipeline(), get_pipeline())

    def test_pipeline_never_logs_vectors(self):
        handler_stream = io.StringIO()
        handler = logging.StreamHandler(handler_stream)
        logger = logging.getLogger("backend.pipeline")
        logger.addHandler(handler)
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            self._pipeline().process_chunk(_chunk())
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)
        logged = handler_stream.getvalue()
        self.assertIn("1042", logged)  # IDs are fine to log
        for probe in ("0.7071", "sin", "embedding"):
            self.assertNotIn(probe, logged)


if __name__ == "__main__":
    unittest.main()
