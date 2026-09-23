"""Tests for Backend 4 Part 3: profile / reference-vector store.

Stdlib unittest only. Deterministic fixtures; no audio, network, models
or downloads. Privacy tests assert vectors never surface outside the
integration boundary.
"""
from __future__ import annotations

import json
import threading
import unittest
from dataclasses import asdict

from backend.profile_store import (
    ProfileReference,
    ProfileStore,
    ReferenceMetadata,
    ReferenceVector,
)
from backend.schemas import ValidationError


def _vector(dim: int = 32, value: float = 0.25) -> list:
    return [value] * dim


class TestProfileStore(unittest.TestCase):
    def setUp(self):
        self.store = ProfileStore()

    def test_successful_enrollment(self):
        meta = self.store.enroll_reference(
            reference_id="usr-1042", owner_id="owner-1",
            embedding=_vector(), embedder_version="mock-spectral-v0.1.0",
            is_mock=True)
        self.assertIsInstance(meta, ReferenceMetadata)
        self.assertEqual(meta.reference_id, "usr-1042")
        self.assertEqual(len(self.store), 1)

    def test_successful_metadata_lookup(self):
        self.store.enroll_reference("usr-1042", "owner-1", _vector(),
                                    "mock-spectral-v0.1.0", True)
        meta = self.store.get_metadata("usr-1042")
        self.assertEqual(meta.dimension, 32)
        self.assertEqual(meta.embedder_version, "mock-spectral-v0.1.0")
        self.assertTrue(meta.is_mock)

    def test_successful_internal_reference_lookup(self):
        self.store.enroll_reference("usr-1042", "owner-1", _vector(),
                                    "mock-spectral-v0.1.0", True)
        ref = self.store.get_reference_vector("usr-1042")
        self.assertIsInstance(ref, ReferenceVector)
        self.assertEqual(len(ref.embedding), 32)
        self.assertEqual(ref.dimension, 32)
        self.assertEqual(ref.reference_id, "usr-1042")

    def test_missing_reference(self):
        with self.assertRaises(ValidationError):
            self.store.get_metadata("ghost")
        with self.assertRaises(ValidationError):
            self.store.get_reference_vector("ghost")

    def test_empty_reference_id(self):
        for bad in ("", "   ", None, 123):
            with self.assertRaises(ValidationError, msg=f"ref={bad!r}"):
                self.store.enroll_reference(bad, "owner-1", _vector(), "v1", True)
        for bad_str in ("", "   "):
            with self.assertRaises(ValidationError, msg=f"lookup={bad_str!r}"):
                self.store.get_metadata(bad_str)

    def test_empty_owner_id(self):
        for bad in ("", "   ", None):
            with self.assertRaises(ValidationError, msg=f"owner={bad!r}"):
                self.store.enroll_reference("usr-1", bad, _vector(), "v1", True)

    def test_empty_embedding(self):
        with self.assertRaises(ValidationError):
            self.store.enroll_reference("usr-1", "owner-1", [], "v1", True)

    def test_non_numeric_embedding(self):
        with self.assertRaises(ValidationError):
            self.store.enroll_reference("usr-1", "owner-1", [0.1, "x"], "v1", True)
        with self.assertRaises(ValidationError):
            self.store.enroll_reference("usr-1", "owner-1", [0.1, True], "v1", True)
        with self.assertRaises(ValidationError):
            self.store.enroll_reference("usr-1", "owner-1", "not-a-vector", "v1", True)

    def test_nan_embedding(self):
        with self.assertRaises(ValidationError):
            self.store.enroll_reference("usr-1", "owner-1", [0.1, float("nan")], "v1", True)

    def test_infinite_embedding(self):
        with self.assertRaises(ValidationError):
            self.store.enroll_reference("usr-1", "owner-1", [float("inf")], "v1", True)

    def test_invalid_embedder_version(self):
        for bad in ("", "   ", None, 42):
            with self.assertRaises(ValidationError, msg=f"version={bad!r}"):
                self.store.enroll_reference("usr-1", "owner-1", _vector(), bad, True)

    def test_invalid_is_mock(self):
        for bad in ("yes", 1, None):
            with self.assertRaises(ValidationError, msg=f"mock={bad!r}"):
                self.store.enroll_reference("usr-1", "owner-1", _vector(), "v1", bad)

    def test_dimension_inferred_correctly(self):
        meta = self.store.enroll_reference("usr-1", "owner-1", _vector(dim=7),
                                           "v1", False)
        self.assertEqual(meta.dimension, 7)
        ref = self.store.get_reference_vector("usr-1")
        self.assertEqual(ref.dimension, 7)
        self.assertEqual(len(ref.embedding), 7)

    def test_stored_vector_defensive_copy(self):
        original = _vector()
        self.store.enroll_reference("usr-1", "owner-1", original, "v1", True)
        original[0] = 999.0  # mutating caller input must not affect the store
        ref = self.store.get_reference_vector("usr-1")
        self.assertNotIn(999.0, ref.embedding)
        self.assertIsInstance(ref.embedding, tuple)  # immutable handoff

    def test_duplicate_reference_rejected(self):
        self.store.enroll_reference("usr-1", "owner-1", _vector(), "v1", True)
        with self.assertRaises(ValidationError):
            self.store.enroll_reference("usr-1", "owner-1", _vector(value=0.5), "v1", True)
        # Original untouched by the failed overwrite.
        self.assertEqual(self.store.get_reference_vector("usr-1").embedding[0], 0.25)

    def test_delete_reference(self):
        self.store.enroll_reference("usr-1", "owner-1", _vector(), "v1", True)
        self.assertTrue(self.store.delete_reference("usr-1"))
        self.assertFalse(self.store.delete_reference("usr-1"))  # idempotent

    def test_deleted_reference_unavailable(self):
        self.store.enroll_reference("usr-1", "owner-1", _vector(), "v1", True)
        self.store.delete_reference("usr-1")
        with self.assertRaises(ValidationError):
            self.store.get_metadata("usr-1")
        with self.assertRaises(ValidationError):
            self.store.get_reference_vector("usr-1")

    def test_clear_store(self):
        self.store.enroll_reference("a", "o", _vector(), "v1", True)
        self.store.enroll_reference("b", "o", _vector(), "v1", True)
        self.store.clear()
        self.assertEqual(len(self.store), 0)
        with self.assertRaises(ValidationError):
            self.store.get_metadata("a")

    def test_owner_match_succeeds(self):
        self.store.enroll_reference("usr-1", "owner-1", _vector(), "v1", True)
        meta = self.store.get_metadata_for_owner("usr-1", "owner-1")
        self.assertEqual(meta.reference_id, "usr-1")
        ref = self.store.get_reference_vector_for_owner("usr-1", "owner-1")
        self.assertEqual(len(ref.embedding), 32)

    def test_wrong_owner_denied(self):
        self.store.enroll_reference("usr-1", "owner-1", _vector(), "v1", True)
        with self.assertRaises(ValidationError):
            self.store.get_metadata_for_owner("usr-1", "owner-2")
        with self.assertRaises(ValidationError):
            self.store.get_reference_vector_for_owner("usr-1", "owner-2")

    def test_owner_mismatch_leaks_nothing(self):
        self.store.enroll_reference("usr-1", "owner-1", _vector(), "v1", True)
        mismatch_text = ""
        try:
            self.store.get_metadata_for_owner("usr-1", "owner-2")
            self.fail("expected ValidationError")
        except ValidationError as exc:
            mismatch_text = str(exc)
        self.assertNotIn("owner-1", mismatch_text)  # real owner never disclosed
        self.assertNotIn("0.25", mismatch_text)  # vector never disclosed
        # Identical surface for genuinely-missing IDs (no probing oracle).
        missing_text = ""
        try:
            self.store.get_metadata_for_owner("ghost", "owner-2")
            self.fail("expected ValidationError")
        except ValidationError as exc2:
            missing_text = str(exc2)
        self.assertEqual(mismatch_text, missing_text.replace("ghost", "usr-1"))

    def test_mock_provenance_preserved(self):
        self.store.enroll_reference("usr-1", "owner-1", _vector(),
                                    "mock-spectral-v0.1.0", True)
        ref = self.store.get_reference_vector("usr-1")
        self.assertTrue(ref.is_mock)
        self.assertEqual(ref.embedder_version, "mock-spectral-v0.1.0")

    def test_production_provenance_preserved(self):
        self.store.enroll_reference("usr-1", "owner-1", _vector(), "ecapa-v1", False)
        ref = self.store.get_reference_vector("usr-1")
        self.assertFalse(ref.is_mock)
        self.assertEqual(ref.embedder_version, "ecapa-v1")

    def test_cross_version_metadata_preserved(self):
        # Store must not gate on version; B3 similarity decides comparability.
        self.store.enroll_reference("usr-1", "owner-1", _vector(), "enc-v1", False)
        ref = self.store.get_reference_vector("usr-1")
        self.assertEqual(ref.embedder_version, "enc-v1")

    def test_dimension_mismatch_rejected_at_similarity(self):
        from backend.similarity import SpeakerSimilarityService

        self.store.enroll_reference("usr-1", "owner-1", _vector(dim=32), "v1", True)
        ref = self.store.get_reference_vector("usr-1")
        service = SpeakerSimilarityService()
        with self.assertRaises(ValidationError):
            service.compare(list(ref.embedding), [1.0, 0.0])  # 32 vs 2

    def test_raw_embedding_absent_from_metadata(self):
        self.store.enroll_reference("usr-1", "owner-1", _vector(), "v1", True)
        payload = asdict(self.store.get_metadata("usr-1"))
        self.assertNotIn("embedding", payload)
        self.assertNotIn("owner_id", payload)  # owner not exposed either
        json.dumps(payload)

    def test_no_raw_embedding_in_exception_text(self):
        self.store.enroll_reference("usr-1", "owner-1", _vector(value=0.77), "v1", True)
        with self.assertRaises(ValidationError) as ctx:
            self.store.get_metadata_for_owner("usr-1", "intruder")
        self.assertNotIn("0.77", str(ctx.exception))

    def test_reference_id_preserved_exactly(self):
        self.store.enroll_reference("Usr-1042_X", "owner-1", _vector(), "v1", True)
        self.assertEqual(self.store.get_metadata("Usr-1042_X").reference_id, "Usr-1042_X")
        self.assertEqual(self.store.get_reference_vector("Usr-1042_X").reference_id,
                         "Usr-1042_X")

    def test_no_extra_fields_stored(self):
        self.store.enroll_reference("usr-1", "owner-1", _vector(), "v1", True)
        record = self.store._get_record("usr-1")
        self.assertIsInstance(record, ProfileReference)
        self.assertEqual(
            set(asdict(record)),
            {"reference_id", "owner_id", "embedding", "dimension",
             "embedder_version", "is_mock", "created_at"})
        text = repr(record)
        self.assertNotIn("0.25", text)  # repr redacts the vector

    def test_concurrent_enrollment_and_lookup(self):
        errors: list = []

        def enroll(i: int) -> None:
            try:
                self.store.enroll_reference(f"u-{i}", f"o-{i % 4}", _vector(), "v1", True)
                self.store.get_metadata(f"u-{i}")
                self.store.get_reference_vector(f"u-{i}")
            except Exception as exc:  # noqa: BLE001 - collected for assertion
                errors.append(exc)

        threads = [threading.Thread(target=enroll, args=(i,)) for i in range(32)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.store), 32)


if __name__ == "__main__":
    unittest.main()
