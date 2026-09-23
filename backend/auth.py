"""Backend 4 Part 7: minimal authentication abstraction (stdlib only).

Modes (``VG_AUTH_MODE``), enforced against ``Settings``:

    disabled (default):
        Trusted-internal development default. ``authenticate`` returns
        None, meaning "no identity asserted"; callers fall back to
        explicit internal owner scoping. Must never be used in production
        (see ``require_production_ready``).
    token:
        Shared development/test token ONLY -- never production auth. The
        client presents ``X-VoiceGuard-Token``; on a constant-time match
        against ``VG_AUTH_TOKEN`` the explicitly configured ``VG_DEV_OWNER``
        identity is asserted. Tokens are never logged, never returned,
        and never appear in errors/reprs.
    strict:
        Fail-closed placeholder for a future real identity provider:
        every request is rejected until that provider exists.

Rules honored everywhere this module is used:
    * The authenticated principal is authoritative. Client-supplied
      ``owner_id`` values (body/query) are NEVER an authorization source;
      ``request_owner`` ignores them whenever a principal exists.
    * ``AuthError`` maps to HTTP 401 at the transport boundary.
    * Production (``VG_ENV=production``) fails closed via
      ``require_production_ready``: sqlite storage with a path, a
      non-disabled auth mode, and a configured token in token mode.
"""
from __future__ import annotations

import hmac
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.config import Settings

log = logging.getLogger(__name__)

TOKEN_HEADER = "x-voiceguard-token"


class AuthError(Exception):
    """Authentication/authorization failure (maps to HTTP 401)."""


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Request identity asserted by the auth layer (never by the client).

    ``development`` is True for the dev-tunnel identities (disabled/token
    modes); production integrations must assert False with real proof.
    The token itself is never stored here.
    """

    owner_id: str
    auth_type: str
    development: bool

    def __repr__(self) -> str:  # no secrets possible: token never held
        return (f"AuthenticatedPrincipal(owner_id={self.owner_id!r}, "
                f"auth_type={self.auth_type!r}, development={self.development})")


def _headers_lower(headers: Mapping) -> dict:
    try:
        items = headers.items()  # type: ignore[union-attr]
    except AttributeError:
        raise AuthError("unusable request headers.")
    return {str(key).lower(): value for key, value in items}


def authenticate(headers: Mapping | None, settings: Settings) -> AuthenticatedPrincipal | None:
    """Resolve the request principal, or None in disabled (dev) mode.

    Raises:
        AuthError: missing/misconfigured credentials, unknown identity.
    """
    mode = settings.auth_mode
    if mode == "disabled":
        return None
    if mode == "strict":
        raise AuthError("authentication is required but not configured.")
    if mode == "token":
        if not settings.auth_token:
            raise AuthError("token auth configured without VG_AUTH_TOKEN.")
        if not settings.dev_owner:
            raise AuthError("token auth configured without VG_DEV_OWNER.")
        presented = _headers_lower(headers or {}).get(TOKEN_HEADER)
        if not isinstance(presented, str) or not presented:
            raise AuthError("missing credentials.")
        if not hmac.compare_digest(presented, settings.auth_token):
            raise AuthError("invalid credentials.")
        log.info("token principal asserted (development-only identity)")
        return AuthenticatedPrincipal(
            owner_id=settings.dev_owner, auth_type="token", development=True)
    raise AuthError(f"unknown auth mode {mode!r}.")  # defensive; config validates


def request_owner(principal: AuthenticatedPrincipal | None,
                  supplied_owner_id: Any = None) -> str | None:
    """Resolve the authoritative owner for a request.

    A present principal always wins; client-supplied ``owner_id`` is
    ignored (spoof-proof by construction). Without a principal the
    explicitly supplied internal owner applies (trusted-internal use).
    """
    if principal is not None:
        return principal.owner_id
    if supplied_owner_id is None:
        return None
    if not isinstance(supplied_owner_id, str) or not supplied_owner_id.strip():
        from backend.schemas import ValidationError

        raise ValidationError("owner_id must be a non-empty string.")
    return supplied_owner_id


def require_production_ready(settings: Settings) -> None:
    """Fail closed for production: explicit storage + auth required.

    Raises:
        AuthError: production demanded without sqlite storage path,
            without authentication, or with token auth lacking a token.
    """
    if settings.env != "production":
        return
    problems = []
    if settings.storage_backend != "sqlite" or not settings.storage_path.strip():
        problems.append("production requires VG_STORAGE_BACKEND=sqlite with VG_STORAGE_PATH set")
    if settings.auth_mode == "disabled":
        problems.append("production requires VG_AUTH_MODE != disabled")
    if settings.auth_mode == "token" and not settings.auth_token:
        problems.append("production token auth requires VG_AUTH_TOKEN")
    if settings.auth_mode == "strict":
        problems.append("production strict mode has no identity provider yet")
    if problems:
        raise AuthError("production configuration incomplete: " + "; ".join(problems))
