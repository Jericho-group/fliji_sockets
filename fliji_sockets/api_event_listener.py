import asyncio
import logging

import nats

from fliji_sockets.helpers import time_now, get_room_name, configure_logging
from fliji_sockets.models.api_service_events import RoomCreatedEvent, RoomUpdatedEvent, \
    UserJoinedEvent, RoomDeletedEvent
from fliji_sockets.models.database import Room, Chat, RoomUser
from fliji_sockets.models.enums import RoomUserRole, RoomMode
from fliji_sockets.room_service import RoomService
from fliji_sockets.settings import NATS_HOST, NATS_TOKEN
from fliji_sockets.socketio_application import SocketioApplication
from fliji_sockets.store import upsert_room, get_database, insert_chat, \
    upsert_temp_room_user, get_room_by_uuid, delete_chat_by_room_uuid, \
    delete_room_by_uuid, delete_room_users_by_room_uuid


async def async_main():
    options = {
        "token": NATS_TOKEN
    }

    db = get_database()
    sio_app = SocketioApplication.get_remote_emitter()

    nc = await nats.connect(f"{NATS_HOST}", **options)

    async def room_created(msg):
        subject = msg.subject
        reply = msg.reply
        data = msg.data.decode()

        logging.debug("Received a message on '{subject} {reply}': {data}".format(
            subject=subject, reply=reply, data=data))

        event_data = RoomCreatedEvent.parse_raw(data)
        chat = Chat()

        now = time_now()
        room = Room.model_validate(event_data.model_dump() | {
            "updated_at": now,
            "created_at": now,
            "internal_chat_id": str(chat.id)
        })

        await upsert_room(db, room)
        await insert_chat(db, chat)

    async def room_updated(msg):
        subject = msg.subject
        reply = msg.reply
        data = msg.data.decode()

        logging.debug("Received a message on '{subject} {reply}': {data}".format(
            subject=subject, reply=reply, data=data))

        event_data = RoomUpdatedEvent.parse_raw(data)

        now = time_now()
        room = Room.model_validate(event_data.model_dump() | {
            "updated_at": now,
        })

        await upsert_room(db, room)

    async def room_deleted(msg):
        subject = msg.subject
        reply = msg.reply
        data = msg.data.decode()

        logging.debug("Received a message on '{subject} {reply}': {data}".format(
            subject=subject, reply=reply, data=data))

        event_data = RoomDeletedEvent.parse_raw(data)
        room = await get_room_by_uuid(db, event_data.room_uuid)

        if room:
            await sio_app.emit("room_deleted", {
                "room_uuid": room.uuid,
            }, room=get_room_name(room.uuid))
            await delete_chat_by_room_uuid(db, room.uuid)
            await delete_room_by_uuid(db, room.uuid)
            await delete_room_users_by_room_uuid(db, room.uuid)

    async def user_joined_room(msg):
        subject = msg.subject
        reply = msg.reply
        data = msg.data.decode()

        logging.debug("Received a message on '{subject} {reply}': {data}".format(
            subject=subject, reply=reply, data=data))

        event_data = UserJoinedEvent.parse_raw(data)

        now = time_now()

        user_role = RoomUserRole(event_data.role)
        room_mode = RoomMode(event_data.room_mode)

        # add the admin user to the room
        room_user = RoomUser(
            room_uuid=event_data.room_uuid,
            user_uuid=event_data.user_uuid,
            username=event_data.username,
            first_name=event_data.first_name,
            last_name=event_data.last_name,
            avatar_url=event_data.avatar_url,

            mic=False,
            role=user_role,
            right_to_speak=RoomService.get_right_to_speak(user_role, room_mode),
            mic_ban=False,

            created_at=now,
            updated_at=now
        )

        await upsert_temp_room_user(db, room_user)

    await nc.subscribe("room.created", cb=room_created)
    await nc.subscribe("room.updated", cb=room_updated)
    await nc.subscribe("room.deleted", cb=room_deleted)
    await nc.subscribe("room.user_joined", cb=user_joined_room)

    logging.info(f"Listening for events...")

    # Keep the connection open to listen for messages
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        logging.error("Cancelled!")
    finally:
        await nc.drain()


def main():
    configure_logging()
    asyncio.run(async_main())
