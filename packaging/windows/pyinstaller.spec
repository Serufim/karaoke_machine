# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller specification for AI Karaoke Studio on Windows.
Bundles Python runtime, PyTorch (CUDA), Demucs, Whisper, FastAPI, and Vue 3 frontend.
Produces an optimized onedir bundle ready for Inno Setup and Steam Depot.
"""

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
ROOT_DIR = Path(SPECPATH).resolve().parent.parent

# Collect required data files
datas = [
    (str(ROOT_DIR / "frontend" / "dist"), "frontend/dist"),
]

# Add optional bundled ffmpeg if present
bundled_bin = ROOT_DIR / "bin"
if bundled_bin.exists():
    datas.append((str(bundled_bin), "bin"))

# Collect submodules and data for heavy libraries
datas += collect_data_files("whisper_timestamped")
datas += collect_data_files("demucs")
datas += collect_data_files("transformers")

hiddenimports = [
    "karaoke.server",
    "karaoke.desktop_app",
    "karaoke.hardware",
    "karaoke.model_manager",
    "karaoke.config",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespans",
    "uvicorn.lifespans.on",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
] + collect_submodules("karaoke")

a = Analysis(
    [str(ROOT_DIR / "src" / "karaoke" / "desktop_app.py")],
    pathex=[str(ROOT_DIR / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
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
    name="AIKaraokeStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Windowed GUI (no terminal popup)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT_DIR / "packaging" / "windows" / "app.ico") if (ROOT_DIR / "packaging" / "windows" / "app.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AIKaraokeStudio",
)
