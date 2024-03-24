from pymongo.database import Database

from fliji_sockets.api_client import FlijiApiService
from fliji_sockets.store import get_database


def get_db() -> Database:
    # Assuming you have a predefined function to get your db instance
    return get_database()


def get_api_service() -> FlijiApiService:
    # Initialize and return an instance of your ApiService
    return FlijiApiService()
