"""Tests for Part 8: real-model adapters, registry and mixed mode.

Stdlib unittest only. No external weights are used anywhere here: the
"real" adapters execute against tiny deterministic TEST FIXTURE weight
files generated per-test in a temp directory. Fixture scores exercise
the loading/scoring/plumbing path only -- they validate NO real model.

Optional integration tests gated by VG_RUN_REAL_MODEL_TESTS=1 run only
when real weight files are explicitly supplied, and skip otherwise.
"""
from __future__ import annotations

import json
import math
import os
import random
import tempfile
import threading
import unittest

from backend.config import Settings
from backend.models.embed_registry import get_embedder, reset_embedder_registry
from backend.models.real_detector import RealDetectorAdapter
from backend.models.real_embedder import RealEmbedderAdapter
from backend.models.registry import get_model, reset_model_registry
from backend.schemas import ModelError, ValidationError

DETECTOR_VERSION = "cm-test-v1"
EMBEDDER_VERSION = "enc-test-v1"
EMBED_OUT_DIM = 16


def _settings(**overrides) -> Settings:
    params = dict(
        model_name="mock",
        model_version="mock-heuristic-v0.1.0",
        embedder_name="mock",
        embedder_version="mock-spectral-v0.1.0",
        detector_model="",
        embedder_model="",
        synthetic_threshold=0.7,
        real_threshold=0.3,
        min_duration_s=0.25,
        max_duration_s=30.0,
        max_id_length=128,
        log_level="CRITICAL",
    )
    params.update(overrides)
    return Settings(**params)


def _tone(n: int = 8000) -> list:
    return [0.5 * math.sin(2.0 * math.pi * 440.0 * i / 16000) for i in range(n)]


def _write_detector_fixture(path: str, version: str = DETECTOR_VERSION) -> None:
    # TEST FIXTURE weights: deterministic, tiny, unvalidated.
    weights = [0.05 * ((i % 7) - 3) for i in range(32)]
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({
            "format": "voiceguard-detector-v1",
            "model": "test-fixture (not a real model)",
            "version": version,
            "feature": "heuristic-32-v1",
            "input_dim": 32,
            "weights": weights,
            "bias": -0.5,
        }, handle)


def _write_embedder_fixture(path: str, version: str = EMBEDDER_VERSION,
                            out_dim: int = EMBED_OUT_DIM) -> None:
    # TEST FIXTURE weights: seeded, deterministic, unvalidated.
    rng = random.Random(20240923)
    matrix = [[rng.uniform(-0.5, 0.5) for _ in range(32)] for _ in range(out_dim)]
    bias = [rng.uniform(-0.1, 0.1) for _ in range(out_dim)]
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({
            "format": "voiceguard-embedder-v1",
            "model": "test-fixture (not a real model)",
            "version": version,
            "feature": "heuristic-32-v1",
            "input_dim": 32,
            "output_dim": out_dim,
            "matrix": matrix,
            "bias": bias,
        }, handle)


class _FixtureDir(unittest.TestCase):
    def setUp(self):
        reset_model_registry()
        reset_embedder_registry()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.detector_path = os.path.join(self._tmp.name, "detector.json")
        self.embedder_path = os.path.join(self._tmp.name, "embedder.json")
        _write_detector_fixture(self.detector_path)
        _write_embedder_fixture(self.embedder_path)

    def tearDown(self):
        reset_model_registry()
        reset_embedder_registry()


