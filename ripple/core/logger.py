"""统一日志：rich handler，默认 INFO。"""
from __future__ import annotations

import logging
import os

from rich.logging import RichHandler


_configured = False


def get_logger(name: str = "ripple") -> logging.Logger:
    global _configured
    if not _configured:
        level = os.environ.get("RIPPLE_LOG", "INFO").upper()
        logging.basicConfig(
            level=level,
            format="%(message)s",
            datefmt="%H:%M:%S",
            handlers=[RichHandler(rich_tracebacks=True, show_path=False, markup=True)],
        )
        _configured = True
    return logging.getLogger(name)
