import logging
import logging.handlers
import sys

import flet as ft

from group_addler.paths import log_dir, migrate_legacy_session
from group_addler.ui import main

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _configure_streams() -> None:
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass


def _configure_logging() -> None:
    handlers: list[logging.Handler] = []
    try:
        log_file = log_dir() / "group-addler.log"
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
        )
    except OSError:
        pass

    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())

    if handlers:
        logging.basicConfig(
            level=logging.INFO,
            format=LOG_FORMAT,
            handlers=handlers,
        )
    else:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)


if __name__ == "__main__":
    _configure_streams()
    _configure_logging()
    try:
        migrate_legacy_session()
    except Exception:
        logging.getLogger(__name__).exception("Could not migrate WhatsApp session")
    ft.run(main)
