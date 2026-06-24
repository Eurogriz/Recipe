#!/usr/bin/env python3
"""Production build orchestrator for Formulation Workbench.

Performs full release pipeline:
1. Clean previous build artifacts
2. Verify dependencies (Python version, packages)
3. Run quality checks (lint, type-check, tests)
4. Build executable with PyInstaller
5. Build Windows installer with Inno Setup (if available)
6. Generate checksums (SHA-256)
7. Create release artifacts archive
8. Generate RELEASE_NOTES.md

Usage:
    python scripts/release/build.py [--skip-tests] [--skip-lint]

Environment variables:
    FW_VERSION: Override version (default: from pyproject.toml)
    FW_OUTPUT_DIR: Override output directory (default: dist/release)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PYPROJECT_FILE = PROJECT_ROOT / "pyproject.toml"
OUTPUT_DIR_DEFAULT = PROJECT_ROOT / "dist" / "release"


class BuildError(Exception):
    """Raised when build fails."""


def get_version() -> str:
    """Read version from pyproject.toml."""
    if not PYPROJECT_FILE.exists():
        raise BuildError(f"pyproject.toml not found at {PYPROJECT_FILE}")

    content = PYPROJECT_FILE.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise BuildError("Could not find version in pyproject.toml")
    return match.group(1)


def run_command(cmd: list[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command, log output."""
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd or PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if check and result.returncode != 0:
        raise BuildError(f"Command failed with exit code {result.returncode}: {' '.join(cmd)}")
    return result


def step_1_clean(output_dir: Path) -> None:
    """Step 1: Clean previous build artifacts."""
    print("\n" + "=" * 70)
    print("STEP 1: Cleaning previous build artifacts")
    print("=" * 70)

    paths_to_clean = [
        PROJECT_ROOT / "build",
        PROJECT_ROOT / "dist" / "FormulationWorkbench",
        PROJECT_ROOT / "dist" / "FormulationWorkbench.exe",
        output_dir,
    ]

    for path in paths_to_clean:
        if path.exists():
            print(f"  Removing: {path}")
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def step_2_verify_dependencies() -> None:
    """Step 2: Verify Python version and required packages."""
    print("\n" + "=" * 70)
    print("STEP 2: Verifying dependencies")
    print("=" * 70)

    # Python version
    py_version = sys.version_info
    print(f"  Python version: {py_version.major}.{py_version.minor}.{py_version.micro}")
    if py_version < (3, 11):
        raise BuildError(f"Python 3.11+ required, got {py_version.major}.{py_version.minor}")

    # Required packages
    required_packages = [
        "PySide6",
        "SQLAlchemy",
        "alembic",
        "pydantic",
        "reportlab",
        "openpyxl",
        "sklearn",
        "structlog",
        "cryptography",
    ]

    print(f"  Checking required packages...")
    for pkg in required_packages:
        try:
            __import__(pkg)
            print(f"    ✓ {pkg}")
        except ImportError:
            print(f"    ✗ {pkg} (NOT FOUND)")
            raise BuildError(f"Required package '{pkg}' is not installed. Run: pip install -e '.[dev]'")


def step_3_lint_and_tests(skip: bool) -> None:
    """Step 3: Run lint, type-check, and tests."""
    if skip:
        print("\n⚠️  Skipping lint and tests (--skip-tests)")
        return

    print("\n" + "=" * 70)
    print("STEP 3: Running quality checks (lint, type-check, tests)")
    print("=" * 70)

    print("\n--- Linting with ruff ---")
    run_command(["ruff", "check", "src", "tests"], check=False)
    run_command(["ruff", "format", "--check", "src", "tests"], check=False)

    print("\n--- Type-checking with mypy (strict) ---")
    run_command(["mypy", "src"], check=False)

    print("\n--- Running tests ---")
    run_command(["pytest", "-x", "--tb=short", "-q"], check=False)


