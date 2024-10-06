import nats
from nats.aio.client import Client
from pymongo.database import Database

from tests.test_api_client import FlijiApiService
from fliji_sockets.settings import NATS_TOKEN, NATS_HOST
from fliji_sockets.store import get_database


async def get_db() -> Database:
    # Assuming you have a predefined function to get your db instance
    return get_database()


async def get_api_service() -> FlijiApiService:
    # Initialize and return an instance of your ApiService
    return FlijiApiService()


async def get_nats_client() -> Client:
    options = {
        "token": NATS_TOKEN
    }

    nc = await nats.connect(f"{NATS_HOST}", **options)
    return nc
