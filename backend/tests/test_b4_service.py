"""Tests for Backend 4 Part 4: application / orchestration service.

Stdlib unittest only. Integration tests exercise the real ProfileStore,
Backend3Pipeline, RiskFusionEngine and RiskUpdate adapter; doubles isolate
orchestration and error paths. No network, downloads or credentials.
"""
from __future__ import annotations

import io
import json
import logging
import math
import unittest
from unittest import mock

from backend.b4_schemas import RiskAssessment
from backend.b4_service import Backend4Service, get_b4_service, reset_b4_service
from backend.config import Settings
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


def _tone(n: int = 8000) -> list:
    return [0.5 * math.sin(2.0 * math.pi * 440.0 * i / 16000) for i in range(n)]


def _chunk(**overrides) -> dict:
    params = dict(
        audio=_tone(),
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
    assessment = payload["assessment"]
    assessment.pop("processing_time_ms", None)
    for key in ("synthetic", "speaker", "similarity"):
        nested = assessment.get(key)
        if isinstance(nested, dict):
            nested.pop("processing_time_ms", None)
    payload.pop("metadata", None)
    return payload


class TestBackend4Service(unittest.TestCase):
    def setUp(self):
        from backend.detector import reset_detector
        from backend.embeddings import reset_embedding_service
        from backend.models.embed_registry import reset_embedder_registry
        from backend.models.registry import reset_model_registry
        from backend.pipeline import reset_pipeline

        reset_detector()
        reset_embedding_service()
        reset_embedder_registry()
        reset_model_registry()
        reset_pipeline()
        reset_b4_service()

    def tearDown(self):
        reset_b4_service()

    def _service(self) -> Backend4Service:
        return Backend4Service(_settings())

    def _enrolled(self, service: Backend4Service, ref: str = "usr-1042",
                  owner: str = "owner-1", mock: bool = True) -> None:
        from backend.embeddings import SpeakerEmbeddingService

        vector = SpeakerEmbeddingService(_settings()).embed(_chunk()).embedding
        service.enroll_reference(
            reference_id=ref, owner_id=owner, embedding=list(vector),
            embedder_version="mock-spectral-v0.1.0", is_mock=mock)

    def test_service_construction(self):
        service = self._service()
        self.assertIsInstance(service, Backend4Service)
        self.assertIs(get_b4_service(), get_b4_service())

    def test_process_without_reference(self):
        result = self._service().process_chunk(_chunk())
        self.assertIsNotNone(result.assessment.synthetic_probability)
        self.assertIsNone(result.assessment.speaker_consistency)

    def test_process_with_reference(self):
        service = self._service()
        self._enrolled(service)
        result = service.process_chunk(_chunk(), owner_id="owner-1",
                                       reference_id="usr-1042")
        self.assertIsNotNone(result.assessment.speaker_consistency)
        assert result.assessment.provenance is not None
        self.assertEqual(result.assessment.provenance.reference_id, "usr-1042")

    def test_missing_reference(self):
        with self.assertRaises(ValidationError):
            self._service().process_chunk(_chunk(), reference_id="ghost")

    def test_wrong_owner(self):
        service = self._service()
        self._enrolled(service)
        with self.assertRaises(ValidationError):
            service.process_chunk(_chunk(), owner_id="intruder",
                                  reference_id="usr-1042")

    def test_owner_aware_lookup(self):
        service = self._service()
        self._enrolled(service)
        result = service.process_chunk(_chunk(), owner_id="owner-1",
                                       reference_id="usr-1042")
        self.assertIsNotNone(result.assessment.speaker_consistency)

    def test_owner_omitted_internal_lookup(self):
        service = self._service()
        self._enrolled(service)
        # Trusted in-process path: resolves without owner_id.
        result = service.process_chunk(_chunk(), reference_id="usr-1042")
        self.assertIsNotNone(result.assessment.speaker_consistency)

    def test_reference_id_passed_unchanged(self):
        service = self._service()
        self._enrolled(service, ref="Usr-9_X")
        result = service.process_chunk(_chunk(), reference_id="Usr-9_X")
        assert result.assessment.provenance is not None
        self.assertEqual(result.assessment.provenance.reference_id, "Usr-9_X")

    def test_reference_embedding_reaches_b3(self):
        service = self._service()
        self._enrolled(service)
        with mock.patch.object(
            service._pipeline, "process_chunk",
            wraps=service._pipeline.process_chunk,
        ) as spy:
            service.process_chunk(_chunk(), reference_id="usr-1042")
            _, kwargs = spy.call_args
            self.assertIsNotNone(kwargs["reference_embedding"])
            self.assertEqual(kwargs["reference_id"], "usr-1042")
            self.assertEqual(len(kwargs["reference_embedding"]), 32)

    def test_no_reference_means_no_similarity(self):
        service = self._service()
        with mock.patch.object(
            service._pipeline, "process_chunk",
            wraps=service._pipeline.process_chunk,
        ) as spy:
            result = service.process_chunk(_chunk())
            _, kwargs = spy.call_args
            self.assertIsNone(kwargs["reference_embedding"])
            self.assertIsNone(kwargs["reference_id"])
            self.assertIsNone(result.assessment.speaker_consistency)

    def test_signals_reach_risk_engine(self):
        service = self._service()
        with mock.patch.object(
            service._risk_engine, "assess",
            wraps=service._risk_engine.assess,
        ) as spy:
            service.process_chunk(_chunk())
            (signals,), _ = spy.call_args
            self.assertIsInstance(signals, Backend3Signals)
            self.assertEqual(signals.session_id, "1042")

    def test_assessment_returned(self):
        result = self._service().process_chunk(_chunk())
        self.assertIsInstance(result.assessment, RiskAssessment)
        self.assertIsNotNone(result.assessment.risk_score)

    def test_risk_update_returned(self):
        result = self._service().process_chunk(_chunk())
        self.assertEqual(result.risk_update["type"], "risk_update")
        self.assertEqual(result.risk_update["callId"], "1042")

    def test_assessment_update_same_session_chunk(self):
        result = self._service().process_chunk(_chunk())
        self.assertEqual(result.assessment.session_id, "1042")
        self.assertEqual(result.assessment.chunk_id, "c0018")
        self.assertEqual(result.provenance, result.assessment.provenance)

    def test_timestamp_passed_correctly(self):
        result = self._service().process_chunk(_chunk(), timestamp=42.5)
        self.assertAlmostEqual(result.risk_update["timestamp"], 42.5)
        from_chunk = self._service().process_chunk(_chunk())  # timestamp_s=18.0
        self.assertAlmostEqual(from_chunk.risk_update["timestamp"], 18.0)
        no_time = _chunk()
        del no_time["timestamp_s"]
        with self.assertRaises(ValidationError):
            self._service().process_chunk(no_time)

    def test_missing_similarity_stays_none(self):
        result = self._service().process_chunk(_chunk())
        self.assertIsNone(result.assessment.speaker_consistency)

    def test_synthetic_only_fusion(self):
        result = self._service().process_chunk(_chunk())
        self.assertAlmostEqual(
            result.assessment.risk_score,
            round(result.assessment.synthetic_probability * 100.0, 2))

    def test_speaker_plus_synthetic_fusion(self):
        service = self._service()
        self._enrolled(service)
        result = service.process_chunk(_chunk(), reference_id="usr-1042")
        self.assertIsNotNone(result.assessment.synthetic_probability)
        self.assertIsNotNone(result.assessment.speaker_consistency)
        self.assertIsNotNone(result.assessment.risk_score)

    def test_no_usable_signals_unknown(self):
        from backend.risk_engine import RiskFusionEngine

        empty = Backend3Signals(session_id="s", chunk_id="c")
        assessment = RiskFusionEngine().assess(empty)
        self.assertIsNone(assessment.risk_score)
        self.assertEqual(assessment.risk_level, "UNKNOWN")

    def test_mock_b3_propagates(self):
        result = self._service().process_chunk(_chunk())
        self.assertTrue(result.assessment.is_mock)

    def test_mock_reference_propagates(self):
        service = self._service()
        self._enrolled(service, mock=True)
        result = service.process_chunk(_chunk(), reference_id="usr-1042")
        self.assertTrue(result.assessment.is_mock)
        codes = {r.code for r in result.assessment.reasons}
        self.assertIn("REFERENCE_PROVENANCE", codes)

    def test_mock_reference_plus_nonmock_b3_stays_mock(self):
        from backend.signals import build_backend3_signals

        service = self._service()
        # Non-mock B3 signals built by hand...
        bundle_signals = build_backend3_signals(
            detection_result={
                "label": "real", "synthetic_probability": 0.1,
                "model_version": "cm-real-v2", "processing_time_ms": 1.0,
                "session_id": "1042", "chunk_id": "c0018", "is_mock": False})
        with mock.patch.object(service._pipeline, "process_chunk",
                               return_value=bundle_signals):
            service.enroll_reference("usr-1", "o", [0.1] * 8, "mock-v1", True)
            result = service.process_chunk(_chunk(), reference_id="usr-1")
            self.assertTrue(result.assessment.is_mock)
            codes = {r.code for r in result.assessment.reasons}
            self.assertIn("MOCK_MODEL_SIGNAL", codes)

    def test_provenance_versions_preserved(self):
        service = self._service()
        self._enrolled(service)
        result = service.process_chunk(_chunk(), reference_id="usr-1042")
        provenance = result.assessment.provenance
        self.assertEqual(provenance.detector_version, "mock-heuristic-v0.1.0")
        self.assertEqual(provenance.similarity_version, "mock-spectral-v0.1.0")

    def test_reference_embedder_version_preserved(self):
        from backend.embeddings import SpeakerEmbeddingService

        service = self._service()
        vector = SpeakerEmbeddingService(_settings()).embed(_chunk()).embedding
        service.enroll_reference("usr-1", "o", list(vector), "enc-v9", False)
        result = service.process_chunk(_chunk(), reference_id="usr-1")
        texts = " ".join(r.message for r in result.assessment.reasons)
        self.assertIn("enc-v9", texts)

    def test_no_embedding_in_result(self):
        service = self._service()
        self._enrolled(service)
        result = service.process_chunk(_chunk(), reference_id="usr-1042")
        text = json.dumps(result.to_dict())
        self.assertNotIn("embedding", text)

    def test_no_embedding_in_assessment(self):
        result = self._service().process_chunk(_chunk())
        self.assertNotIn("embedding", json.dumps(result.assessment.to_dict()))

    def test_no_embedding_in_risk_update(self):
        result = self._service().process_chunk(_chunk())
        self.assertNotIn("embedding", json.dumps(result.risk_update))

    def test_enrollment_delegates(self):
        service = self._service()
        meta = service.enroll_reference("usr-1", "o", [0.2] * 8, "v1", True)
        self.assertEqual(meta.reference_id, "usr-1")
        with self.assertRaises(ValidationError):
            service.enroll_reference("usr-1", "o", [0.2] * 8, "v1", True)

    def test_metadata_lookup_delegates(self):
        service = self._service()
        service.enroll_reference("usr-1", "o", [0.2] * 8, "v1", True)
        self.assertEqual(service.get_reference_metadata("usr-1").dimension, 8)
        self.assertEqual(
            service.get_reference_metadata("usr-1", owner_id="o").dimension, 8)
        with self.assertRaises(ValidationError):
            service.get_reference_metadata("usr-1", owner_id="intruder")

    def test_deletion_delegates(self):
        service = self._service()
        service.enroll_reference("usr-1", "o", [0.2] * 8, "v1", True)
        self.assertTrue(service.delete_reference("usr-1"))
        with self.assertRaises(ValidationError):
            service.process_chunk(_chunk(), reference_id="usr-1")

    def test_b3_error_propagates(self):
        with self.assertRaises(ValidationError):
            self._service().process_chunk({"sample_rate": 16000})
        service = self._service()
        with mock.patch.object(service._pipeline, "process_chunk",
                               side_effect=ModelError("b3 down")):
            with self.assertRaises(ModelError):
                service.process_chunk(_chunk())

    def test_risk_engine_error_propagates(self):
        service = self._service()
        with mock.patch.object(service._risk_engine, "assess",
                               side_effect=ModelError("fusion down")):
            with self.assertRaises(ModelError):
                service.process_chunk(_chunk())

    def test_risk_update_error_propagates(self):
        import backend.b4_service as service_module

        service = self._service()
        with mock.patch.object(service_module, "to_risk_update",
                               side_effect=ValidationError("no score")):
            with self.assertRaises(ValidationError):
                service.process_chunk(_chunk())

    def test_chunk_unchanged(self):
        chunk = _chunk()
        snapshot = json.loads(json.dumps(chunk))
        self._service().process_chunk(chunk)
        self.assertEqual(json.loads(json.dumps(chunk)), snapshot)

    def test_no_frontend_or_transport_imports(self):
        import pathlib

        source = pathlib.Path(__file__).resolve().parent.parent / "b4_service.py"
        imports = [
            line.strip().lower() for line in
            source.read_text(encoding="utf-8").splitlines()
            if line.strip().lower().startswith(("import ", "from "))
        ]
        for token in ("frontend", "websocket", "fastapi", "flask", "sqlite",
                      "requests", "httpx"):
            self.assertFalse(any(token in line for line in imports),
                             f"transport dependency in imports: {token}")

    def test_deterministic_behavior(self):
        service = self._service()
        first = _strip_timings(service.process_chunk(_chunk()).to_dict())
        second = _strip_timings(service.process_chunk(_chunk()).to_dict())
        # created_at varies per enrollment only; no enrollment here.
        self.assertEqual(first, second)

    def test_public_serialization_privacy(self):
        service = self._service()
        self._enrolled(service)
        result = service.process_chunk(
            _chunk(), owner_id="owner-1", reference_id="usr-1042")
        payload = result.to_dict()
        text = json.dumps(payload)
        for secret in ("embedding", "owner-1", "ProfileReference", "audio"):
            self.assertNotIn(secret, text)
        self.assertNotIn("embedding", repr(result))
        self.assertEqual(set(payload), {"assessment", "risk_update", "provenance"})


if __name__ == "__main__":
    unittest.main()