def step_4_build_executable(version: str, output_dir: Path) -> Path:
    """Step 4: Build executable with PyInstaller."""
    print("\n" + "=" * 70)
    print("STEP 4: Building executable with PyInstaller")
    print("=" * 70)

    spec_file = PROJECT_ROOT / "pyinstaller.spec"
    if not spec_file.exists():
        raise BuildError(f"pyinstaller.spec not found at {spec_file}")

    # Run PyInstaller
    run_command(
        ["pyinstaller", "--clean", "--noconfirm", str(spec_file)],
    )

    # PyInstaller output
    exe_path = PROJECT_ROOT / "dist" / "FormulationWorkbench" / "FormulationWorkbench.exe"
    if not exe_path.exists():
        # Check alternate location (onefile mode)
        alt_path = PROJECT_ROOT / "dist" / "FormulationWorkbench.exe"
        if alt_path.exists():
            exe_path = alt_path
        else:
            raise BuildError(f"PyInstaller output not found at {exe_path} or {alt_path}")

    print(f"\n✓ Executable built: {exe_path}")

    # Copy to release output dir
    output_dir.mkdir(parents=True, exist_ok=True)
    release_exe = output_dir / f"FormulationWorkbench-{version}.exe"
    shutil.copy2(exe_path, release_exe)
    print(f"✓ Copied to: {release_exe}")

    return release_exe


def step_5_build_installer(version: str, exe_path: Path, output_dir: Path) -> Optional[Path]:
    """Step 5: Build Windows installer with Inno Setup (if available)."""
    print("\n" + "=" * 70)
    print("STEP 5: Building Windows installer")
    print("=" * 70)

    # Check for Inno Setup
    iscc_paths = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]

    iscc = None
    for path in iscc_paths:
        if path.exists():
            iscc = path
            break

    if iscc is None:
        print("⚠️  Inno Setup not found. Skipping installer build.")
        print("   Install Inno Setup 6 from: https://jrsoftware.org/isdl.php")
        return None

    iss_file = PROJECT_ROOT / "installer" / "inno-setup.iss"
    if not iss_file.exists():
        print(f"⚠️  Installer script not found at {iss_file}. Skipping.")
        return None

    # Need to set up dist/ structure for Inno Setup
    # Copy executable and all dependencies
    dist_dir = PROJECT_ROOT / "dist" / "FormulationWorkbench"
    if not dist_dir.exists():
        print(f"⚠️  Distribution directory not found at {dist_dir}. Skipping.")
        return None

    # Build installer
    run_command(
        [str(iscc), str(iss_file)],
    )

    # Inno Setup output
    installer_path = PROJECT_ROOT / "dist" / f"FormulationWorkbench-{version}-setup.exe"
    if not installer_path.exists():
        print(f"⚠️  Installer not found at {installer_path}. Check Inno Setup output.")
        return None

    print(f"\n✓ Installer built: {installer_path}")
    return installer_path


def step_6_generate_checksums(output_dir: Path, files: list[Path]) -> Path:
    """Step 6: Generate SHA-256 checksums for all release files."""
    print("\n" + "=" * 70)
    print("STEP 6: Generating SHA-256 checksums")
    print("=" * 70)

    checksums = []
    for file in files:
        if file.exists():
            sha256 = hashlib.sha256(file.read_bytes()).hexdigest()
            size = file.stat().st_size
            checksums.append(f"{sha256}  {file.name}  ({size:,} bytes)")
            print(f"  {sha256[:16]}...  {file.name}")

    checksums_file = output_dir / "SHA256SUMS.txt"
    checksums_file.write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print(f"\n✓ Checksums written: {checksums_file}")
    return checksums_file


