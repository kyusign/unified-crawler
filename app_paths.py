from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "YouTubeCollector"


def _windows_roaming_root() -> Path:
    env = os.getenv("APPDATA")
    if env:
        return Path(env)
    return Path.home() / "AppData" / "Roaming"


def _windows_local_root() -> Path:
    env = os.getenv("LOCALAPPDATA")
    if env:
        return Path(env)
    return Path.home() / "AppData" / "Local"


def _mac_app_support_root() -> Path:
    return Path.home() / "Library" / "Application Support"


def _mac_log_root() -> Path:
    return Path.home() / "Library" / "Logs"


def _posix_data_root() -> Path:
    env = os.getenv("XDG_DATA_HOME")
    if env:
        return Path(env)
    return Path.home() / ".local" / "share"


def _posix_log_root() -> Path:
    env = os.getenv("XDG_STATE_HOME")
    if env:
        return Path(env)
    return Path.home() / ".local" / "state"


def app_support_dir() -> Path:
    if sys.platform == "darwin":
        root = _mac_app_support_root()
    elif sys.platform.startswith("win"):
        root = _windows_roaming_root()
    else:
        root = _posix_data_root()

    target = root / APP_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def log_dir() -> Path:
    if sys.platform == "darwin":
        root = _mac_log_root()
    elif sys.platform.startswith("win"):
        root = _windows_local_root()
    else:
        root = _posix_log_root()

    target = root / APP_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target
