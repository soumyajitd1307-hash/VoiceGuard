"""Tests for the Backend 2 -> Backend 3 handoff contract.

Stdlib unittest only (no pytest dependency). Model-independent:
no model is imported or scored here.
"""
from __future__ import annotations

import base64
import unittest

from backend.b2_contract import ProcessedSpeechChunk, from_dict, validate_chunk
from backend.config import Settings
from backend.schemas import ValidationError


def _settings() -> Settings:
    return Settings(
        model_name="mock",
        model_version="test",
        synthetic_threshold=0.7,
        real_threshold=0.3,
        min_duration_s=0.25,
        max_duration_s=30.0,
        max_id_length=128,
        log_level="CRITICAL",
    )


def _pcm16_bytes(n_samples: int = 8000) -> bytes:
    # 0.5s of silence-ish PCM16 at 16kHz (value 1000, valid even length).
    return (int(1000).to_bytes(2, byteorder="little", signed=True)) * n_samples


class TestB2Contract(unittest.TestCase):
    def test_valid_full_chunk_preserves_metadata(self):
        chunk = validate_chunk(
            ProcessedSpeechChunk(
                audio=_pcm16_bytes(),
                sample_rate=16000,
                session_id="1042",
                chunk_id="c0018",
                timestamp_s=18.0,
                language="en",
                is_speech=True,
                speech_ratio=0.92,
            ),
            _settings(),
        )
        self.assertEqual(chunk.session_id, "1042")
        self.assertEqual(chunk.chunk_id, "c0018")
        self.assertEqual(chunk.timestamp_s, 18.0)
        self.assertEqual(chunk.language, "en")
        self.assertTrue(chunk.is_speech_ready)
        self.assertAlmostEqual(chunk.duration_s(), 0.5)
        kwargs = chunk.to_detect_kwargs()
        self.assertEqual(
            set(kwargs),
            {"audio", "sample_rate", "session_id", "chunk_id", "audio_encoding"},
        )

    def test_minimal_chunk_uses_defaults(self):
        chunk = validate_chunk(
            ProcessedSpeechChunk(
                audio=[0.0] * 8000,
                sample_rate=16000,
                session_id="s",
                chunk_id="c",
            ),
            _settings(),
        )
        self.assertIsNone(chunk.timestamp_s)
        self.assertIsNone(chunk.language)
        self.assertIsNone(chunk.speech_ratio)
        self.assertTrue(chunk.is_speech)

    def test_non_speech_flag_preserved(self):
        chunk = validate_chunk(
            ProcessedSpeechChunk(
                audio=[0.0] * 8000,
                sample_rate=16000,
                session_id="s",
                chunk_id="c",
                is_speech=False,
                speech_ratio=0.05,
            ),
            _settings(),
        )
        self.assertFalse(chunk.is_speech_ready)

    def test_from_dict_wire_form_round_trip(self):
        payload = {
            "audio_base64": base64.b64encode(_pcm16_bytes()).decode("ascii"),
            "audio_encoding": "pcm16_base64",
            "sample_rate": 16000,
            "session_id": "1042",
            "chunk_id": "c0018",
            "timestamp_s": 18.0,
            "language": "en",
            "is_speech": True,
            "speech_ratio": 0.92,
        }
        chunk = from_dict(payload, _settings())
        out = chunk.to_dict()
        self.assertEqual(out["audio_base64"], payload["audio_base64"])
        self.assertEqual(out["session_id"], "1042")
        again = from_dict(out, _settings())
        self.assertEqual(again.chunk_id, "c0018")

    def test_rejects_bad_sample_rate(self):
        with self.assertRaises(ValidationError):
            validate_chunk(
                ProcessedSpeechChunk(
                    audio=[0.0] * 8000, sample_rate=12345,
                    session_id="s", chunk_id="c",
                ),
                _settings(),
            )

    def test_rejects_empty_ids_and_bad_flags(self):
        with self.assertRaises(ValidationError):
            validate_chunk(
                ProcessedSpeechChunk(
                    audio=[0.0] * 8000, sample_rate=16000,
                    session_id="  ", chunk_id="c",
                ),
                _settings(),
            )
        with self.assertRaises(ValidationError):
            validate_chunk(
                ProcessedSpeechChunk(
                    audio=[0.0] * 8000, sample_rate=16000,
                    session_id="s", chunk_id="c", speech_ratio=1.5,
                ),
                _settings(),
            )
        with self.assertRaises(ValidationError):
            validate_chunk(
                ProcessedSpeechChunk(
                    audio=[0.0] * 8000, sample_rate=16000,
                    session_id="s", chunk_id="c", timestamp_s=-1.0,
                ),
                _settings(),
            )

    def test_rejects_too_short_audio(self):
        with self.assertRaises(ValidationError):
            validate_chunk(
                ProcessedSpeechChunk(
                    audio=[0.0] * 10, sample_rate=16000,
                    session_id="s", chunk_id="c",
                ),
                _settings(),
            )


if __name__ == "__main__":
    unittest.main()
