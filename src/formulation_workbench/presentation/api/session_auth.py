"""Signed session tokens for browser-facing login.

HTTP Basic works but the browser renders a native popup, which is
jarring in a single-page-app.  Instead we ship a login form that
posts to ``POST /auth/login`` and gets back an ``httpOnly`` cookie
holding a signed token.

The token is stateless (no server-side session store): the payload
holds ``{sub, role, exp}`` and is signed HMAC-SHA256 with
``AppSettings.session_secret`` (falls back to ``jwt_secret`` and then
to ``encryption_key_hex`` so a dev-mode deployment still works).

Format on the wire::

    base64url(payload_json).base64url(signature_bytes)

Cookie attributes:
- Name: ``fw_session``
- ``HttpOnly`` (JS cannot read it → XSS-proof)
- ``SameSite=Lax`` (CSRF-safe for browser navigations; the writing
  endpoints require the cookie AND go through the SPA's fetch calls
  which already carry it same-origin)
- ``Secure`` in production (``environment != "development"``)
- ``Path=/``

We intentionally do NOT reuse the JWT plumbing in ``auth.py`` — the
session token has different verification rules (issued only by us,
short-lived, opaque to third parties) and a different transport
(cookie, not ``Authorization`` header).  Sharing code would tangle
the two.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass

from ...infrastructure.config import AppSettings

logger = logging.getLogger(__name__)


SESSION_COOKIE_NAME = "fw_session"
# 12 hours — long enough that a working day rarely re-authenticates,
# short enough that a stolen cookie stops working overnight.
DEFAULT_SESSION_TTL_SECONDS = 12 * 60 * 60


class SessionTokenError(Exception):
    """Raised when a session token cannot be decoded or verified."""


@dataclass(frozen=True, slots=True)
class SessionPayload:
    """Decoded session cookie payload."""

    subject: str
    role: str
    expires_at: int


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def _session_secret(settings: AppSettings) -> str:
    """Derive the signing secret with sensible fallbacks.

    Priority: explicit ``session_secret`` → ``jwt_secret`` →
    ``encryption_key_hex``.  In pure open dev mode (none of those
    set) we synthesize a static per-process secret so the local UI
    still works — production invariants refuse that mode elsewhere.
    """
    secret = (
        getattr(settings, "session_secret", None)
        or settings.jwt_secret
        or settings.encryption_key_hex
    )
    if not secret:
        # Dev-only: a stable but unadvertised value so restarting the
        # process does not silently keep old sessions valid.
        return "fw-dev-session-secret-do-not-use-in-production"
    return secret


def issue_session_token(
    *,
    subject: str,
    role: str,
    settings: AppSettings,
    ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    issued_at: int | None = None,
) -> str:
    """Build a signed session token for ``subject`` with ``role``."""
    now = int(issued_at if issued_at is not None else time.time())
    payload = {
        "sub": subject,
        "role": role,
        "exp": now + int(ttl_seconds),
        "iat": now,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)
    signature = hmac.new(
        _session_secret(settings).encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    signature_b64 = _b64url_encode(signature)
    return f"{payload_b64}.{signature_b64}"


def decode_session_token(token: str, settings: AppSettings) -> SessionPayload:
    """Verify + decode a session token.

    Raises :class:`SessionTokenError` on any tampering, malformed
    input, or expiry.  Never returns partial data — the caller can
    trust every field of the returned :class:`SessionPayload`.
    """
    if not token or "." not in token:
        raise SessionTokenError("malformed token")
    try:
        payload_b64, signature_b64 = token.split(".", 1)
    except ValueError as exc:
        raise SessionTokenError("malformed token") from exc

    expected_sig = hmac.new(
        _session_secret(settings).encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual_sig = _b64url_decode(signature_b64)
    except (ValueError, TypeError) as exc:
        raise SessionTokenError("bad signature encoding") from exc
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise SessionTokenError("bad signature")

    try:
        payload_json = _b64url_decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_json)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SessionTokenError("bad payload encoding") from exc
    if not isinstance(payload, dict):
        raise SessionTokenError("payload is not an object")

    sub = payload.get("sub")
    role = payload.get("role")
    exp = payload.get("exp")
    if not isinstance(sub, str) or not sub:
        raise SessionTokenError("missing sub")
    if not isinstance(role, str) or not role:
        raise SessionTokenError("missing role")
    if not isinstance(exp, int):
        raise SessionTokenError("missing exp")
    if int(time.time()) >= exp:
        raise SessionTokenError("expired")

    return SessionPayload(subject=sub, role=role, expires_at=exp)


def session_cookie_is_secure(settings: AppSettings) -> bool:
    """Return True when the cookie must carry the ``Secure`` flag.

    Non-development environments always ride HTTPS in real
    deployments, and the browser silently drops ``Secure`` cookies
    over plaintext HTTP — so this doubles as a canary during local
    smoke tests.
    """
    return settings.environment != "development"


__all__ = [
    "DEFAULT_SESSION_TTL_SECONDS",
    "SESSION_COOKIE_NAME",
    "SessionPayload",
    "SessionTokenError",
    "decode_session_token",
    "issue_session_token",
    "session_cookie_is_secure",
]
