import json
import logging

from pymongo import MongoClient
from pymongo.database import Database

from fliji_sockets.models.database import ViewSession, Room, Chat, RoomUser, ChatMessage, \
    TimelineWatchSession, TimelineGroup, TimelineChatMessage
from fliji_sockets.models.socket import TimelineStatusResponse
from fliji_sockets.settings import (
    MONGO_PORT,
    MONGO_HOST,
    MONGO_USER,
    MONGO_PASSWORD,
    MONGO_DB,
)


def ensure_indexes(db: Database):
    db.view_sessions.create_index("sid")
    db.view_sessions.create_index("video_uuid")
    db.view_sessions.create_index("user_uuid")

    db.timeline_watch_sessions.create_index("sid")
    db.timeline_watch_sessions.create_index("video_uuid")
    db.timeline_watch_sessions.create_index("user_uuid")

    db.rooms.create_index("uuid")

    db.temp_room_users.create_index("user_uuid")

    db.room_users.create_index("user_uuid")
    db.room_users.create_index("room_uuid")

    # create TTL index for temporary room users for 10 minutes
    db.temp_room_users.create_index("created_at", expireAfterSeconds=600)


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


async def upsert_room(db: Database, room: Room) -> int:
    result = db.rooms.update_one(
        {"uuid": room.uuid},
        {"$set": room.model_dump(exclude_none=True)},
        upsert=True,
    )
    return result


async def get_room_by_uuid(db: Database, uuid: str) -> Room:
    room = db.rooms.find_one({"uuid": uuid})
    return room


async def get_room_users_by_user_uuid(db: Database, user_uuid: str) -> list[dict]:
    rooms_cursor = db.room_users.find({"user_uuid": user_uuid})
    rooms = []
    for room in rooms_cursor:
        rooms.append(room)
    return rooms


async def get_room_users_by_room_uuid(db: Database, room_uuid: str) -> list[dict]:
    rooms_cursor = db.room_users.find({"room_uuid": room_uuid})
    rooms = []
    for room in rooms_cursor:
        rooms.append(room)
    return rooms


async def get_room_user(db: Database, room_uuid: str, user_uuid: str) -> dict:
    room_user = db.room_users.find_one({"room_uuid": room_uuid, "user_uuid": user_uuid})
    return room_user


async def insert_chat_message(db: Database, chat_message: ChatMessage) -> int:
    result = db.chat_messages.update_one(
        {"internal_chat_id": chat_message.internal_chat_id},
        {"$set": chat_message.model_dump(exclude_none=True)},
        upsert=True,
    )
    return result


async def delete_room_users_by_user_uuid(db: Database, user_uuid: str) -> int:
    result = db.room_users.delete_many({"user_uuid": user_uuid})
    return result.deleted_count


async def insert_chat(db: Database, chat: Chat) -> str:
    chat_id = db.chats.insert_one(chat.model_dump(exclude_none=True)).inserted_id
    return chat_id


async def get_chat_by_id(db: Database, chat_id: int) -> dict:
    chat = db.chats.find_one({"_id": chat_id})
    return chat


async def upsert_room_user(db: Database, room_user: RoomUser) -> int:
    result = db.room_users.update_one(
        {"room_uuid": room_user.room_uuid, "user_uuid": room_user.user_uuid},
        {"$set": room_user.model_dump(exclude_none=True)},
        upsert=True,
    )
    return result


async def delete_temp_room_user_by_user_uuid(db: Database, user_uuid: str) -> int:
    result = db.temp_room_users.delete_many({"user_uuid": user_uuid})
    return result.deleted_count


async def delete_room_users_by_room_uuid(db: Database, room_uuid: str) -> int:
    result = db.room_users.delete_many({"room_uuid": room_uuid})
    return result.deleted_count


async def delete_room_by_uuid(db: Database, room_uuid: str) -> int:
    result = db.rooms.delete_one({"uuid": room_uuid})
    return result.deleted_count


async def delete_chat_by_room_uuid(db: Database, room_uuid: str) -> int:
    result = db.chats.delete_one({"room_uuid": room_uuid})
    return result.deleted_count