class TestRealDetector(_FixtureDir):
    def _adapter(self, **overrides) -> RealDetectorAdapter:
        params = dict(weights_path=self.detector_path, version=DETECTOR_VERSION)
        params.update(overrides)
        return RealDetectorAdapter(**params)

    def test_construction_requires_path_and_version(self):
        with self.assertRaises(ModelError):
            RealDetectorAdapter("", DETECTOR_VERSION)
        with self.assertRaises(ModelError):
            RealDetectorAdapter(self.detector_path, "  ")

    def test_load_and_metadata(self):
        adapter = self._adapter()
        adapter.load()
        self.assertEqual(adapter.version, DETECTOR_VERSION)
        self.assertFalse(adapter.is_mock)

    def test_load_idempotent_once(self):
        adapter = self._adapter()
        adapter.load()
        adapter.load()
        self.assertEqual(adapter.load_count, 1)

    def test_deterministic_output_in_range(self):
        adapter = self._adapter()
        adapter.load()
        first = adapter.predict_proba(_tone(), 16000)
        second = adapter.predict_proba(_tone(), 16000)
        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 0.0)
        self.assertLessEqual(first, 1.0)

    def test_missing_file_fails_clearly(self):
        adapter = self._adapter(weights_path=os.path.join(self._tmp.name, "nope.json"))
        with self.assertRaises(ModelError) as ctx:
            adapter.load()
        self.assertIn("not found", str(ctx.exception))

    def test_malformed_file_fails(self):
        bad = os.path.join(self._tmp.name, "bad.json")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(ModelError):
            self._adapter(weights_path=bad).load()

    def test_version_mismatch_fails(self):
        other = os.path.join(self._tmp.name, "other.json")
        _write_detector_fixture(other, version="cm-other-v9")
        with self.assertRaises(ModelError) as ctx:
            self._adapter(weights_path=other).load()
        self.assertIn("cm-other-v9", str(ctx.exception))

    def test_bad_weights_shape_fails(self):
        bad = os.path.join(self._tmp.name, "shape.json")
        _write_detector_fixture(bad)
        with open(bad, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["weights"] = payload["weights"][:10]
        with open(bad, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        with self.assertRaises(ModelError):
            self._adapter(weights_path=bad).load()

    def test_predict_before_load_fails(self):
        with self.assertRaises(RuntimeError):
            self._adapter().predict_proba(_tone(), 16000)

    def test_invalid_input_rejected(self):
        adapter = self._adapter()
        adapter.load()
        with self.assertRaises(ValueError):
            adapter.predict_proba([], 16000)
        with self.assertRaises(ValueError):
            adapter.predict_proba([0.1, float("nan")], 16000)
        with self.assertRaises(ValueError):
            adapter.predict_proba([0.1, float("inf")], 16000)
        with self.assertRaises(ValueError):
            adapter.predict_proba([0.1, 1.5], 16000)  # extreme amplitude
        with self.assertRaises(ValueError):
            adapter.predict_proba([[0.1]], 16000)  # not mono floats
        with self.assertRaises(ValueError):
            adapter.predict_proba(_tone(), 0)

    def test_silence_is_valid_input(self):
        adapter = self._adapter()
        adapter.load()
        score = adapter.predict_proba([0.0] * 8000, 16000)
        self.assertTrue(math.isfinite(score))

    def test_repr_hides_path(self):
        text = repr(self._adapter())
        self.assertNotIn(self.detector_path, text)
        self.assertNotIn("tmp", text)
        self.assertIn(DETECTOR_VERSION, text)

    def test_thread_safe_single_load(self):
        adapter = self._adapter()
        adapter.load()
        results: list = []
        errors: list = []

        def work() -> None:
            try:
                results.append(adapter.predict_proba(_tone(), 16000))
            except Exception as exc:  # noqa: BLE001 - collected for assertion
                errors.append(exc)

        threads = [threading.Thread(target=work) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertTrue(all(score == results[0] for score in results))


class TestRealEmbedder(_FixtureDir):
    def _adapter(self, **overrides) -> RealEmbedderAdapter:
        params = dict(weights_path=self.embedder_path, version=EMBEDDER_VERSION)
        params.update(overrides)
        return RealEmbedderAdapter(**params)

    def test_construction_requires_path_and_version(self):
        with self.assertRaises(ModelError):
            RealEmbedderAdapter("", EMBEDDER_VERSION)
        with self.assertRaises(ModelError):
            RealEmbedderAdapter(self.embedder_path, "")

    def test_load_and_metadata(self):
        adapter = self._adapter()
        adapter.load()
        self.assertEqual(adapter.version, EMBEDDER_VERSION)
        self.assertFalse(adapter.is_mock)
        self.assertEqual(adapter.embedding_dim, EMBED_OUT_DIM)

    def test_embedding_dim_unavailable_before_load(self):
        with self.assertRaises(RuntimeError):
            self._adapter().embedding_dim()

    def test_fixed_dimension_from_weights(self):
        other = os.path.join(self._tmp.name, "enc8.json")
        _write_embedder_fixture(other, out_dim=8)
        adapter = self._adapter(weights_path=other)
        adapter.load()
        self.assertEqual(adapter.embedding_dim, 8)
        self.assertEqual(len(adapter.embed(_tone(), 16000)), 8)

    def test_deterministic_output(self):
        adapter = self._adapter()
        adapter.load()
        self.assertEqual(adapter.embed(_tone(), 16000),
                         adapter.embed(_tone(), 16000))

    def test_normalized_finite_output(self):
        adapter = self._adapter()
        adapter.load()
        vector = adapter.embed(_tone(), 16000)
        norm = math.sqrt(sum(v * v for v in vector))
        self.assertAlmostEqual(norm, 1.0, places=9)
        self.assertTrue(all(math.isfinite(v) for v in vector))

    def test_missing_file_fails_clearly(self):
        adapter = self._adapter(weights_path=os.path.join(self._tmp.name, "nope.json"))
        with self.assertRaises(ModelError) as ctx:
            adapter.load()
        self.assertIn("not found", str(ctx.exception))

    def test_version_mismatch_fails(self):
        other = os.path.join(self._tmp.name, "other.json")
        _write_embedder_fixture(other, version="enc-other-v9")
        with self.assertRaises(ModelError):
            self._adapter(weights_path=other).load()

    def test_bad_matrix_shape_fails(self):
        bad = os.path.join(self._tmp.name, "shape.json")
        _write_embedder_fixture(bad)
        with open(bad, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["matrix"] = payload["matrix"][:4]  # 4 rows vs output_dim 16
        with open(bad, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        with self.assertRaises(ModelError):
            self._adapter(weights_path=bad).load()

    def test_degenerate_weights_fail_loudly(self):
        degenerate = os.path.join(self._tmp.name, "zero.json")
        _write_embedder_fixture(degenerate)
        with open(degenerate, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["matrix"] = [[0.0] * 32 for _ in range(EMBED_OUT_DIM)]
        payload["bias"] = [0.0] * EMBED_OUT_DIM
        with open(degenerate, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        adapter = self._adapter(weights_path=degenerate)
        adapter.load()
        with self.assertRaises(ModelError):  # no fake uniform fallback
            adapter.embed(_tone(), 16000)

    def test_embed_before_load_fails(self):
        with self.assertRaises(RuntimeError):
            self._adapter().embed(_tone(), 16000)

    def test_invalid_input_rejected(self):
        adapter = self._adapter()
        adapter.load()
        with self.assertRaises(ValueError):
            adapter.embed([], 16000)
        with self.assertRaises(ValueError):
            adapter.embed([0.1, float("nan")], 16000)
        with self.assertRaises(ValueError):
            adapter.embed([0.1, 2.0], 16000)
        with self.assertRaises(ValueError):
            adapter.embed(_tone(), -16000)

    def test_repr_hides_path(self):
        text = repr(self._adapter())
        self.assertNotIn(self.embedder_path, text)
        self.assertIn(EMBEDDER_VERSION, text)


class TestRealRegistry(_FixtureDir):
    def test_mock_selection_default(self):
        model = get_model(_settings())
        self.assertTrue(model.is_mock)
        from backend.models.embed_registry import get_embedder as _get_embedder

        self.assertTrue(_get_embedder(_settings()).is_mock)

    def test_real_detector_selection(self):
        model = get_model(_settings(
            model_name="real", detector_model=self.detector_path,
            model_version=DETECTOR_VERSION))
        self.assertFalse(model.is_mock)
        self.assertEqual(model.version, DETECTOR_VERSION)

    def test_real_embedder_selection(self):
        model = get_embedder(_settings(
            embedder_name="real", embedder_model=self.embedder_path,
            embedder_version=EMBEDDER_VERSION))
        self.assertFalse(model.is_mock)
        self.assertEqual(model.version, EMBEDDER_VERSION)
        self.assertEqual(model.embedding_dim, EMBED_OUT_DIM)

    def test_invalid_backend_rejected(self):
        from types import SimpleNamespace

        # Bypasses Settings validation to reach the registry branch.
        with self.assertRaises(ModelError):
            get_model(SimpleNamespace(model_name="weird"))
        with self.assertRaises(ModelError):
            get_embedder(SimpleNamespace(embedder_name="weird"))

    def test_real_missing_path_fails_at_config(self):
        with self.assertRaises(ValueError):
            _settings(model_name="real", detector_model="")
        with self.assertRaises(ValueError):
            _settings(embedder_name="real", embedder_model="")

    def test_real_load_failure_no_mock_fallback(self):
        missing = os.path.join(self._tmp.name, "gone.json")
        settings = _settings(model_name="real", detector_model=missing)
        with self.assertRaises(ModelError):
            get_model(settings)
        # And the registry did NOT cache a mock stand-in.
        reset_model_registry()
        self.assertTrue(get_model(_settings()).is_mock)

    def test_invalid_backend_name_rejected_at_config(self):
        with self.assertRaises(ValueError):
            _settings(model_name="weird")


class TestMixedMode(_FixtureDir):
    def _pipeline_settings(self, **overrides):
        from backend.pipeline import Backend3Pipeline

        params = dict(
            model_name="mock", embedder_name="mock",
            model_version=DETECTOR_VERSION,
            embedder_version=EMBEDDER_VERSION,
            detector_model=self.detector_path,
            embedder_model=self.embedder_path)
        params.update(overrides)
        return Backend3Pipeline(_settings(**params))

    def _chunk(self) -> dict:
        return {"audio": _tone(), "sample_rate": 16000,
                "session_id": "s", "chunk_id": "c", "is_speech": True}

    def test_real_detector_mock_embedder(self):
        pipeline = self._pipeline_settings(model_name="real")
        signals = pipeline.process_chunk(self._chunk())
        assert signals.synthetic is not None and signals.speaker is not None
        self.assertFalse(signals.synthetic.is_mock)
        self.assertEqual(signals.synthetic.model_version, DETECTOR_VERSION)
        self.assertTrue(signals.speaker.is_mock)

    def test_mock_detector_real_embedder(self):
        pipeline = self._pipeline_settings(embedder_name="real")
        signals = pipeline.process_chunk(self._chunk())
        assert signals.synthetic is not None and signals.speaker is not None
        self.assertTrue(signals.synthetic.is_mock)
        self.assertFalse(signals.speaker.is_mock)
        self.assertEqual(signals.speaker.model_version, EMBEDDER_VERSION)
        self.assertEqual(signals.speaker.dimension, EMBED_OUT_DIM)

    def test_real_real(self):
        pipeline = self._pipeline_settings(model_name="real", embedder_name="real")
        signals = pipeline.process_chunk(self._chunk())
        assert signals.synthetic is not None and signals.speaker is not None
        self.assertFalse(signals.synthetic.is_mock)
        self.assertFalse(signals.speaker.is_mock)

    def test_service_error_semantics(self):
        from backend.detector import SyntheticVoiceDetector, reset_detector

        reset_detector()
        missing = os.path.join(self._tmp.name, "gone.json")
        detector = SyntheticVoiceDetector(_settings(
            model_name="real", detector_model=missing))
        with self.assertRaises(ModelError):  # load failure, not a mock score
            detector.detect_chunk(self._chunk())
        reset_detector()


class TestRealModelPrivacy(_FixtureDir):
    def test_results_carry_no_audio(self):
        from backend.detector import SyntheticVoiceDetector, reset_detector

        reset_detector()
        try:
            detector = SyntheticVoiceDetector(_settings(
                model_name="real", detector_model=self.detector_path,
                model_version=DETECTOR_VERSION))
            result = detector.detect_chunk(
                {"audio": _tone(), "sample_rate": 16000,
                 "session_id": "s", "chunk_id": "c", "is_speech": True})
            text = json.dumps(result.to_dict())
            self.assertNotIn("audio", text)
            self.assertNotIn("embedding", text)
        finally:
            reset_detector()

    def test_error_messages_hide_samples(self):
        adapter = RealDetectorAdapter(self.detector_path, DETECTOR_VERSION)
        adapter.load()
        with self.assertRaises(ValueError) as ctx:
            adapter.predict_proba([0.1, 0.987654321, float("nan")], 16000)
        # Message names the problem; it never echoes sample values.
        self.assertNotIn("0.987654321", str(ctx.exception))


class TestOptionalRealIntegration(unittest.TestCase):
    def test_gated_integration(self):
        if os.getenv("VG_RUN_REAL_MODEL_TESTS") != "1":
            self.skipTest("real weights not supplied (set VG_RUN_REAL_MODEL_TESTS=1 "
                          "with VG_DETECTOR_MODEL/VG_EMBEDDER_MODEL to run).")
        detector_path = os.getenv("VG_DETECTOR_MODEL", "")
        embedder_path = os.getenv("VG_EMBEDDER_MODEL", "")
        if not detector_path or not embedder_path:
            self.skipTest("VG_DETECTOR_MODEL/VG_EMBEDDER_MODEL weights not supplied.")
        detector = RealDetectorAdapter(
            detector_path, os.getenv("VG_DETECTOR_VERSION", "real-detector-v1"))
        detector.load()
        score = detector.predict_proba(_tone(), 16000)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


if __name__ == "__main__":
    unittest.main()
