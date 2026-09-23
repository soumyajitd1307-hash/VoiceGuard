"""Tests for Part 7 auth abstraction + production fail-closed. Stdlib only."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from backend.auth import (
    AuthenticatedPrincipal,
    AuthError,
    authenticate,
    request_owner,
    require_production_ready,
)
from backend.config import Settings
from backend.schemas import ValidationError


def _settings(**overrides) -> Settings:
    params = dict(
        model_name="mock", model_version="mock-heuristic-v0.1.0",
        embedder_name="mock", embedder_version="mock-spectral-v0.1.0",
        synthetic_threshold=0.7, real_threshold=0.3,
        min_duration_s=0.25, max_duration_s=30.0,
        max_id_length=128, log_level="CRITICAL",
        storage_backend="memory", storage_path="", env="development",
        auth_mode="disabled", auth_token="", dev_owner="")
    params.update(overrides)
    return Settings(**params)


def _env_settings(variables: dict) -> Settings:
    with mock.patch.dict(os.environ, variables, clear=False):
        return Settings()  # reads env inside the patched context


class TestAuthenticate(unittest.TestCase):
    def test_disabled_returns_none(self):
        self.assertIsNone(authenticate({}, _settings(auth_mode="disabled")))

    def test_token_valid(self):
        principal = authenticate(
            {"X-VoiceGuard-Token": "s3cret"}, _settings(
                auth_mode="token", auth_token="s3cret", dev_owner="owner-1"))
        self.assertIsInstance(principal, AuthenticatedPrincipal)
        assert principal is not None
        self.assertEqual(principal.owner_id, "owner-1")
        self.assertTrue(principal.development)

    def test_token_header_case_insensitive(self):
        principal = authenticate(
            {"x-voiceguard-token": "s3cret"}, _settings(
                auth_mode="token", auth_token="s3cret", dev_owner="o"))
        assert principal is not None
        self.assertEqual(principal.owner_id, "o")

    def test_token_missing(self):
        with self.assertRaises(AuthError):
            authenticate({}, _settings(
                auth_mode="token", auth_token="s3cret", dev_owner="o"))

    def test_token_wrong(self):
        with self.assertRaises(AuthError):
            authenticate({"x-voiceguard-token": "nope"}, _settings(
                auth_mode="token", auth_token="s3cret", dev_owner="o"))

    def test_token_misconfigured_no_token(self):
        with self.assertRaises(AuthError):
            authenticate({"x-voiceguard-token": "x"}, _settings(
                auth_mode="token", auth_token="", dev_owner="o"))

    def test_token_misconfigured_no_owner(self):
        with self.assertRaises(AuthError):
            authenticate({"x-voiceguard-token": "x"}, _settings(
                auth_mode="token", auth_token="x", dev_owner=""))

    def test_strict_always_rejects(self):
        with self.assertRaises(AuthError):
            authenticate({"x-voiceguard-token": "x"}, _settings(auth_mode="strict"))

    def test_unknown_mode_rejected(self):
        namespace = SimpleNamespace(auth_mode="weird")
        with self.assertRaises(AuthError):
            authenticate({}, namespace)  # type: ignore[arg-type]

    def test_token_never_leaked(self):
        principal = authenticate(
            {"x-voiceguard-token": "s3cret"}, _settings(
                auth_mode="token", auth_token="s3cret", dev_owner="o"))
        self.assertNotIn("s3cret", repr(principal))
        try:
            authenticate({"x-voiceguard-token": "wrong"}, _settings(
                auth_mode="token", auth_token="s3cret", dev_owner="o"))
        except AuthError as exc:
            self.assertNotIn("s3cret", str(exc))
            self.assertNotIn("wrong", str(exc))

    def test_request_owner_principal_wins(self):
        principal = AuthenticatedPrincipal("owner-1", "token", True)
        self.assertEqual(request_owner(principal, "owner-2"), "owner-1")

    def test_request_owner_internal(self):
        self.assertEqual(request_owner(None, "owner-9"), "owner-9")
        self.assertIsNone(request_owner(None))
        with self.assertRaises(ValidationError):
            request_owner(None, "")


class TestProductionReady(unittest.TestCase):
    def test_development_always_ok(self):
        require_production_ready(_settings(env="development"))

    def test_production_disabled_auth_fails(self):
        with self.assertRaises(AuthError):
            require_production_ready(_settings(
                env="production", storage_backend="sqlite",
                storage_path="/tmp/x.db", auth_mode="disabled"))

    def test_production_memory_storage_fails(self):
        with self.assertRaises(AuthError):
            require_production_ready(_settings(
                env="production", storage_backend="memory",
                auth_mode="token", auth_token="t", dev_owner="o"))

    def test_production_token_without_token_fails(self):
        with self.assertRaises(AuthError):
            require_production_ready(_settings(
                env="production", storage_backend="sqlite",
                storage_path="/tmp/x.db", auth_mode="token", auth_token=""))

    def test_production_strict_fails_without_idp(self):
        with self.assertRaises(AuthError):
            require_production_ready(_settings(
                env="production", storage_backend="sqlite",
                storage_path="/tmp/x.db", auth_mode="strict"))

    def test_production_ready_config_passes(self):
        require_production_ready(_settings(
            env="production", storage_backend="sqlite",
            storage_path="/tmp/x.db", auth_mode="token",
            auth_token="t", dev_owner="o"))

    def test_env_vars_wire_through(self):
        settings = _env_settings({
            "VG_STORAGE_BACKEND": "sqlite",
            "VG_STORAGE_PATH": "/tmp/v.db",
            "VG_AUTH_MODE": "token",
            "VG_AUTH_TOKEN": "t",
            "VG_DEV_OWNER": "o",
            "VG_ENV": "production",
        })
        self.assertEqual(settings.storage_backend, "sqlite")
        self.assertEqual(settings.auth_mode, "token")
        require_production_ready(settings)

    def test_invalid_env_values_rejected(self):
        with self.assertRaises(ValueError):
            _env_settings({"VG_STORAGE_BACKEND": "postgres"})
        with self.assertRaises(ValueError):
            _env_settings({"VG_AUTH_MODE": "oauth"})
        with self.assertRaises(ValueError):
            _env_settings({"VG_ENV": "staging"})


if __name__ == "__main__":
    unittest.main()
