"""Single-line logging to stderr, safe for GitHub Actions logs."""
import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
