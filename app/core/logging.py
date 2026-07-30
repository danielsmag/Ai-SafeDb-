"""Central application logger and logging configuration."""

import logging
from typing import Final

_LOG_FORMAT: Final[str] = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOGGER_NAME: Final[str] = "aisafedb"

logger: logging.Logger = logging.getLogger(LOGGER_NAME)


def configure_logging(level: str | int) -> None:
    """Configure root logging for the application."""
    logging.basicConfig(level=level, format=_LOG_FORMAT)
