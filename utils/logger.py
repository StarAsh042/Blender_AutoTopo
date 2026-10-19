"""Logging system for AutoTopo plugin."""

import logging
import sys


# Create plugin logger
logger = logging.getLogger("blender_auto_topo")
logger.setLevel(logging.DEBUG)

# Prevent adding multiple handlers on reload
if not logger.handlers:
    # Console handler (outputs to Blender console)
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setLevel(logging.INFO)
    _formatter = logging.Formatter(
        "[AutoTopo] %(levelname)s: %(message)s"
    )
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)


def set_log_level(level: str) -> None:
    """Set log level: DEBUG, INFO, WARNING, ERROR."""
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
    }
    log_level = level_map.get(level.upper(), logging.INFO)
    logger.setLevel(log_level)
    for handler in logger.handlers:
        handler.setLevel(log_level)
