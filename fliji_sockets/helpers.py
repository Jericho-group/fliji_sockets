import datetime
import json
import logging
import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Coroutine, TypeVar, Optional

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


T = TypeVar("T")  # Generic type for return values

def run_async_task(coro: Coroutine[Any, Any, T], loop: Optional[asyncio.AbstractEventLoop] = None) -> T:
    """
    Run an async function in a separate thread and return the result.

    Args:
        coro (Coroutine[Any, Any, T]): The coroutine to run.
        loop (Optional[asyncio.AbstractEventLoop]): The event loop to use. If None, a new loop is created.

    Returns:
        T: The result of the coroutine.

    Raises:
        Exception: Any exception raised inside the coroutine.
    """
    future: Future[T] = Future()

    def thread_func() -> None:
        local_loop = None
        try:
            local_loop = loop or asyncio.new_event_loop()
            asyncio.set_event_loop(local_loop)
            result = local_loop.run_until_complete(coro)
            future.set_result(result)
        except Exception as e:
            future.set_exception(e)
        finally:
            if loop is None and local_loop is not None:  # Only close if we created a new loop
                local_loop.close()

    thread = threading.Thread(target=thread_func, daemon=True)
    thread.start()
    thread.join()  # Wait for the thread to complete

    return future.result()  # Return the coroutine result or raise exception