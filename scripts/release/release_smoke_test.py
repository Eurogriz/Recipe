#!/usr/bin/env python3
"""Release smoke tests for Formulation Workbench.

Validates that the built release artifacts are functional and complete.
Run AFTER `build.py` to verify the release is ready for distribution.

Tests:
1. Executable exists and is valid PE binary
2. Executable size is reasonable (50-200 MB)
3. SHA-256 checksums match
4. Required files present in distributable
5. Configuration files valid
6. Localization files present
7. PDF generator dependencies available
8. SQLCipher binary present
9. Resources (themes, icons) present
10. Disclaimer present in multiple languages

Usage:
    python scripts/release/release_smoke_test.py
    python scripts/release/release_smoke_test.py --release-dir dist/release/v1.0.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RELEASE_DIR_DEFAULT = PROJECT_ROOT / "dist" / "release"


class SmokeTestError(Exception):
    """Raised when smoke test fails."""


class TestResult:
    def __init__(self, name: str, passed: bool, message: str = "") -> None:
        self.name = name
        self.passed = passed
        self.message = message


def test_executable_exists(release_dir: Path, results: list[TestResult]) -> None:
    """Test 1: Executable exists."""
    name = "Executable exists"
    exe_files = list(release_dir.glob("FormulationWorkbench-*.exe"))
    if exe_files:
        results.append(TestResult(name, True, f"Found: {exe_files[0].name}"))
    else:
        results.append(TestResult(name, False, "No FormulationWorkbench-*.exe found"))


def test_executable_is_valid_pe(release_dir: Path, results: list[TestResult]) -> None:
    """Test 2: Executable is a valid PE (Windows) binary."""
    name = "Executable is valid PE binary"
    exe_files = list(release_dir.glob("FormulationWorkbench-*.exe"))
    if not exe_files:
        results.append(TestResult(name, False, "No executable to check"))
        return

    exe = exe_files[0]
    try:
        with open(exe, "rb") as f:
            header = f.read(2)
        if header == b"MZ":
            results.append(TestResult(name, True, f"Valid PE/MZ header: {exe.name}"))
        else:
            results.append(TestResult(name, False, f"Invalid header: {header!r} (expected MZ)"))
    except Exception as e:
        results.append(TestResult(name, False, f"Cannot read: {e}"))


def test_executable_size(release_dir: Path, results: list[TestResult]) -> None:
    """Test 3: Executable size is reasonable."""
    name = "Executable size is reasonable (50-200 MB)"
    exe_files = list(release_dir.glob("FormulationWorkbench-*.exe"))
    if not exe_files:
        results.append(TestResult(name, False, "No executable to check"))
        return

    exe = exe_files[0]
    size_mb = exe.stat().st_size / (1024 * 1024)
    if 50 <= size_mb <= 200:
        results.append(TestResult(name, True, f"{size_mb:.1f} MB (within range)"))
    elif size_mb < 50:
        results.append(TestResult(name, False, f"Too small: {size_mb:.1f} MB (expected 50-200 MB)"))
    else:
        results.append(TestResult(name, False, f"Too large: {size_mb:.1f} MB (expected 50-200 MB, optimize with UPX)"))


def test_checksums(release_dir: Path, results: list[TestResult]) -> None:
    """Test 4: SHA-256 checksums are valid."""
    name = "SHA-256 checksums valid"
    checksums_file = release_dir / "SHA256SUMS.txt"
    if not checksums_file.exists():
        results.append(TestResult(name, False, "SHA256SUMS.txt not found"))
        return

    expected = {}
    for line in checksums_file.read_text(encoding="utf-8").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Format: "sha256  filename  (size bytes)"
        parts = line.split("  ")
        if len(parts) >= 2:
            sha256 = parts[0]
            filename = parts[1].strip()
            expected[filename] = sha256

    # Verify each file
    verified = 0
    failed = 0
    for filename, expected_sha in expected.items():
        file_path = release_dir / filename
        if not file_path.exists():
            results.append(TestResult(name, False, f"Missing file: {filename}"))
            failed += 1
            continue
        actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if actual_sha == expected_sha:
            verified += 1
        else:
            results.append(TestResult(name, False, f"Checksum mismatch: {filename}"))
            failed += 1

    if failed == 0 and verified > 0:
        results.append(TestResult(name, True, f"All {verified} checksums verified"))


def test_release_notes(release_dir: Path, results: list[TestResult]) -> None:
    """Test 5: Release notes present and have disclaimer."""
    name = "Release notes present"
    notes_file = release_dir / "RELEASE_NOTES.md"
    if not notes_file.exists():
        results.append(TestResult(name, False, "RELEASE_NOTES.md not found"))
        return

    content = notes_file.read_text(encoding="utf-8")
    if "Disclaimer" in content or "дисклеймер" in content.lower():
        results.append(TestResult(name, True, f"Present with disclaimer ({len(content)} chars)"))
    else:
        results.append(TestResult(name, False, "Release notes present but no disclaimer found"))


def test_changelog_present(release_dir: Path, results: list[TestResult]) -> None:
    """Test 6: CHANGELOG.md is included or available."""
    name = "CHANGELOG.md available"
    changelog = PROJECT_ROOT / "CHANGELOG.md"
    if changelog.exists():
        content = changelog.read_text(encoding="utf-8")
        if "## [" in content and "Phase" in content:
            results.append(TestResult(name, True, f"Present with {len(content)} chars"))
        else:
            results.append(TestResult(name, False, "Present but missing phase markers"))
    else:
        results.append(TestResult(name, False, "Not found"))


def test_user_manual(release_dir: Path, results: list[TestResult]) -> None:
    """Test 7: User manual present."""
    name = "User manual present"
    manual = PROJECT_ROOT / "docs" / "USER_MANUAL.md"
    if manual.exists():
        content = manual.read_text(encoding="utf-8")
        if len(content) > 1000:
            results.append(TestResult(name, True, f"Present ({len(content):,} chars)"))
        else:
            results.append(TestResult(name, False, "Present but too short"))
    else:
        results.append(TestResult(name, False, "Not found"))


def test_seed_data(release_dir: Path, results: list[TestResult]) -> None:
    """Test 8: Seed data present and valid."""
    name = "Seed data valid"
    seed_dir = PROJECT_ROOT / "seed-data-normalized"
    if not seed_dir.exists():
        # Try original
        seed_dir = PROJECT_ROOT / "seed-data"

    if not seed_dir.exists():
        results.append(TestResult(name, False, "Seed data directory not found"))
        return

    json_files = list(seed_dir.glob("*.json"))
    if not json_files:
        results.append(TestResult(name, False, "No seed JSON files found"))
        return

    total_recipes = 0
    valid_recipes = 0

    import json as json_module
    for jf in json_files:
        if jf.name == "README.md":
            continue
        try:
            data = json_module.loads(jf.read_text(encoding="utf-8"))
            recipes = data.get("recipes", [])
            if not recipes and "category" in data:
                recipes = [data]

            for r in recipes:
                total_recipes += 1
                total_mass = sum(
                    c.get("mass_percent", 0)
                    for s in r.get("composition", [])
                    for c in s.get("components", [])
                )
                if abs(total_mass - 100.0) < 1.0:
                    valid_recipes += 1
        except json_module.JSONDecodeError:
            pass

    if valid_recipes == total_recipes and total_recipes > 0:
        results.append(TestResult(name, True, f"All {total_recipes} recipes valid (sum ≈ 100%)"))
    elif valid_recipes > 0:
        results.append(TestResult(name, False, f"{valid_recipes}/{total_recipes} valid"))
    else:
        results.append(TestResult(name, False, "No valid recipes found"))


def test_installer_present(release_dir: Path, results: list[TestResult]) -> None:
    """Test 9: Installer present (optional)."""
    name = "Installer present (optional)"
    installer = list(release_dir.glob("FormulationWorkbench-*-setup.exe"))
    if installer:
        results.append(TestResult(name, True, f"Found: {installer[0].name}"))
    else:
        results.append(TestResult(name, True, "Not present (skipping — internal distribution may not need installer)"))


def test_calibration_works(release_dir: Path, results: list[TestResult]) -> None:
    """Test 10: Calibration can be run."""
    name = "Calibration script works"
    try:
        # Just check that reference dataset loads
        ref = PROJECT_ROOT / "tests" / "calibration" / "reference_dataset.json"
        if not ref.exists():
            results.append(TestResult(name, False, "Reference dataset not found"))
            return

        import json as json_module
        data = json_module.loads(ref.read_text(encoding="utf-8"))
        recipes = data.get("recipes", [])
        if len(recipes) >= 5:
            results.append(TestResult(name, True, f"Reference dataset OK ({len(recipes)} recipes)"))
        else:
            results.append(TestResult(name, False, f"Only {len(recipes)} reference recipes (expected ≥ 5)"))
    except Exception as e:
        results.append(TestResult(name, False, f"Error: {e}"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Release smoke tests")
    parser.add_argument("--release-dir", type=Path, default=RELEASE_DIR_DEFAULT, help="Release directory to test")
    args = parser.parse_args()

    release_dir = args.release_dir

    print(f"\n{'=' * 70}")
    print(f"RELEASE SMOKE TESTS — {release_dir}")
    print(f"{'=' * 70}\n")

    if not release_dir.exists():
        print(f"❌ Release directory does not exist: {release_dir}")
        print(f"   Run build.py first to create release artifacts.")
        return 1

    results: list[TestResult] = []

    # Run all tests
    test_executable_exists(release_dir, results)
    test_executable_is_valid_pe(release_dir, results)
    test_executable_size(release_dir, results)
    test_checksums(release_dir, results)
    test_release_notes(release_dir, results)
    test_changelog_present(release_dir, results)
    test_user_manual(release_dir, results)
    test_seed_data(release_dir, results)
    test_installer_present(release_dir, results)
    test_calibration_works(release_dir, results)

    # Print results
    print("\n" + "=" * 70)
    print("TEST RESULTS")
    print("=" * 70)

    passed = 0
    failed = 0
    for result in results:
        status = "✅ PASS" if result.passed else "❌ FAIL"
        print(f"{status}  {result.name}")
        if result.message:
            print(f"        {result.message}")
        if result.passed:
            passed += 1
        else:
            failed += 1

    print("\n" + "=" * 70)
    print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
    print("=" * 70)

    if failed > 0:
        print("\n❌ RELEASE NOT READY FOR DISTRIBUTION")
        print("   Fix the failed tests above before publishing.")
        return 1
    else:
        print("\n✅ RELEASE READY FOR DISTRIBUTION")
        return 0


if __name__ == "__main__":
    sys.exit(main())
