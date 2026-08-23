"""Formulation Workbench — verified paint/coatings recipe database.

Top-level package. Exposes only ``__version__``; consumers must import
concrete symbols from ``formulation_workbench.domain``,
``formulation_workbench.application``, ``formulation_workbench.infrastructure``,
or ``formulation_workbench.presentation``.
"""

from __future__ import annotations

__version__ = "1.19.0"
__all__ = ["__version__"]
