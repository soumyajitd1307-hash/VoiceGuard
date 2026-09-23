"""Tests for Backend 3 Part 3: speaker similarity.

Stdlib unittest only (no pytest dependency).

Math tests use small deterministic vectors and assert cosine geometry
only. They do NOT validate speaker recognition -- the wired encoder is
the development/mock descriptor, and mock similarity must never be read
as "same person" / "verified".
"""
from __future__ import annotations

import math
import unittest

from backend.config import Settings
from backend.schemas import SimilarityResult, SpeakerEmbeddingResult
from backend.schemas import ValidationError
from backend.similarity import SpeakerSimilarityService, compare_similarity


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


def _result(embedding, **overrides) -> SpeakerEmbeddingResult:
    params = dict(
        session_id="1042",
        chunk_id="c0018",
        embedding=tuple(embedding),
        dimension=len(embedding),
        model_version="mock-spectral-v0.1.0",
        is_mock=True,
        processing_time_ms=0.1,
    )
    params.update(overrides)
    return SpeakerEmbeddingResult(**params)


def _unit(values):
    norm = math.sqrt(sum(v * v for v in values))
    return tuple(v / norm for v in values)


class TestSpeakerSimilarity(unittest.TestCase):
    def test_identical_vectors(self):
        service = SpeakerSimilarityService(_settings())
        result = service.compare([1.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        self.assertIsInstance(result, SimilarityResult)
        self.assertAlmostEqual(result.similarity, 1.0, places=6)

    def test_orthogonal_vectors(self):
        service = SpeakerSimilarityService(_settings())
        result = service.compare([1.0, 0.0], [0.0, 1.0])
        self.assertAlmostEqual(result.similarity, 0.0, places=6)

    def test_opposite_vectors(self):
        service = SpeakerSimilarityService(_settings())
        result = service.compare([1.0, 2.0, 3.0], [-1.0, -2.0, -3.0])
        self.assertAlmostEqual(result.similarity, -1.0, places=6)

    def test_known_cosine_similarity(self):
        service = SpeakerSimilarityService(_settings())
        # 3-4-5 triangle vs x-axis: cos = 3/5.
        result = service.compare([3.0, 4.0], [1.0, 0.0])
        self.assertAlmostEqual(result.similarity, 0.6, places=6)
        # Non-unit inputs must score identically to their unit versions.
        scaled = service.compare([30.0, 40.0], [5.0, 0.0])
        self.assertAlmostEqual(scaled.similarity, 0.6, places=6)

    def test_different_dimensions(self):
        service = SpeakerSimilarityService(_settings())
        with self.assertRaises(ValidationError):
            service.compare([1.0, 0.0], [1.0, 0.0, 0.0])

    def test_empty_vectors(self):
        service = SpeakerSimilarityService(_settings())
        with self.assertRaises(ValidationError):
            service.compare([], [1.0, 0.0])
        with self.assertRaises(ValidationError):
            service.compare([1.0, 0.0], [])

    def test_zero_vectors(self):
        service = SpeakerSimilarityService(_settings())
        with self.assertRaises(ValidationError):
            service.compare([0.0, 0.0], [1.0, 0.0])
        with self.assertRaises(ValidationError):
            service.compare([1.0, 0.0], [0.0, 0.0, 0.0][:2])

    def test_nan_rejected(self):
        service = SpeakerSimilarityService(_settings())
        with self.assertRaises(ValidationError):
            service.compare([float("nan"), 0.0], [1.0, 0.0])

    def test_infinity_rejected(self):
        service = SpeakerSimilarityService(_settings())
        with self.assertRaises(ValidationError):
            service.compare([1.0, 0.0], [float("inf"), 0.0])

    def test_non_numeric_rejected(self):
        service = SpeakerSimilarityService(_settings())
        with self.assertRaises(ValidationError):
            service.compare([1.0, "x"], [1.0, 0.0])
        with self.assertRaises(ValidationError):
            service.compare([True, 0.0], [1.0, 0.0])

    def test_threshold_absent_gives_uncertain(self):
        service = SpeakerSimilarityService(_settings())  # no threshold configured
        result = service.compare([1.0, 0.0], [1.0, 0.0])
        self.assertEqual(result.match, "uncertain")
        self.assertIsNone(result.threshold)
        self.assertAlmostEqual(result.similarity, 1.0, places=6)  # score preserved

    def test_threshold_configured_match(self):
        service = SpeakerSimilarityService(_settings(), threshold=0.5)
        result = service.compare([3.0, 4.0], [1.0, 0.0])  # sim = 0.6
        self.assertEqual(result.match, "match")
        self.assertEqual(result.threshold, 0.5)

    def test_threshold_configured_non_match(self):
        service = SpeakerSimilarityService(_settings(), threshold=0.9)
        result = service.compare([3.0, 4.0], [1.0, 0.0])  # sim = 0.6
        self.assertEqual(result.match, "non_match")

    def test_exact_threshold_is_match(self):
        service = SpeakerSimilarityService(_settings())
        result = service.compare([3.0, 4.0], [1.0, 0.0], threshold=0.6)
        self.assertEqual(result.match, "match")  # inclusive boundary

    def test_bad_threshold_rejected(self):
        service = SpeakerSimilarityService(_settings())
        with self.assertRaises(ValidationError):
            service.compare([1.0, 0.0], [1.0, 0.0], threshold=1.5)
        with self.assertRaises(ValueError):
            SpeakerSimilarityService(_settings(), threshold=2.0)

    def test_mock_propagation(self):
        service = SpeakerSimilarityService(_settings())
        ref = _result(_unit([1.0, 2.0, 3.0]))
        cur = _result(_unit([1.0, 2.0, 4.0]), chunk_id="c0019")
        result = service.compare(ref, cur, reference_id="usr-1042")
        self.assertTrue(result.is_mock)
        # Unknown-provenance raw vectors default to mock, never production-looking.
        raw = service.compare([1.0, 0.0], [1.0, 0.0])
        self.assertTrue(raw.is_mock)
        # Explicit real provenance is preserved when asserted by the caller.
        real = service.compare(
            _result([1.0, 0.0], is_mock=False, model_version="ecapa-v1"),
            _result([1.0, 0.0], is_mock=False, model_version="ecapa-v1"),
            threshold=0.5,
        )
        self.assertFalse(real.is_mock)
        self.assertEqual(real.match, "match")

    def test_metadata_preservation(self):
        service = SpeakerSimilarityService(_settings())
        ref = _result(_unit([0.2, 0.5]), session_id="0000", chunk_id="enroll")
        cur = _result(_unit([0.3, 0.6]))
        result = service.compare(ref, cur, reference_id="usr-1042")
        self.assertEqual(result.reference_id, "usr-1042")
        self.assertEqual(result.session_id, "1042")  # from CURRENT chunk
        self.assertEqual(result.chunk_id, "c0018")
        self.assertEqual(result.model_version, "mock-spectral-v0.1.0")
        overridden = service.compare(
            ref, cur, reference_id="usr-9",
            session_id="s", chunk_id="c", model_version="vX",
        )
        self.assertEqual(
            (overridden.reference_id, overridden.session_id,
             overridden.chunk_id, overridden.model_version),
            ("usr-9", "s", "c", "vX"),
        )

    def test_cross_version_comparison_documented(self):
        service = SpeakerSimilarityService(_settings())
        ref = _result([1.0, 0.0], model_version="enc-v1")
        cur = _result([1.0, 0.0], model_version="enc-v2")
        result = service.compare(ref, cur)
        self.assertEqual(result.model_version, "enc-v2")  # current wins, documented

    def test_deterministic_output(self):
        service = SpeakerSimilarityService(_settings())
        first = service.compare([0.1, 0.7, 0.3], [0.4, 0.2, 0.9], threshold=0.5)
        second = service.compare([0.1, 0.7, 0.3], [0.4, 0.2, 0.9], threshold=0.5)
        # Timing varies run to run; everything else must be identical.
        first_dict = first.to_dict()
        second_dict = second.to_dict()
        for payload in (first_dict, second_dict):
            payload.pop("processing_time_ms")
        self.assertEqual(first_dict, second_dict)

    def test_malformed_input(self):
        service = SpeakerSimilarityService(_settings())
        with self.assertRaises(ValidationError):
            service.compare(None, [1.0, 0.0])  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            service.compare("abc", [1.0, 0.0, 0.0])  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            service.compare({"nope": []}, [1.0])  # type: ignore[arg-type]

    def test_result_schema(self):
        service = SpeakerSimilarityService(_settings())
        payload = service.compare([1.0, 0.0], [0.0, 1.0]).to_dict()
        self.assertEqual(
            set(payload),
            {
                "reference_id", "session_id", "chunk_id", "similarity",
                "threshold", "match", "model_version", "is_mock",
                "processing_time_ms",
            },
        )
        self.assertIn(payload["match"], ("match", "non_match", "uncertain"))
        self.assertGreaterEqual(payload["processing_time_ms"], 0.0)

    def test_embedding_result_end_to_end(self):
        # Mock-service vectors flow into compare(); stays flagged mock.
        from backend.embeddings import SpeakerEmbeddingService as EmbedService

        embed = EmbedService(_settings())
        import math as _math

        tone = [0.5 * _math.sin(2.0 * _math.pi * 440.0 * i / 16000) for i in range(8000)]
        cur = embed.embed(
            {"audio": tone, "sample_rate": 16000,
             "session_id": "1042", "chunk_id": "c0018", "is_speech": True}
        )
        result = SpeakerSimilarityService(_settings()).compare(
            cur, cur, reference_id="usr-1042"
        )
        self.assertAlmostEqual(result.similarity, 1.0, places=5)
        self.assertTrue(result.is_mock)

    def test_functional_entry_point(self):
        result = compare_similarity([1.0, 0.0], [1.0, 0.0])
        self.assertAlmostEqual(result.similarity, 1.0, places=6)
        self.assertEqual(result.match, "uncertain")


if __name__ == "__main__":
    unittest.main()
