"""Tests for the Backend 3 -> Backend 4 signal boundary.

Stdlib unittest only. Fixtures are deterministic TEST FIXTURES for the
plumbing; they assert contract mechanics, never model quality or risk.
No test prints or logs embedding contents (privacy).
"""
from __future__ import annotations

import io
import json
import logging
import unittest

from backend.schemas import (
    Backend3Signals,
    DetectionResult,
    SimilarityResult,
    SpeakerEmbeddingResult,
    ValidationError,
)
from backend.signals import build_backend3_signals


def _detection(**overrides) -> DetectionResult:
    params = dict(
        label="synthetic",
        synthetic_probability=0.91,
        model_version="mock-heuristic-v0.1.0",
        processing_time_ms=1.5,
        session_id="1042",
        chunk_id="c0018",
        is_mock=True,
    )
    params.update(overrides)
    return DetectionResult(**params)


def _embedding(**overrides) -> SpeakerEmbeddingResult:
    vec = tuple([0.25] * 32)
    params = dict(
        session_id="1042",
        chunk_id="c0018",
        embedding=vec,
        dimension=32,
        model_version="mock-spectral-v0.1.0",
        is_mock=True,
        processing_time_ms=2.5,
    )
    params.update(overrides)
    return SpeakerEmbeddingResult(**params)


def _similarity(**overrides) -> SimilarityResult:
    params = dict(
        reference_id="usr-1042",
        session_id="1042",
        chunk_id="c0018",
        similarity=0.64,
        threshold=None,
        match="uncertain",
        model_version="mock-spectral-v0.1.0",
        is_mock=True,
        processing_time_ms=0.5,
    )
    params.update(overrides)
    return SimilarityResult(**params)


