"""Backend 4 Part 3: in-memory speaker profile / reference-vector store.

Purpose: let a caller/session own a trusted enrolled voice reference that
B4 later resolves by ``reference_id`` for B3 similarity comparison.

Trust boundary (three access tiers -- do not blur them):
    1. Public metadata access (``get_metadata``): dimension, versions and
       mock provenance ONLY. Never the embedding, never the owner.
    2. Owner-authorized access (``*_for_owner``): same metadata, gated on
       ``owner_id`` match. Missing and wrong-owner both report "not found"
       so callers cannot probe another owner's references.
    3. Private B3-integration access (``get_reference_vector*``): the raw
       embedding plus the minimal fields B3 similarity needs
       (embedding, dimension, embedder_version, is_mock, reference_id).
       For B4-internal wiring only -- never API/WS/frontend facing.

Privacy rules enforced here:
    * Raw vectors live ONLY inside locked ``_records`` and inside the
      integration result. They never enter logs, error messages, reprs,
      metadata results, RiskAssessment, RiskUpdate, reasons or alerts.
    * ``ProfileReference.__repr__`` redacts the vector.
    * Stored vectors are defensive float-tuple copies: mutating caller
      input afterwards cannot mutate the store, and tuples handed out
      cannot be mutated in place.
    * Nothing stored except the reference itself: no audio, phone numbers,
      names, RiskUpdates or frontend objects. No free-form metadata bag
      (rejected by design -- fewer places to leak PII).
    * IDs are opaque and stored EXACTLY as given (no stripping/casing):
      identity is never derived from them.

Enrollment policy:
    * ``reference_id`` / ``owner_id``: non-empty strings (whitespace-only
      rejected); stored verbatim.
    * ``embedding``: non-empty finite-numeric sequence; dimension inferred
      as ``len(vector)`` (guarded by ``MAX_DIMENSION``); B4 never
      normalizes, pads, truncates or transforms it.
    * ``embedder_version``: non-empty string, stored verbatim, never
      invented. Cross-version use is ALLOWED at lookup -- B3 similarity
      documents such comparisons as technically possible but
      non-comparable; the version metadata travels along so B4/B3 can
      decide explicitly. Dimension mismatch is a hard error at the
      similarity boundary (raised by B3, never papered over here).
    * ``is_mock``: real bool, preserved end to end (mock references stay
      visibly mock; never production evidence).
    * Duplicate ``reference_id`` enrollment fails (no silent overwrite, no
      replace operation -- add one only on demonstrated need).

Lifecycle: enroll -> lookup (metadata / owner / integration) -> delete ->
clear (tests). Delete is immediate and idempotent (returns False when
absent). All operations hold an RLock; the store is intentionally small
and replaceable by a DB-backed repository later.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backend.schemas import ValidationError

log = logging.getLogger(__name__)

MAX_DIMENSION = 8192  # sanity guard against degenerate/giant payloads


@dataclass(frozen=True)
class ProfileReference:
    """Internal enrolled record. Never leaves the store except through the
    integration accessor, and never serializes whole."""

    reference_id: str
    owner_id: str
    embedding: tuple
    dimension: int
    embedder_version: str
    is_mock: bool
    created_at: float

    def __repr__(self) -> str:  # privacy: vector contents never in reprs/logs
        return (
            f"ProfileReference(reference_id={self.reference_id!r}, "
            f"dimension={self.dimension}, embedder_version={self.embedder_version!r}, "
            f"is_mock={self.is_mock}, embedding=<{self.dimension}-dim vector withheld>)"
        )


@dataclass(frozen=True)
class ReferenceMetadata:
    """Public lookup result: provenance without the vector or the owner."""

    reference_id: str
    dimension: int
    embedder_version: str
    is_mock: bool
    created_at: float


@dataclass(frozen=True)
class ReferenceVector:
    """Private B3-integration payload: exactly what similarity needs, and
    nothing else (no owner, no unrelated profile data)."""

    reference_id: str
    embedding: tuple
    dimension: int
    embedder_version: str
    is_mock: bool


def _check_id(value: Any, field: str, max_len: int = 128) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string.")
    if not value or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string.")
    if len(value) > max_len:
        raise ValidationError(f"{field} exceeds max length {max_len}.")
    return value  # stored verbatim once validated


def _check_version(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("embedder_version must be a string.")
    if not value or not value.strip():
        raise ValidationError("embedder_version must be a non-empty string.")
    return value


def _check_mock(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValidationError("is_mock must be a boolean.")
    return value


def _copy_vector(embedding: Any) -> tuple:
    if isinstance(embedding, (str, bytes, bytearray)) or not isinstance(embedding, Sequence):
        raise ValidationError("embedding must be a sequence of numbers.")
    try:
        items = list(embedding)
    except TypeError:
        raise ValidationError("embedding must be a sequence of numbers.") from None
    if len(items) == 0:
        raise ValidationError("embedding must contain at least one value.")
    if len(items) > MAX_DIMENSION:
        raise ValidationError(f"embedding dimension {len(items)} exceeds maximum {MAX_DIMENSION}.")
    out = []
    for idx, item in enumerate(items):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValidationError(f"embedding[{idx}] must be a number.")
        f = float(item)
        if math.isnan(f):
            raise ValidationError(f"embedding[{idx}] must not be NaN.")
        if math.isinf(f):
            raise ValidationError(f"embedding[{idx}] must be finite.")
        out.append(f)
    return tuple(out)  # immutable defensive copy


class ProfileStore:
    """Small in-memory reference store. Dependency-free and deterministic."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, ProfileReference] = {}

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def enroll_reference(
        self,
        reference_id: str,
        owner_id: str,
        embedding: Sequence[float],
        embedder_version: str,
        is_mock: bool,
    ) -> ReferenceMetadata:
        """Enroll one reference vector. Duplicate IDs fail (no overwrite)."""
        cleaned_id = _check_id(reference_id, "reference_id")
        cleaned_owner = _check_id(owner_id, "owner_id")
        vector = _copy_vector(embedding)
        version = _check_version(embedder_version)
        mock = _check_mock(is_mock)
        with self._lock:
            if cleaned_id in self._records:
                # Generic message: reveals nothing about the existing owner.
                raise ValidationError(
                    f"reference_id {cleaned_id!r} is already enrolled."
                )
            record = ProfileReference(
                reference_id=cleaned_id,
                owner_id=cleaned_owner,
                embedding=vector,
                dimension=len(vector),
                embedder_version=version,
                is_mock=mock,
                created_at=time.time(),
            )
            self._records[cleaned_id] = record
        log.info(
            "enrolled reference_id=%r dimension=%d mock=%s",
            cleaned_id, len(vector), mock,
        )
        return self._metadata_of(record)

    def get_metadata(self, reference_id: str) -> ReferenceMetadata:
        """Public metadata lookup (no vector, no owner)."""
        return self._metadata_of(self._get_record(reference_id))

    def get_metadata_for_owner(self, reference_id: str, owner_id: str) -> ReferenceMetadata:
        """Owner-authorized metadata lookup."""
        return self._metadata_of(self._get_record_for_owner(reference_id, owner_id))

    def get_reference_vector(self, reference_id: str) -> ReferenceVector:
        """Private B3-integration lookup: vector + similarity essentials."""
        return self._vector_of(self._get_record(reference_id))

    def get_reference_vector_for_owner(
        self, reference_id: str, owner_id: str
    ) -> ReferenceVector:
        """Owner-authorized B3-integration lookup."""
        return self._vector_of(self._get_record_for_owner(reference_id, owner_id))

    def delete_reference(self, reference_id: str) -> bool:
        """Remove a reference immediately. True if one existed."""
        cleaned_id = _check_id(reference_id, "reference_id")
        with self._lock:
            existed = self._records.pop(cleaned_id, None) is not None
        if existed:
            log.info("deleted reference_id=%r", cleaned_id)
        return existed

    def clear(self) -> None:
        """Remove all references (tests / controlled reset)."""
        with self._lock:
            self._records.clear()

    def _get_record(self, reference_id: str) -> ProfileReference:
        cleaned_id = _check_id(reference_id, "reference_id")
        with self._lock:
            record = self._records.get(cleaned_id)
        if record is None:
            raise ValidationError(f"reference_id {cleaned_id!r} not found.")
        return record

    def _get_record_for_owner(self, reference_id: str, owner_id: str) -> ProfileReference:
        # Owner validated first so malformed callers get usage errors, while
        # unknown-ID and wrong-owner both surface as plain "not found".
        cleaned_owner = _check_id(owner_id, "owner_id")
        try:
            record = self._get_record(reference_id)
        except ValidationError as exc:
            raise ValidationError(f"reference_id {reference_id!r} not found.") from exc
        if record.owner_id != cleaned_owner:
            raise ValidationError(f"reference_id {reference_id!r} not found.")
        return record

    @staticmethod
    def _metadata_of(record: ProfileReference) -> ReferenceMetadata:
        return ReferenceMetadata(
            reference_id=record.reference_id,
            dimension=record.dimension,
            embedder_version=record.embedder_version,
            is_mock=record.is_mock,
            created_at=record.created_at,
        )

    @staticmethod
    def _vector_of(record: ProfileReference) -> ReferenceVector:
        return ReferenceVector(
            reference_id=record.reference_id,
            embedding=tuple(record.embedding),  # fresh immutable copy
            dimension=record.dimension,
            embedder_version=record.embedder_version,
            is_mock=record.is_mock,
        )