def step_7_generate_release_notes(version: str, output_dir: Path) -> Path:
    """Step 7: Generate RELEASE_NOTES.md."""
    print("\n" + "=" * 70)
    print("STEP 7: Generating RELEASE_NOTES.md")
    print("=" * 70)

    changelog = PROJECT_ROOT / "CHANGELOG.md"
    changelog_content = changelog.read_text(encoding="utf-8") if changelog.exists() else ""

    # Find the [Unreleased] section
    unreleased_match = re.search(
        r"## \[Unreleased\](.*?)(?=## \[|$)",
        changelog_content,
        re.DOTALL,
    )
    unreleased_content = unreleased_match.group(1).strip() if unreleased_match else "See CHANGELOG.md for details."

    release_notes = f"""# Formulation Workbench v{version}

**Release Date:** {datetime.now(timezone.utc).strftime("%Y-%m-%d")}
**Build Type:** Production

---

## ⚠️ Important Disclaimer

This release is provided **for reference purposes only**. All recipes must be:
1. Verified against laboratory data
2. Adapted to specific raw materials
3. Confirmed for target substrate

Calculated values (density, mass solids, VOC, PVC, Tg, etc.) are **predictive estimates** and require experimental confirmation before industrial use. ML-advisory predictions are marked with ⚠ in the UI.

---

## 📋 What's New

{unreleased_content}

---

## 🛠️ System Requirements

| Parameter | Minimum |
|---|---|
| OS | Windows 10 (build 19041+) or Windows 11 |
| RAM | 8 GB |
| Disk | 500 MB |
| Display | 1920×1080 |

---

## 📦 Installation

1. Run `FormulationWorkbench-{version}-setup.exe`
2. Follow installer prompts
3. Launch from Start Menu or Desktop shortcut

---

## 🔐 Security

- Database encrypted with SQLCipher (AES-256)
- Key derived from passphrase via Argon2id
- Role-based access control (Viewer/Technologist/Admin/Auditor)
- Audit log of all changes

---

## 📞 Support

- Documentation: F1 in application
- Architecture docs: docs/00-discovery/
- Issues: contact your system administrator

---

**© 2026 Formulation Workbench Team. All rights reserved.**
"""

    notes_file = output_dir / "RELEASE_NOTES.md"
    notes_file.write_text(release_notes, encoding="utf-8")
    print(f"✓ Release notes written: {notes_file}")
    return notes_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Formulation Workbench")
    parser.add_argument("--skip-tests", action="store_true", help="Skip lint and tests")
    parser.add_argument("--skip-lint", action="store_true", help="Skip lint only")
    parser.add_argument("--skip-installer", action="store_true", help="Skip installer build")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR_DEFAULT, help="Output directory")
    parser.add_argument("--version", type=str, help="Override version")

    args = parser.parse_args()

    output_dir = args.output_dir
    version = args.version or get_version()

    print(f"\n{'=' * 70}")
    print(f"FORMULATION WORKBENCH v{version} — PRODUCTION BUILD")
    print(f"{'=' * 70}")
    print(f"Output directory: {output_dir}")
    print(f"Skip tests: {args.skip_tests}")
    print(f"Skip installer: {args.skip_installer}")

    try:
        # Step 1: Clean
        step_1_clean(output_dir)

        # Step 2: Verify dependencies
        step_2_verify_dependencies()

        # Step 3: Quality checks
        step_3_lint_and_tests(args.skip_tests or args.skip_lint)

        # Step 4: Build executable
        exe_path = step_4_build_executable(version, output_dir)

        # Step 5: Build installer
        installer_path = None
        if not args.skip_installer:
            installer_path = step_5_build_installer(version, exe_path, output_dir)

        # Step 6: Checksums
        files_to_checksum = [exe_path]
        if installer_path:
            files_to_checksum.append(installer_path)
        step_6_generate_checksums(output_dir, files_to_checksum)

        # Step 7: Release notes
        step_7_generate_release_notes(version, output_dir)

        # Summary
        print("\n" + "=" * 70)
        print("✅ BUILD COMPLETE")
        print("=" * 70)
        print(f"Version: {version}")
        print(f"Output directory: {output_dir}")
        print(f"Files:")
        for file in sorted(output_dir.iterdir()):
            size_mb = file.stat().st_size / (1024 * 1024)
            print(f"  {file.name}: {size_mb:.2f} MB")
        return 0

    except BuildError as e:
        print(f"\n❌ BUILD FAILED: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n\n⚠️  Build interrupted by user", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
