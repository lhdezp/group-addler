from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "GroupAddler"


def app_data_dir() -> Path:
    """Return the per-user application directory, creating it if needed."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_session_path() -> str:
    """Location of the WhatsApp credentials database."""
    return str(app_data_dir() / "whatsapp_session")


def log_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def exports_dir() -> Path:
    path = app_data_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_session_path() -> Path:
    """Session location used by versions that stored data next to the code."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "whatsapp_session"


def migrate_legacy_session() -> None:
    """Move a session stored next to the code/exe into the app data directory."""
    target = Path(default_session_path())
    if target.exists():
        return

    legacy = legacy_session_path()
    if not legacy.exists():
        return

    try:
        shutil.move(str(legacy), str(target))
        for suffix in ("-wal", "-shm"):
            companion = Path(f"{legacy}{suffix}")
            if companion.exists():
                shutil.move(str(companion), f"{target}{suffix}")
    except OSError:
        logger.exception("Could not migrate WhatsApp session to %s", target)
        return

    logger.info("Moved WhatsApp session from %s to %s", legacy, target)
