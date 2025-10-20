"""Helpers for consistent logging configuration across the CLI."""

from __future__ import annotations

import logging

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def configure_logging(verbosity: int) -> None:
    """Configure the root logger based on the requested verbosity.

    The CLI treats no flag as WARNING, "-v" as INFO, and "-vv" (or more)
    as DEBUG. Repeated invocations only adjust levels to avoid duplicating
    handlers when the CLI is imported in tests.
    """

    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        for handler in root.handlers:
            handler.setLevel(level)
    else:
        logging.basicConfig(level=level, format=_LOG_FORMAT, datefmt=_DATE_FORMAT)

    logging.captureWarnings(True)
