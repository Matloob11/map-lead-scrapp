from __future__ import annotations

import logging

from .config import LOG_DIR, RUNTIME_LOG_FILE


def configure_logging() -> None:
    if getattr(configure_logging, "_configured", False):
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(RUNTIME_LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    configure_logging._configured = True
