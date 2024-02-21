import datetime
import logging

from fliji_sockets.settings import LOG_LEVEL


def time_now():
    return datetime.datetime.now().replace(microsecond=0)


def configure_logging():
    loglevel = get_log_level()
    logging.basicConfig(format="%(asctime)s %(levelname)s:%(message)s", level=loglevel)


def get_log_level() -> int:
    """
    Allows to set log level from environment variable as a string.
    """
    switch = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    return switch.get(LOG_LEVEL)
