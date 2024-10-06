import json
import logging

from pymongo import MongoClient
from pymongo.database import Database

from fliji_sockets.models.database import TimelineWatchSession, TimelineGroup, TimelineChatMessage
from fliji_sockets.models.socket import TimelineStatusResponse
from fliji_sockets.settings import (
    MONGO_PORT,
    MONGO_HOST,
    MONGO_USER,
    MONGO_PASSWORD,
    MONGO_DB,
)


def ensure_indexes(db: Database):
    db.timeline_watch_sessions.create_index("sid")
    db.timeline_watch_sessions.create_index("video_uuid")
    db.timeline_watch_sessions.create_index("user_uuid")


def serialize_doc(doc):
    """Weird hack to serialize the ObjectId to a string.
    This is necessary because socketio doesn't properly serialize"""
    return json.loads(json.dumps(doc, default=str))


def get_database():
    # with password
    connection_url = (
        f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}"
    )
    client = MongoClient(connection_url)
    db = client[
        MONGO_DB
    ]  # Replace 'your_database_name' with your desired database name

    # set logging level to INFO so it's not too verbose
    logging.getLogger('pymongo').setLevel(logging.INFO)

    ensure_indexes(db)
    return db

async def upsert_timeline_watch_session(db: Database, watch_session: TimelineWatchSession) -> int:
    watch_session_id = db.timeline_watch_sessions.update_one(
        {"user_uuid": watch_session.user_uuid, "video_uuid": watch_session.video_uuid},
        {"$set": watch_session.model_dump()},
        upsert=True,
    )
    return watch_session_id


async def delete_timeline_watch_session_by_user_uuid(db: Database, user_uuid: str) -> int:
    result = db.timeline_watch_sessions.delete_one({"user_uuid": user_uuid})
    return result.deleted_count


async def get_timeline_watch_session_by_user_uuid(db: Database, user_uuid: str) -> dict:
    watch_session = db.timeline_watch_sessions.find_one({"user_uuid": user_uuid})
    return watch_session


async def get_timeline_group_by_uuid(db: Database, group_uuid: str):
    group = db.timeline_groups.find_one({"group_uuid": group_uuid})
    return group


async def get_timeline_group_users(db: Database, group_uuid: str):
    # order by last_update_time
    users = db.timeline_watch_sessions.find({"group_uuid": group_uuid}).sort(
        "last_update_time"
    )
    return users


async def upsert_timeline_group(db: Database, group: TimelineGroup) -> int:
    result = db.timeline_groups.update_one(
        {"group_uuid": group.group_uuid},
        {"$set": group.model_dump(exclude_none=True)},
        upsert=True,
    )
    return result


async def delete_timeline_group_by_uuid(db: Database, group_uuid: str) -> int:
    result = db.timeline_groups.delete_one({"group_uuid": group_uuid})
    return result.deleted_count


async def get_timeline_status(db: Database, video_uuid: str) -> TimelineStatusResponse:
    groups = db.timeline_groups.find({"video_uuid": video_uuid})
    users = db.timeline_watch_sessions.find({"video_uuid": video_uuid}).sort("last_update_time")

    groups_dict = {}
    for group in groups:
        group["users"] = []
        groups_dict[group["group_uuid"]] = group

    # remove users that are already in groups
    users_data = []
    for user in users:
        if user.get("group_uuid") is not None and user.get("group_uuid") in groups_dict.keys():
            # if user is the host, add to the beginning of the list
            is_host = groups_dict[user["group_uuid"]].get("host_uuid") == user.get("user_uuid")
            if is_host:
                groups_dict[user["group_uuid"]]["users"].insert(0, user)
            else:
                groups_dict[user["group_uuid"]]["users"].append(user)
        else:
            users_data.append(user)

    # transform groups_dict to list
    groups_data = []
    for group in groups_dict.values():
        groups_data.append(group)

    response = TimelineStatusResponse(
        video_uuid=video_uuid,
        groups=groups_data,
        users=users_data,
    )
    return response


def delete_all_timeline_watch_sessions(db: Database) -> int:
    result = db.timeline_watch_sessions.delete_many({})
    return result.deleted_count


def delete_all_timeline_groups(db: Database) -> int:
    result = db.timeline_groups.delete_many({})
    return result.deleted_count


def delete_all_timeline_chat_messages(db: Database) -> int:
    result = db.timeline_chat_messages.delete_many({})
    return result.deleted_count


async def insert_timeline_chat_message(db: Database, chat_message: TimelineChatMessage) -> int:
    result = db.timeline_chat_messages.insert_one(chat_message.model_dump(exclude_none=True))
    return result


async def get_timeline_chat_messages_by_video_uuid(db: Database, video_uuid: str) -> list[dict]:
    messages = db.timeline_chat_messages.find({"video_uuid": video_uuid})
    return messages