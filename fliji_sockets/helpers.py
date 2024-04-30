import datetime
import json
import logging

import sentry_sdk

from fliji_sockets.settings import (
    LOG_LEVEL,
    SENTRY_DSN,
    APP_ENV,
    SENTRY_SAMPLE_RATE,
    SENTRY_PROFILING_SAMPLE_RATE,
)


def time_now():
    return datetime.datetime.now().replace(microsecond=0)


def configure_logging():
    loglevel = get_log_level()
    logging.basicConfig(format="%(asctime)s %(levelname)s:%(message)s", level=loglevel)


def configure_sentry():
    if SENTRY_DSN and APP_ENV != "local":
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=SENTRY_SAMPLE_RATE,
            profiles_sample_rate=SENTRY_PROFILING_SAMPLE_RATE,
            environment=APP_ENV,
        )


def parse_data(data):
    """
    If data is string - parse it to dict. If it's already dict - return it.
    """
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError as e:
            logging.error(f"Error parsing data: {e}")
            return {}
    elif isinstance(data, dict):
        return data
    else:
        return {}


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


def get_room_name(voice_uuid: str) -> str:
    return f"room_{voice_uuid}"
