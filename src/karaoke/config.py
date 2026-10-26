"""
Configuration and runtime environment manager for AI Karaoke Studio.
Provides path isolation (zero global environment pollution), portable mode,
and cache redirection for PyTorch, HuggingFace, and Demucs models.
"""

import os
import sys
from pathlib import Path
from typing import Optional


def is_frozen() -> bool:
    """Checks if running as a compiled standalone executable (PyInstaller/PyOxidizer)."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def get_app_dir() -> Path:
    """Returns the base application installation directory."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # In development mode, root is 3 levels up from src/karaoke/config.py
    return Path(__file__).resolve().parent.parent.parent


def get_data_dir() -> Path:
    """
    Returns the user data and cache directory.
    Supports portable mode (if 'portable.txt' exists in app_dir or PORTABLE=1 is set).
    Otherwise uses OS-standard application data directory:
    - Windows: %LOCALAPPDATA%/AIKaraokeStudio
    - macOS: ~/Library/Application Support/AIKaraokeStudio
    - Linux: ~/.local/share/AIKaraokeStudio
    """
    app_dir = get_app_dir()
    if (app_dir / "portable.txt").exists() or os.environ.get("PORTABLE") == "1":
        data_dir = app_dir / "data"
    elif sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        data_dir = Path(local_app_data) / "AIKaraokeStudio"
    elif sys.platform == "darwin":
        data_dir = Path.home() / "Library" / "Application Support" / "AIKaraokeStudio"
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        data_dir = Path(xdg_data) / "AIKaraokeStudio"

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def setup_isolated_environment() -> None:
    """
    Configures environment variables to isolate all AI model caches and binaries.
    Prevents polluting global user profiles or relying on system-wide installations.
    """
    data_dir = get_data_dir()
    cache_dir = data_dir / "cache"

    torch_cache = cache_dir / "torch"
    hf_cache = cache_dir / "huggingface"
    demucs_cache = cache_dir / "demucs"

    torch_cache.mkdir(parents=True, exist_ok=True)
    hf_cache.mkdir(parents=True, exist_ok=True)
    demucs_cache.mkdir(parents=True, exist_ok=True)

    # Set cache dirs only if not explicitly overridden by user
    os.environ.setdefault("TORCH_HOME", str(torch_cache))
    os.environ.setdefault("HF_HOME", str(hf_cache))
    os.environ.setdefault("DEMUCS_CACHE", str(demucs_cache))

    # Prepend bundled binaries (ffmpeg, ffprobe) to PATH if present
    app_dir = get_app_dir()
    bundled_bin = app_dir / "bin"
    if bundled_bin.is_dir():
        current_path = os.environ.get("PATH", "")
        if str(bundled_bin) not in current_path:
            os.environ["PATH"] = str(bundled_bin) + os.pathsep + current_path


# Initialize isolated environment upon module import
setup_isolated_environment()

APP_DIR = get_app_dir()
DATA_DIR = get_data_dir()
CACHE_DIR = DATA_DIR / "cache"
PROJECTS_DIR = DATA_DIR / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
