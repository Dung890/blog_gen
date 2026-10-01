"""Structured logging setup using structlog.

Call ``configure_logging()`` once at startup. Everywhere else, get a logger with
``get_logger(__name__)`` and log events as ``log.info("event_name", key=value)``.
"""

import logging
import sys

import structlog


def configure_logging() -> None:
    """Configure structlog to emit readable, timestamped, key-value logs."""
    # Windows consoles default to cp1252, which can't encode some Unicode the LLM
    # emits (e.g. non-breaking hyphens). Force UTF-8 and replace anything odd, so
    # a log line can never crash the program.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    structlog.configure(
        processors=[
            # Pulls in any values bound for the current request (e.g. request_id).
            structlog.contextvars.merge_contextvars,
            # Adds the log level (info/warning/error) as a field.
            structlog.processors.add_log_level,
            # Adds an ISO timestamp.
            structlog.processors.TimeStamper(fmt="iso"),
            # Renders it nicely for the console (colored key=value lines).
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None):
    """Return a structlog logger."""
    return structlog.get_logger(name)
