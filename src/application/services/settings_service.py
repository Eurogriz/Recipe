"""SettingsService — user-override mechanism for component properties.

Production-grade feature: allows users to override defaults for:
- Component densities (g/cm³)
- Glass transition temperatures (Tg, °C)
- Oil absorption (g oil / 100 g pigment)
- Solids fractions
- Cost prices (per kg)

Use cases:
- Lab-measured density for a specific component (overrides default)
- Different supplier grade with different Tg
- Procurement price update
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ComponentOverride:
    """Override for a specific component property."""

    component_name: str  # e.g., "Titanium dioxide (rutile)"
    property_name: str   # e.g., "density", "tg", "oil_absorption"
    value: float
    unit: str
    source: str  # "lab_measurement", "supplier_tds", "user_input"
    notes: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class UserSettings:
    """User-level settings (per installation)."""

    # Component overrides (keyed by (component_name, property_name))
    component_overrides: dict[str, dict[str, ComponentOverride]] = field(default_factory=dict)

    # Calculator settings
    default_temperature_c: float = 23.0
    enable_advisory_warnings: bool = True
    show_calculation_breakdown: bool = True

    # Calibration overrides (per category)
    calibration_overrides: dict[str, dict[str, float]] = field(default_factory=dict)

    # Display preferences
    theme: str = "light"  # "light" | "dark" | "high_contrast"
    language: str = "ru"  # "ru" | "en"


class SettingsService:
    """Manages user settings and component overrides.

    Persists to JSON in %APPDATA% (or $XDG_CONFIG_HOME on Linux/macOS).
    """

    def __init__(self, settings_path: Path | None = None) -> None:
        if settings_path is None:
            settings_path = self._default_settings_path()
        self._settings_path = settings_path
        self._settings = self._load()

    @staticmethod
    def _default_settings_path() -> Path:
        """Default location for settings file."""
        import os
        if os.name == "nt":  # Windows
            base = Path(os.environ.get("APPDATA", str(Path.home())))
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        return base / "FormulationWorkbench" / "settings.json"

    def _load(self) -> UserSettings:
        """Load settings from file or return defaults."""
        if not self._settings_path.exists():
            logger.info("No settings file found, using defaults: %s", self._settings_path)
            return UserSettings()

        try:
            with open(self._settings_path, encoding="utf-8") as f:
                data = json.load(f)
            # Reconstruct ComponentOverride objects
            overrides_raw = data.get("component_overrides", {})
            overrides: dict[str, dict[str, ComponentOverride]] = {}
            for comp_name, props in overrides_raw.items():
                overrides[comp_name] = {}
                for prop_name, ov_data in props.items():
                    overrides[comp_name][prop_name] = ComponentOverride(**ov_data)

            return UserSettings(
                component_overrides=overrides,
                default_temperature_c=data.get("default_temperature_c", 23.0),
                enable_advisory_warnings=data.get("enable_advisory_warnings", True),
                show_calculation_breakdown=data.get("show_calculation_breakdown", True),
                calibration_overrides=data.get("calibration_overrides", {}),
                theme=data.get("theme", "light"),
                language=data.get("language", "ru"),
            )
        except Exception as e:
            logger.exception("Failed to load settings, using defaults")
            return UserSettings()

    def save(self) -> None:
        """Persist settings to file."""
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "component_overrides": {
                    comp_name: {
                        prop_name: asdict(override)
                        for prop_name, override in props.items()
                    }
                    for comp_name, props in self._settings.component_overrides.items()
                },
                "default_temperature_c": self._settings.default_temperature_c,
                "enable_advisory_warnings": self._settings.enable_advisory_warnings,
                "show_calculation_breakdown": self._settings.show_calculation_breakdown,
                "calibration_overrides": self._settings.calibration_overrides,
                "theme": self._settings.theme,
                "language": self._settings.language,
            }
            with open(self._settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("Settings saved to %s", self._settings_path)
        except Exception:
            logger.exception("Failed to save settings")

    # =========================================================================
    # Component overrides
    # =========================================================================

    def set_override(
        self,
        component_name: str,
        property_name: str,
        value: float,
        unit: str,
        source: str = "user_input",
        notes: str = "",
    ) -> None:
        """Set an override for a specific component property."""
        if component_name not in self._settings.component_overrides:
            self._settings.component_overrides[component_name] = {}

        self._settings.component_overrides[component_name][property_name] = ComponentOverride(
            component_name=component_name,
            property_name=property_name,
            value=value,
            unit=unit,
            source=source,
            notes=notes,
        )
        logger.info(
            "Override set: %s.%s = %s %s (source: %s)",
            component_name, property_name, value, unit, source,
        )

    def get_override(self, component_name: str, property_name: str) -> ComponentOverride | None:
        """Get an override for a specific component property."""
        return self._settings.component_overrides.get(component_name, {}).get(property_name)

    def get_value_with_override(
        self,
        component_name: str,
        property_name: str,
        default_value: float,
        unit: str = "",
    ) -> tuple[float, str]:
        """Get a property value, checking overrides first.

        Returns:
            (value, source) where source is 'override' or 'default'.
        """
        override = self.get_override(component_name, property_name)
        if override is not None:
            return override.value, "override"
        return default_value, "default"

    def remove_override(self, component_name: str, property_name: str) -> None:
        """Remove an override."""
        if component_name in self._settings.component_overrides:
            self._settings.component_overrides[component_name].pop(property_name, None)
            if not self._settings.component_overrides[component_name]:
                del self._settings.component_overrides[component_name]

    def list_overrides(self) -> list[ComponentOverride]:
        """List all overrides."""
        result = []
        for comp_props in self._settings.component_overrides.values():
            result.extend(comp_props.values())
        return result

    # =========================================================================
    # Calibration overrides
    # =========================================================================

    def set_calibration_override(
        self,
        category: str,
        property_name: str,
        value: float,
    ) -> None:
        """Override a calibration default for a specific category."""
        if category not in self._settings.calibration_overrides:
            self._settings.calibration_overrides[category] = {}
        self._settings.calibration_overrides[category][property_name] = value

    def get_calibration_override(
        self,
        category: str,
        property_name: str,
        default_value: float,
    ) -> float:
        """Get calibration value with override support."""
        return self._settings.calibration_overrides.get(category, {}).get(
            property_name, default_value,
        )

    # =========================================================================
    # Display settings
    # =========================================================================

    def set_theme(self, theme: str) -> None:
        if theme not in ("light", "dark", "high_contrast"):
            raise ValueError(f"Invalid theme: {theme}")
        self._settings.theme = theme

    def set_language(self, language: str) -> None:
        if language not in ("ru", "en"):
            raise ValueError(f"Invalid language: {language}")
        self._settings.language = language

    @property
    def current_settings(self) -> UserSettings:
        return self._settings
