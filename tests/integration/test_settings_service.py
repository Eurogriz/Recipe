"""Tests for SettingsService — user override mechanism."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


def run_settings_tests() -> int:
    """Run all SettingsService tests."""
    print("=" * 70)
    print("SETTINGS SERVICE TESTS — User Override Mechanism")
    print("=" * 70)

    sys.path.insert(0, ".")

    passed = 0
    failed = 0

    # Test 1: Basic persistence
    try:
        from src.application.services.settings_service import (
            SettingsService, UserSettings, ComponentOverride
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"

            service = SettingsService(settings_path)

            # Initially empty
            assert service.current_settings.component_overrides == {}, "Expected empty overrides"

            # Set override
            service.set_override(
                component_name="Titanium dioxide (rutile)",
                property_name="density",
                value=4.30,
                unit="g/cm³",
                source="lab_measurement",
                notes="Measured at 23°C",
            )

            # Retrieve override
            override = service.get_override("Titanium dioxide (rutile)", "density")
            assert override is not None
            assert override.value == 4.30
            assert override.unit == "g/cm³"
            assert override.source == "lab_measurement"

            # Save
            service.save()
            assert settings_path.exists()

            # Reload
            service2 = SettingsService(settings_path)
            override2 = service2.get_override("Titanium dioxide (rutile)", "density")
            assert override2 is not None
            assert override2.value == 4.30

            # Test get_value_with_override
            value, source = service2.get_value_with_override(
                "Titanium dioxide (rutile)", "density", 4.23
            )
            assert value == 4.30  # Override used
            assert source == "override"

            # Non-overridden value
            value, source = service2.get_value_with_override(
                "Unknown component", "density", 1.0
            )
            assert value == 1.0  # Default
            assert source == "default"

            print("\n✓ Basic persistence: PASS")
            passed += 1
    except Exception as e:
        print(f"\n❌ Basic persistence: {type(e).__name__}: {e}")
        failed += 1

    # Test 2: Multiple overrides
    try:
        from src.application.services.settings_service import SettingsService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            service = SettingsService(settings_path)

            # Set multiple overrides for same component
            service.set_override("Acrylic emulsion", "density", 1.05, "g/cm³", "lab_measurement")
            service.set_override("Acrylic emulsion", "tg", 25.0, "°C", "supplier_tds")
            service.set_override("Acrylic emulsion", "price_per_kg", 4.50, "USD", "procurement")

            overrides = service.list_overrides()
            assert len(overrides) == 3
            assert {o.property_name for o in overrides} == {"density", "tg", "price_per_kg"}

            print("\n✓ Multiple overrides: PASS")
            passed += 1
    except Exception as e:
        print(f"\n❌ Multiple overrides: {type(e).__name__}: {e}")
        failed += 1

    # Test 3: Remove override
    try:
        from src.application.services.settings_service import SettingsService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            service = SettingsService(settings_path)

            service.set_override("Test component", "density", 2.0, "g/cm³", "user_input")
            assert service.get_override("Test component", "density") is not None

            service.remove_override("Test component", "density")
            assert service.get_override("Test component", "density") is None

            print("\n✓ Remove override: PASS")
            passed += 1
    except Exception as e:
        print(f"\n❌ Remove override: {type(e).__name__}: {e}")
        failed += 1

    # Test 4: Calibration overrides
    try:
        from src.application.services.settings_service import SettingsService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            service = SettingsService(settings_path)

            # Default value
            value = service.get_calibration_override("Краски", "density_factor", 1.0)
            assert value == 1.0

            # Set override
            service.set_calibration_override("Краски", "density_factor", 0.98)
            value = service.get_calibration_override("Краски", "density_factor", 1.0)
            assert value == 0.98

            print("\n✓ Calibration overrides: PASS")
            passed += 1
    except Exception as e:
        print(f"\n❌ Calibration overrides: {type(e).__name__}: {e}")
        failed += 1

    # Test 5: Theme and language
    try:
        from src.application.services.settings_service import SettingsService

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            service = SettingsService(settings_path)

            # Default
            assert service.current_settings.theme == "light"
            assert service.current_settings.language == "ru"

            # Change
            service.set_theme("dark")
            service.set_language("en")

            assert service.current_settings.theme == "dark"
            assert service.current_settings.language == "en"

            # Invalid values rejected
            try:
                service.set_theme("invalid")
                print("\n❌ Theme validation: FAIL (should have raised)")
                failed += 1
            except ValueError:
                print("\n✓ Theme/language with validation: PASS")
                passed += 1
    except Exception as e:
        print(f"\n❌ Theme/language: {type(e).__name__}: {e}")
        failed += 1

    print()
    print("=" * 70)
    print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_settings_tests())
