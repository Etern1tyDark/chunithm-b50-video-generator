"""Filesystem and runtime discovery for b50-gen.

The bundled runtime, assets, metadata, and ffmpeg all live under b50-gen;
the generator has no path dependency on mai-gen.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
USER = ROOT / "user"
USER_DATA = USER / "data.json"
ASSETS = DATA / "Chunithm"
FONTS = DATA / "fonts"
TOOLS = ROOT / "tools"
METADATA = DATA / "chuni_fusion_data.json"
DEFAULT_JACKET = DATA / "default_jacket.png"
FFMPEG = TOOLS / "ffmpeg.exe"

# The portable Windows runtime provides Pillow, requests, and pytubefix.
RUNTIME = ROOT / "runtime"


def enable_runtime_packages() -> None:
    """Make packages from b50-gen's optional bundled runtime importable."""
    packages = RUNTIME / "Lib" / "site-packages"
    if packages.exists() and str(packages) not in sys.path:
        sys.path.insert(0, str(packages))


def python_executable() -> Path | None:
    executable = RUNTIME / "python.exe"
    return executable if executable.exists() else None


def ffmpeg_path() -> str | None:
    """Prefer b50-gen's bundled encoder and fall back to PATH."""
    if FFMPEG.exists():
        return str(FFMPEG)
    return shutil.which("ffmpeg")
