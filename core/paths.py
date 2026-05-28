"""
COHOST PATHS — Central path resolution
======================================
Single source of truth for filesystem paths. All modules import COHOST_HOME
from here instead of hardcoding F:/cohost.

Override the install root by setting the COHOST_HOME env var. Otherwise it
resolves to the parent of this file's directory — i.e. the repo/install root.

Also provides load_config() which resolves {COHOST_HOME} placeholders in
config.yaml at load time so YAML stays portable.
"""

import os
from pathlib import Path
from typing import Optional

import yaml


def _resolve_home() -> Path:
    env = os.environ.get("COHOST_HOME")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


COHOST_HOME: Path = _resolve_home()

DATA_DIR     = COHOST_HOME / "data"
MEMORY_DIR   = DATA_DIR / "memory"
LOGS_DIR     = DATA_DIR / "logs"
CACHE_DIR    = DATA_DIR / "cache"
AUDIO_DIR    = DATA_DIR / "audio"
SESSIONS_DIR = DATA_DIR / "sessions"

VOICE_DIR    = COHOST_HOME / "voice"
VOICE_SAMPLE = VOICE_DIR / "samples" / "aria_voice.wav"
VOICE_VENV   = VOICE_DIR / "venv312" / "Scripts" / "python.exe"

CONFIG_PATH  = COHOST_HOME / "core" / "config.yaml"


def _as_posix(p) -> str:
    """Render a path as forward-slash POSIX for YAML interpolation."""
    return str(Path(p)).replace("\\", "/")


def load_config() -> dict:
    """Load config.yaml with {COHOST_HOME} placeholders resolved."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = f.read()
    resolved = raw.replace("{COHOST_HOME}", _as_posix(COHOST_HOME))
    return yaml.safe_load(resolved)


def ensure_dirs() -> None:
    """Create data subdirectories on first use."""
    for d in (DATA_DIR, MEMORY_DIR, LOGS_DIR, CACHE_DIR, AUDIO_DIR, SESSIONS_DIR):
        d.mkdir(parents=True, exist_ok=True)
