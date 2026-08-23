"""Internationalization (i18n) setup using gettext.

See ADR-0005 for architecture decision.
"""

from __future__ import annotations

import gettext
import os
from pathlib import Path

# Default locale
DEFAULT_LOCALE = "ru"
SUPPORTED_LOCALES = ("ru", "en")

# Translations directory (relative to package)
LOCALES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "locales"

_translator: gettext.GNUTranslations | gettext.NullTranslations | None = None


def setup_i18n(locale: str = DEFAULT_LOCALE) -> None:
    """Initialize gettext translations.

    Args:
        locale: One of SUPPORTED_LOCALES.
    """
    global _translator

    if locale not in SUPPORTED_LOCALES:
        locale = DEFAULT_LOCALE

    localedir = LOCALES_DIR
    try:
        _translator = gettext.translation(
            domain="messages",
            localedir=str(localedir),
            languages=[locale],
            fallback=True,  # Fall back to default if translation not found
        )
    except FileNotFoundError:
        _translator = gettext.NullTranslations()

    # Install in builtins as `_` / `_n` so Babel-extracted strings work.
    import builtins

    setattr(builtins, "_", _translator.gettext)  # noqa: B010
    setattr(builtins, "_n", _translator.ngettext)  # noqa: B010


def _(message: str) -> str:
    """Translate a message.

    This is the main translation function. Installed in builtins during setup_i18n().
    """
    if _translator is None:
        return message
    return _translator.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Translate with plural forms."""
    if _translator is None:
        return singular if n == 1 else plural
    return _translator.ngettext(singular, plural, n)


def get_current_locale() -> str:
    """Get the currently active locale."""
    return os.environ.get("LANG", DEFAULT_LOCALE).split(".")[0].split("_")[0]
