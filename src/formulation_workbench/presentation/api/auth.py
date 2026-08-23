"""Authentication + coarse-grained authorisation.

Three modes are supported, in order of preference:

1. **JWT bearer** (``FW_JWT_SECRET`` set, ``FW_JWT_ISSUER`` optional):
   HS256 by default (configurable via ``FW_JWT_ALGORITHM``). Any RFC 7519
   compliant token that verifies is accepted. Scopes are read from the
   ``scope`` claim (space-separated) or the ``scopes`` claim (list).

2. **Static bearer** (``FW_API_TOKEN`` set): the legacy token from
   1.1.x. Automatically granted the ``recipes:read``, ``recipes:write``
   scopes so existing clients keep working.

3. **Open** (both unset, non-production only): every request is treated
   as an anonymous "system" principal with all scopes.  Rejected in
   production by :meth:`AppSettings.enforce_production_invariants`.

We use PyJWT if it's installed, and fall back to a tiny in-tree HS256
implementation otherwise — that fallback exists so unit tests never
require an optional dependency, but production installs should always
pull ``pyjwt`` via ``[jwt]`` extra.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from ...infrastructure.config import AppSettings
from .dependencies import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated caller."""

    subject: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    mode: str = "anonymous"

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes or "*" in self.scopes


_READ_SCOPE = "recipes:read"
_WRITE_SCOPE = "recipes:write"


# ---------------------------------------------------------------------------
# Minimal HS256 verifier (fallback when PyJWT is not installed)
# ---------------------------------------------------------------------------
def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def _decode_jwt_hs256(token: str, secret: str) -> dict[str, object]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("token must have three segments")
    header_b64, payload_b64, sig_b64 = parts

    header = json.loads(_b64url_decode(header_b64))
    if header.get("alg") != "HS256":
        raise ValueError(f"unsupported alg: {header.get('alg')!r}; only HS256")

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual = _b64url_decode(sig_b64)
    if not hmac.compare_digest(expected, actual):
        raise ValueError("bad signature")

    payload = json.loads(_b64url_decode(payload_b64))
    now = int(time.time())
    exp = payload.get("exp")
    if exp is not None and now >= int(exp):
        raise ValueError("token expired")
    nbf = payload.get("nbf")
    if nbf is not None and now < int(nbf):
        raise ValueError("token not yet valid")
    return payload  # type: ignore[no-any-return]


def _decode_jwt(token: str, settings: AppSettings) -> dict[str, object]:
    """Validate a JWT and return its claims."""
    try:
        import jwt  # type: ignore[import-not-found]

        return jwt.decode(  # type: ignore[no-any-return]
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer or None,
            options={"require": ["exp"]} if settings.jwt_require_exp else {},
        )
    except ImportError:
        if settings.jwt_algorithm != "HS256":
            raise ValueError(
                f"algorithm {settings.jwt_algorithm} requires PyJWT — "
                "install formulation-workbench[jwt]"
            ) from None
        payload = _decode_jwt_hs256(token, settings.jwt_secret)
        if settings.jwt_issuer and payload.get("iss") != settings.jwt_issuer:
            raise ValueError("issuer mismatch") from None
        return payload


def _extract_scopes(claims: dict[str, object]) -> frozenset[str]:
    raw = claims.get("scope") or claims.get("scopes") or ""
    if isinstance(raw, str):
        return frozenset(s for s in raw.split() if s)
    if isinstance(raw, (list, tuple)):
        return frozenset(str(s) for s in raw)
    return frozenset()


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
def get_principal(
    settings: Annotated[AppSettings, Depends(get_settings)],
    authorization: str | None = Header(default=None),
) -> Principal:
    """Resolve the caller identity based on the current settings."""
    if not settings.api_token and not settings.jwt_secret:
        # Development / test mode — allow everything, log at debug once.
        return Principal(subject="anonymous", scopes=frozenset({"*"}), mode="open")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()

    # JWT takes precedence if configured — it's cryptographically stronger.
    if settings.jwt_secret:
        try:
            claims = _decode_jwt(token, settings)
        except Exception as exc:
            logger.warning("jwt_invalid", extra={"error": repr(exc)})
            if settings.api_token and hmac.compare_digest(token, settings.api_token):
                # Fall through to the static token check.
                pass
            else:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
        else:
            subject = str(claims.get("sub", "unknown"))
            scopes = _extract_scopes(claims)
            # Grant reader by default so a bare authenticated user can browse.
            if not scopes:
                scopes = frozenset({_READ_SCOPE})
            return Principal(subject=subject, scopes=scopes, mode="jwt")

    if settings.api_token and hmac.compare_digest(token, settings.api_token):
        return Principal(
            subject="api-token",
            scopes=frozenset({_READ_SCOPE, _WRITE_SCOPE}),
            mode="static",
        )

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")


def require_scope(scope: str):  # type: ignore[no-untyped-def]
    """Build a dependency that requires ``scope`` on the principal."""

    def _guard(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if not principal.has_scope(scope):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Scope '{scope}' is required (got {sorted(principal.scopes)})",
            )
        return principal

    return _guard


require_reader = require_scope(_READ_SCOPE)
require_writer = require_scope(_WRITE_SCOPE)


__all__ = [
    "Principal",
    "get_principal",
    "require_reader",
    "require_scope",
    "require_writer",
]