class TestB3B4Contract(unittest.TestCase):
    def test_detection_only_signal(self):
        bundle = build_backend3_signals(detection_result=_detection())
        self.assertIsInstance(bundle, Backend3Signals)
        self.assertIsNotNone(bundle.synthetic)
        self.assertIsNone(bundle.speaker)
        self.assertIsNone(bundle.similarity)

    def test_embedding_only_signal(self):
        bundle = build_backend3_signals(embedding_result=_embedding())
        self.assertIsNone(bundle.synthetic)
        self.assertIsNotNone(bundle.speaker)
        self.assertIsNone(bundle.similarity)

    def test_similarity_only_signal(self):
        bundle = build_backend3_signals(similarity_result=_similarity())
        self.assertIsNone(bundle.synthetic)
        self.assertIsNone(bundle.speaker)
        self.assertIsNotNone(bundle.similarity)

    def test_all_three_signals(self):
        bundle = build_backend3_signals(
            detection_result=_detection(),
            embedding_result=_embedding(),
            similarity_result=_similarity(),
        )
        payload = bundle.to_dict()
        self.assertIsNotNone(payload["synthetic"])
        self.assertIsNotNone(payload["speaker"])
        self.assertIsNotNone(payload["similarity"])
        # metadata timing is provenance arithmetic, not risk.
        self.assertAlmostEqual(payload["metadata"]["processing_time_ms"], 4.5)

    def test_missing_optional_signals(self):
        bundle = build_backend3_signals(detection_result=_detection())
        payload = bundle.to_dict()
        self.assertIsNone(payload["speaker"])
        self.assertIsNone(payload["similarity"])
        with self.assertRaises(ValidationError):
            build_backend3_signals()  # no signals at all

    def test_session_id_consistency(self):
        bundle = build_backend3_signals(
            detection_result=_detection(), embedding_result=_embedding()
        )
        self.assertEqual(bundle.session_id, "1042")

    def test_session_id_mismatch(self):
        with self.assertRaises(ValidationError):
            build_backend3_signals(
                detection_result=_detection(session_id="A"),
                embedding_result=_embedding(session_id="B"),
            )

    def test_chunk_id_consistency(self):
        bundle = build_backend3_signals(similarity_result=_similarity())
        self.assertEqual(bundle.chunk_id, "c0018")

    def test_chunk_id_mismatch(self):
        with self.assertRaises(ValidationError):
            build_backend3_signals(
                detection_result=_detection(chunk_id="c0001"),
                similarity_result=_similarity(chunk_id="c0002"),
            )

    def test_mock_propagation(self):
        bundle = build_backend3_signals(
            detection_result=_detection(),
            embedding_result=_embedding(),
            similarity_result=_similarity(),
        )
        payload = bundle.to_dict()
        self.assertTrue(payload["synthetic"]["is_mock"])
        self.assertTrue(payload["speaker"]["is_mock"])
        self.assertTrue(payload["similarity"]["is_mock"])

    def test_model_version_preservation(self):
        bundle = build_backend3_signals(
            detection_result=_detection(),
            embedding_result=_embedding(),
            similarity_result=_similarity(),
        )
        payload = bundle.to_dict()
        self.assertEqual(payload["synthetic"]["model_version"], "mock-heuristic-v0.1.0")
        self.assertEqual(payload["speaker"]["model_version"], "mock-spectral-v0.1.0")
        self.assertEqual(payload["similarity"]["model_version"], "mock-spectral-v0.1.0")

    def test_reference_id_preservation(self):
        bundle = build_backend3_signals(similarity_result=_similarity())
        self.assertEqual(bundle.to_dict()["similarity"]["reference_id"], "usr-1042")

    def test_probability_preservation(self):
        bundle = build_backend3_signals(detection_result=_detection())
        payload = bundle.to_dict()
        self.assertAlmostEqual(payload["synthetic"]["synthetic_probability"], 0.91)
        self.assertEqual(payload["synthetic"]["label"], "synthetic")

    def test_similarity_preservation(self):
        bundle = build_backend3_signals(similarity_result=_similarity())
        payload = bundle.to_dict()
        self.assertAlmostEqual(payload["similarity"]["similarity"], 0.64)
        self.assertEqual(payload["similarity"]["match"], "uncertain")

    def test_embedding_dimension_preservation(self):
        bundle = build_backend3_signals(embedding_result=_embedding())
        payload = bundle.to_dict()
        self.assertEqual(payload["speaker"]["dimension"], 32)
        self.assertEqual(len(payload["speaker"]["embedding"]), 32)

    def test_malformed_input(self):
        with self.assertRaises(ValidationError):
            build_backend3_signals(detection_result="nope")  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            build_backend3_signals(detection_result={"label": "synthetic"})  # missing keys
        with self.assertRaises(ValidationError):
            build_backend3_signals(
                detection_result=_detection().to_dict() | {"synthetic_probability": 5.0}
            )
        with self.assertRaises(ValidationError):
            build_backend3_signals(
                similarity_result=_similarity().to_dict() | {"similarity": 9.0}
            )
        with self.assertRaises(ValidationError):
            build_backend3_signals(
                embedding_result=_embedding().to_dict() | {"dimension": 7}  # len 32
            )
        with self.assertRaises(ValidationError):
            build_backend3_signals(
                embedding_result=_embedding().to_dict() | {"is_mock": "yes"}
            )

    def test_json_safe_serialization(self):
        bundle = build_backend3_signals(
            detection_result=_detection(),
            embedding_result=_embedding(),
            similarity_result=_similarity(),
        )
        json.dumps(bundle.to_dict())
        json.dumps(bundle.to_dict(include_embedding=False))

    def test_no_risk_score_generated(self):
        bundle = build_backend3_signals(
            detection_result=_detection(),
            embedding_result=_embedding(),
            similarity_result=_similarity(),
        )
        payload = bundle.to_dict()
        flat_keys = set(payload.keys())
        self.assertFalse({"risk", "risk_score", "risk_level"} & flat_keys)
        self.assertNotIn("risk", json.dumps(payload).lower())

    def test_no_risk_label_generated(self):
        bundle = build_backend3_signals(detection_result=_detection())
        payload = bundle.to_dict()
        text = json.dumps(payload).lower()
        for invented in ("low risk", "medium risk", "high risk", "scam",
                         "impersonation", "trusted", "malicious"):
            self.assertNotIn(invented, text)

    def test_deterministic_serialization(self):
        first = build_backend3_signals(
            detection_result=_detection(), similarity_result=_similarity()
        ).to_dict()
        second = build_backend3_signals(
            detection_result=_detection(), similarity_result=_similarity()
        ).to_dict()
        self.assertEqual(first, second)

    def test_embedding_withheld_for_similarity_only_consumers(self):
        bundle = build_backend3_signals(
            embedding_result=_embedding(), similarity_result=_similarity()
        )
        redacted = bundle.to_dict(include_embedding=False)
        self.assertNotIn("embedding", redacted["speaker"])
        self.assertTrue(redacted["speaker"]["embedding_withheld"])
        # Provenance survives redaction.
        self.assertEqual(redacted["speaker"]["dimension"], 32)
        self.assertTrue(redacted["speaker"]["is_mock"])
        # Full form still available for profile comparison.
        self.assertEqual(len(bundle.to_dict()["speaker"]["embedding"]), 32)

    def test_embeddings_never_logged(self):
        handler_stream = io.StringIO()
        handler = logging.StreamHandler(handler_stream)
        logger = logging.getLogger("backend.signals")
        logger.addHandler(handler)
        try:
            build_backend3_signals(
                detection_result=_detection(),
                embedding_result=_embedding(),
                similarity_result=_similarity(),
            )
        finally:
            logger.removeHandler(handler)
        logged = handler_stream.getvalue()
        self.assertNotIn("0.25", logged)  # vector contents must not appear in logs


if __name__ == "__main__":
    unittest.main()
