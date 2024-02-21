#!/usr/bin/env python3
import os

# set via string, convert to logging.LEVEL later
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# access dsn for sentry error reporting
SENTRY_DSN = os.environ.get("SENTRY_DSN")

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