async def upsert_temp_room_user(db: Database, room_user: RoomUser) -> int:
    result = db.temp_room_users.update_one(
        {"room_uuid": room_user.room_uuid, "user_uuid": room_user.user_uuid},
        {"$set": room_user.model_dump(exclude_none=True)},
        upsert=True,
    )
    return result


async def get_temp_room_user_by_user_uuid(db: Database, user_uuid: str) -> dict:
    room_user = db.temp_room_users.find_one({"user_uuid": user_uuid})
    return room_user


async def upsert_view_session(db: Database, view_session: ViewSession) -> int:
    view_session_id = db.view_sessions.update_one(
        {"user_uuid": view_session.user_uuid, "video_uuid": view_session.video_uuid},
        {"$set": view_session.model_dump(exclude_none=True)},
        upsert=True,
    )
    return view_session_id


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
    view_session = db.timeline_watch_sessions.find_one({"user_uuid": user_uuid})
    return view_session


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


async def get_view_session_by_socket_id(db: Database, sid: str) -> ViewSession:
    view_session = db.view_sessions.find_one({"sid": sid})
    return view_session


async def get_view_sessions_for_video(db: Database, video_uuid: str) -> list[dict]:
    view_sessions_cursor = db.view_sessions.find({"video_uuid": video_uuid})
    view_sessions = []
    for view_session in view_sessions_cursor:
        view_sessions.append(view_session)
    return view_sessions


async def get_view_sessions_count_for_video(db: Database, video_uuid: str) -> int:
    count = db.view_sessions.count_documents({"video_uuid": video_uuid})
    return count


async def get_view_session_by_user_uuid(db: Database, user_uuid: str) -> dict:
    view_session = db.view_sessions.find_one({"user_uuid": user_uuid})
    return view_session


async def delete_view_session_by_socket_id(db: Database, sid: str) -> int:
    result = db.view_sessions.delete_one({"sid": sid})
    return result.deleted_count


async def delete_view_session_by_user_uuid(db: Database, user_uuid: str) -> int:
    result = db.view_sessions.delete_one({"user_uuid": user_uuid})
    return result.deleted_count


async def delete_sessions_for_user(db: Database, user_uuid: str) -> int:
    result = db.view_sessions.delete_many({"user_uuid": user_uuid})
    return result.deleted_count


def delete_all_sessions(db: Database) -> int:
    result = db.view_sessions.delete_many({})
    return result.deleted_count


async def get_most_watched_videos(db: Database, page: int, page_size: int) -> dict:
    pipeline = [
        {
            "$group": {
                "_id": "$video_uuid",
                "watching_count": {"$sum": 1},
                "video_uuid": {"$first": "$video_uuid"},
            }
        },
        {"$sort": {"watching_count": -1}},
        {"$skip": page * page_size},
        {"$limit": page_size},
    ]
    most_watched_videos = db.view_sessions.aggregate(pipeline)

    videos = {}
    for i, video in enumerate(most_watched_videos, start=1):
        video["rank"] = i + page * page_size
        videos[video["video_uuid"]] = video

    return videos


async def get_most_watched_videos_by_user_uuids(
        db: Database, page: int, page_size: int, user_uuids: list[str]
) -> dict:
    pipeline = [
        {"$match": {"user_uuid": {"$in": user_uuids}}},
        {
            "$group": {
                # also show what users are watching each video
                "_id": "$video_uuid",
                "watching_count": {"$sum": 1},
                "video_uuid": {"$first": "$video_uuid"},
                "users_watching": {"$addToSet": "$user_uuid"},
            }
        },
        {"$sort": {"watching_count": -1}},
        {"$skip": page * page_size},
        {"$limit": page_size},
    ]
    most_watched_videos = db.view_sessions.aggregate(pipeline)

    videos = {}
    for i, video in enumerate(most_watched_videos, start=1):
        video["rank"] = i + page * page_size
        videos[video["video_uuid"]] = video

    return videos
