import logging

from uaw.config import LogLevel

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(level: LogLevel) -> None:
    """Configure root logging once for the whole process."""
    logging.basicConfig(level=level, format=LOG_FORMAT, force=True)
