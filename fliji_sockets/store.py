import json
from typing import List

from fliji_sockets.data_models import ViewSession
from fliji_sockets.settings import (
    MONGO_PORT,
    MONGO_HOST,
    MONGO_USER,
    MONGO_PASSWORD,
    MONGO_DB,
)
from pymongo import MongoClient
from pymongo.database import Database
from bson.objectid import ObjectId


def ensure_indexes(db: Database):
    db.view_sessions.create_index("sid")
    db.view_sessions.create_index("video_uuid")


def serialize_doc(doc):
    """Weird hack to serialize the ObjectId to a string.
    This is necessary because socketio doesn't properly serialize"""
    return json.loads(json.dumps(doc, default=str))


def get_db():
    # with password
    connection_url = (
        f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}"
    )
    client = MongoClient(connection_url)
    db = client[
        MONGO_DB
    ]  # Replace 'your_database_name' with your desired database name

    ensure_indexes(db)
    return db


async def upsert_view_session(db: Database, view_session: ViewSession) -> int:
    view_session_id = db.view_sessions.update_one(
        {"sid": view_session.sid},
        {"$set": view_session.model_dump()},
        upsert=True,
    )
    return view_session_id


async def get_session_by_socket_id(db: Database, sid: str) -> ViewSession:
    view_session = db.view_sessions.find_one({"sid": sid})
    return view_session


async def get_view_sessions_for_video(db: Database, video_uuid: str) -> List[dict]:
    view_sessions_cursor = db.view_sessions.find({"video_uuid": video_uuid})
    view_sessions = []
    for view_session in view_sessions_cursor:
        view_sessions.append(view_session)
    return view_sessions


async def get_view_sessions_count_for_video(db: Database, video_uuid: str) -> int:
    count = db.view_sessions.count_documents({"video_uuid": video_uuid})
    return count


async def get_view_session_by_user_uuid(db: Database, user_uuid: str) -> ViewSession:
    view_session = db.view_sessions.find_one({"user_uuid": user_uuid})
    return view_session


async def delete_sessions_for_user(db: Database, user_uuid: str) -> int:
    result = db.view_sessions.delete_many({"user_uuid": user_uuid})
    return result.deleted_count


def delete_all_sessions(db: Database) -> int:
    result = db.view_sessions.delete_many({})
    return result.deleted_count
