# PyInstaller spec file for Formulation Workbench
# Build: pyinstaller pyinstaller.spec
# Result: dist/FormulationWorkbench.exe (single-file executable)

import sys
from pathlib import Path

block_cipher = None

# Analysis: collect all source files
a = Analysis(
    ['src/presentation/main.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        # Translations
        ('locales', 'locales'),
        # Resources (icons, themes — to be added in Phase 4)
        # ('resources', 'resources'),
    ],
    hiddenimports=[
        'aiosqlite',
        'sqlcipher3',
        'scikit-learn',
        'reportlab',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unused Qt modules to reduce size
        'PySide6.QtNetwork',
        'PySide6.QtMultimedia',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.QtQuick3D',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FormulationWorkbench',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # UPX compression
    console=False,  # GUI app, no console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Icon (to be added in Phase 5)
    # icon='resources/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FormulationWorkbench',
)
