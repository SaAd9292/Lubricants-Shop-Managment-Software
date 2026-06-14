# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build spec for Penguix.
# Build with:  pyinstaller --noconfirm --clean penguix.spec
# Produces a single-file, windowed Windows executable: dist/Penguix.exe
#
# IMPORTANT: schema.sql is read at runtime, so it must be bundled as data.
# (tuple form is OS-independent — no ';' vs ':' issues.)

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('lubripos/database/schema.sql', 'lubripos/database'),
        ('assets/penguix.ico', 'assets'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # trim things we never use to shrink the exe
        'tkinter', 'matplotlib', 'numpy', 'pandas', 'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets', 'PySide6.QtQuick', 'PySide6.QtQml',
        'PySide6.Qt3DCore', 'PySide6.QtMultimedia', 'PySide6.QtNetwork',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Penguix',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/penguix.ico',
)
