#!/usr/bin/env python3
import os

# set via string, convert to logging.LEVEL later
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# access dsn for sentry error reporting
SENTRY_DSN = os.environ.get("SENTRY_DSN")
SENTRY_SAMPLE_RATE = float(os.environ.get("SENTRY_SAMPLE_RATE", "0.3"))
SENTRY_PROFILING_SAMPLE_RATE = float(os.environ.get("SENTRY_PROFILING_SAMPLE_RATE", "0.0"))

APP_ENV = os.environ.get("APP_ENV", default="prod")

if os.environ.get("DB_ECHO"):
    DB_ECHO = True
else:
    DB_ECHO = False

MONGO_HOST = os.environ.get("MONGO_HOST", "localhost")
MONGO_PORT = int(os.environ.get("MONGO_PORT", "27017"))
MONGO_DB = os.environ.get("MONGO_DB", "fliji_sockets")
MONGO_USER = os.environ.get("MONGO_USER", "fliji_sockets")
MONGO_PASSWORD = os.environ.get("MONGO_PASSWORD", "fliji_sockets")

USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:8000")
USER_SERVICE_API_KEY = os.environ.get("USER_SERVICE_API_KEY")

NATS_HOST = os.environ.get("NATS_HOST", "nats://localhost:4222")
NATS_TOKEN = os.environ.get("NATS_TOKEN", "")

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "5"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
REDIS_CONNECTION_STRING = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

TEST_VIDEO_UUID = os.environ.get("TEST_VIDEO_UUID", "9d2b6a97-d054-4c68-96ed-af0cb82b97db")
