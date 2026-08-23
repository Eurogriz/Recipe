"""FastAPI-based REST facade for the formulation workbench."""

from .app import create_app

__all__ = ["create_app"]
