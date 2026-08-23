"""FastAPI dependency-injection helpers."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from ...infrastructure.config import AppSettings
from ...infrastructure.di import Container


def get_container(request: Request) -> Container:
    """Return the :class:`Container` bound to the running application."""
    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover — should always be set at startup
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application container is not initialised.",
        )
    return container


def get_settings(container: Annotated[Container, Depends(get_container)]) -> AppSettings:
    return container.settings


def require_api_token(
    settings: Annotated[AppSettings, Depends(get_settings)],
    authorization: str | None = Header(default=None),
) -> None:
    """Validate a static bearer token when ``FW_API_TOKEN`` is configured.

    In development (``FW_API_TOKEN`` empty) the dependency is a no-op.
    In production the settings validator enforces that a token is set.
    """
    expected = settings.api_token
    if not expected:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    provided = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token")


__all__ = ["get_container", "get_settings", "require_api_token"]
