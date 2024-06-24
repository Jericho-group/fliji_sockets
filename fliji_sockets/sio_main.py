import logging
import random
import string
from datetime import datetime

from pydantic import ValidationError
from pymongo.database import Database

from nats.aio.client import Client

from fliji_sockets.api_client import FlijiApiService, ApiException
from fliji_sockets.dependencies import get_db, get_api_service, get_nats_client
from fliji_sockets.event_publisher import publish_user_watched_video, \
    publish_user_started_watching_video, publish_user_joined_room, \
    publish_user_left_all_rooms, publish_chat_message, publish_user_disconnected, \
    publish_user_online, publish_user_offline, publish_room_ownership_changed
from fliji_sockets.helpers import get_room_name, configure_logging, configure_sentry
from fliji_sockets.models.base import UserSession
from fliji_sockets.models.database import ViewSession, RoomUser, Room, ChatMessage
from fliji_sockets.models.enums import RightToSpeakState, RoomUserRole
from fliji_sockets.models.socket import (
    OnConnectRequest,
    UpdateViewSessionRequest,
    GetViewSessionsForVideoRequest,
    JoinRoomRequest,
    RoomActionRequest,
    ToggleVoiceUserMicRequest,
    TransferRoomOwnershipRequest,
    ConfirmRoomOwnershipTransferRequest,
    SendChatMessageRequest,
    HandleRightToSpeakRequest,
    EndVideoWatchSessionRequest,
    VideoTimecodeRequest,
    CurrentDurationRequest, ChangeRoleRequest, KickUserRequest,
)
from fliji_sockets.models.user_service_api import (
    AuthUserResponse,
)
from fliji_sockets.settings import APP_ENV
from fliji_sockets.socketio_application import SocketioApplication, Depends
from fliji_sockets.store import (
    delete_view_session_by_socket_id,
    delete_view_session_by_user_uuid,
    upsert_view_session,
    get_view_sessions_for_video,
    get_database,
    delete_all_sessions,
    get_view_session_by_user_uuid, get_temp_room_user_by_user_uuid, upsert_room_user,
    delete_temp_room_user_by_user_uuid, get_room_users_by_user_uuid, delete_room_users_by_user_uuid,
    get_room_users_by_room_uuid, get_room_user, get_room_by_uuid, upsert_room,
    insert_chat_message,
)

app = SocketioApplication()

configure_logging()
configure_sentry()


@app.event("startup")
async def startup(
        sid,
        data: OnConnectRequest,
        api_service: FlijiApiService = Depends(get_api_service),
        nc: Client = Depends(get_nats_client),
):
    """
    This event should be called when a socket connects.
    It validates the user's auth token and stores the user's UUID in the session.

    Request:
    :py:class:`fliji_sockets.models.socket.OnConnectRequest`

    Raises:
        FatalError: If the user's auth token is invalid or the user's UUID cannot be found.
    """
    logging.debug(f"validated request {data} for sid {sid}")

    try:
        response = await api_service.authenticate_user(data.auth_token)
        response_data = AuthUserResponse.model_validate(response)
    except ApiException as e:
        await app.send_fatal_error_message(sid, f"Could not authenticate user: {e}")
        return
    except ValidationError as e:
        await app.send_fatal_error_message(
            sid, f"Could not authenticate user: {e.errors()} {e.json()}"
        )
        return

    if not response:
        await app.send_fatal_error_message(sid, "Could not authenticate user.")
        return

    logging.debug(f"user_uuid found for sid {sid}")
    if not response_data.uuid:
        await app.send_fatal_error_message(sid, "Authentication service failed.")
        return

    logging.debug(f"authenticated user {response_data.uuid} for sid {sid}")

    await publish_user_online(nc, response_data.uuid)

    # Also store user_uuid in the user's session for later use
    try:
        await app.save_session(
            sid,
            UserSession(
                user_uuid=response_data.uuid,
                username=response_data.username,
                avatar=response_data.image,
                first_name=response_data.first_name,
                last_name=response_data.last_name,
                bio=response_data.bio,
            ),
        )
    except Exception as e:
        logging.error(f"Could not save session: {e}")
        await app.send_fatal_error_message(sid, f"Could not save session: {e}")
        return


@app.event("go_online")
async def go_online(
        sid,
        nc: Client = Depends(get_nats_client),
):
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await publish_user_online(nc, session.user_uuid)


@app.event("go_offline")
async def go_offline(
        sid,
        nc: Client = Depends(get_nats_client),
):
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await publish_user_offline(nc, session.user_uuid)


@app.event("disconnect")
async def disconnect(
        sid,
        db: Database = Depends(get_db),
        nc=Depends(get_nats_client),
):
    """
    Not meant to be called manually.

    This event is automatically called when a socket disconnects.
    Handles both manual disconnection and automatic disconnection due to network issues.

    Deletes the user's video view session and online user status.
    Also saves the video view session to the db if it was not saved before.
    """
    user_session = await app.get_session(sid)

    # If the session data was corrupted somehow, delete whatever we can
    if not user_session:
        await delete_view_session_by_socket_id(db, sid)
        return

    user_uuid = user_session.user_uuid
    room_users = await get_room_users_by_user_uuid(db, user_uuid)
    for room_user in room_users:
        await app.emit(
            "leave_user",
            {"uuid": user_uuid},
            room=get_room_name(room_user.get("room_uuid")),
            skip_sid=sid,
        )

    # save the dangling view session
    view_session = await get_view_session_by_user_uuid(db, user_uuid)

    if (
            view_session
            and (view_session.get("video_uuid") is not None)
            and (view_session.get("current_watch_time") is not None)
    ):
        video_uuid = view_session.get("video_uuid")
        current_watch_time = view_session.get("current_watch_time")
        await publish_user_watched_video(
            nc, user_uuid, video_uuid, current_watch_time
        )

    await delete_room_users_by_user_uuid(db, user_uuid)
    await delete_view_session_by_user_uuid(db, user_session.user_uuid)

    await publish_user_disconnected(nc, user_uuid)


@app.event("end_video_watch_session")
async def end_video_watch_session(
        sid,
        data: EndVideoWatchSessionRequest,
        db: Database = Depends(get_db),
        nc: Client = Depends(get_nats_client),
):
    """
    Handles the end of a video watch session.

    Request:
    :py:class:`fliji_sockets.models.socket.EndVideoWatchSessionRequest`
    """
    # delete the view session
    await delete_view_session_by_socket_id(db, sid)

    # save the view via api
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await publish_user_watched_video(
        nc, session.user_uuid, data.video_uuid, watch_time=data.time
    )


@app.event("update_watch_time")
async def update_watch_time(
        sid, data: UpdateViewSessionRequest, db: Database = Depends(get_db),
        nc: Client = Depends(get_nats_client),
):
    """
    Handles the updating of the current watch time for a video.

    Request:
    :py:class:`fliji_sockets.models.socket.UpdateViewSessionRequest`
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    session_already_exists = await get_view_session_by_user_uuid(db, session.user_uuid)
    if not session_already_exists:
        await publish_user_started_watching_video(nc, session.user_uuid, data.video_uuid)

    # delete the old view session
    await delete_view_session_by_user_uuid(db, session.user_uuid)

    view_session = ViewSession(
        sid=sid,
        last_update_time=datetime.now(),
        current_watch_time=data.current_watch_time,
        video_uuid=data.video_uuid,
        user_uuid=session.user_uuid,
        avatar=session.avatar,
        username=session.username,
        first_name=session.first_name,
        last_name=session.last_name,
        bio=session.bio,
    )
    await upsert_view_session(db, view_session)


@app.event("get_sessions_for_video")
async def get_sessions_for_video(
        sid, data: GetViewSessionsForVideoRequest, db: Database = Depends(get_db)
):
    """
    Handles the request for the view sessions for a video.

    Request:
    :py:class:`fliji_sockets.models.socket.GetViewSessionsForVideoRequest`

    Response (emitted to the client):
    `current_video_view_sessions` event

    .. code-block:: json

        [
          {
            "user_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
            "current_watch_time": 15,
            "last_update_time": "2021-08-01T12:00:00",
            "avatar": "https://example.com/avatar.png",
            "username": "username",
            "first_name": "first_name",
            "last_name": "last_name"
          }
        ]

    Where:

    current_watch_time is in seconds

    last_update_time is an ISO formatted string
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    view_sessions = await get_view_sessions_for_video(db, data.video_uuid)

    view_sessions_response = []
    for view_session in view_sessions:
        last_update_time = view_session.get("last_update_time")
        view_sessions_response.append(
            {
                "user_uuid": view_session.get("user_uuid"),
                "avatar": view_session.get("avatar"),
                "username": view_session.get("username"),
                "first_name": view_session.get("first_name"),
                "last_name": view_session.get("last_name"),
                "current_watch_time": view_session.get("current_watch_time"),
                "last_update_time": (
                    last_update_time.isoformat() if last_update_time else None
                ),
            }
        )

    await app.emit("current_video_view_sessions", view_sessions_response, room=sid)


@app.event("join_room")
async def join_room(
        sid, data: JoinRoomRequest, db: Database = Depends(get_db),
        nc: Client = Depends(get_nats_client)
):
    """
    Handles the joining of a voice room.

    Request:
    :py:class:`fliji_sockets.models.socket.JoinRoomRequest`

    Response (emitted to everybody in the room except for the sender):
    `new_user` event

    Data:

    .. code-block:: json

            {
                "uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
                "status": "online",
                "mic": true,
                "role": "owner"
            }

    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    room_user_data = await get_temp_room_user_by_user_uuid(db, user_uuid)
    try:
        room_user = RoomUser.model_validate(room_user_data)
    except ValidationError as e:
        await app.send_error_message(sid, f"Error joining the voice room: {e}")
        return

    if not room_user:
        await app.send_error_message(sid, "User not found in the room.")
        return

    await upsert_room_user(db, room_user)
    await delete_temp_room_user_by_user_uuid(db, user_uuid)

    # join socketio room
    app.enter_room(sid, get_room_name(data.room_uuid))

    # emit the event to all the participants in the room about the new user
    await app.emit(
        "new_user",
        {
            "uuid": user_uuid,
            "status": "online",
            "mic": room_user.mic,
            "role": room_user.role,
        },
        room=get_room_name(data.room_uuid),
        skip_sid=sid,
    )

    await publish_user_joined_room(nc, user_uuid, data.room_uuid)


@app.event("leave_room")
async def leave_room(
        sid,
        db: Database = Depends(get_db),
        nc: Client = Depends(get_nats_client),
):
    """
    Handles the leaving of a voice room.

    Response (emitted to everybody in the room except for the sender):
    `leave_user` event

    Data:

    .. code-block:: json

            {
                "uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p"
            }

    """
    user_session = await app.get_session(sid)
    if not user_session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = user_session.user_uuid

    room_users = await get_room_users_by_user_uuid(db, user_uuid)
    for room_user in room_users:
        await app.emit(
            "leave_user",
            {"uuid": user_uuid},
            room=get_room_name(room_user.get("room_uuid")),
            skip_sid=sid,
        )

    await delete_room_users_by_user_uuid(db, user_uuid)
    await publish_user_left_all_rooms(nc, user_uuid)


@app.event("video_play")
async def video_play(sid, data: RoomActionRequest):
    """
    Handles the playing of a video in a room.

    The client should validate that the event is only emitted by the admin of the room.

    Request:
    :py:class:`fliji_sockets.models.socket.RoomActionRequest`

    Response (emitted to everybody in the room):
    `video_play` event

    data

    .. code-block:: json

        {
            "from_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p"
        }

    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await app.emit(
        "video_play",
        {"from_uuid": session.user_uuid},
        room=get_room_name(data.room_uuid),
    )


@app.event("video_pause")
async def video_pause(sid, data: RoomActionRequest):
    """
    Handles the pausing of a video in a room.

    The client should validate that the event is only emitted by the admin of the room.

    Request:
    :py:class:`fliji_sockets.models.socket.RoomActionRequest`

    Response (emitted to everybody the room):
    `video_pause` event

    data

    .. code-block:: json

        {
            "from_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p"
        }
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await app.emit(
        "video_pause",
        {"from_uuid": session.user_uuid},
        room=get_room_name(data.room_uuid),
    )


@app.event("video_timecode")
async def video_timecode(sid, data: VideoTimecodeRequest):
    """
    Broadcasts the current timecode of the video in a room.

    The client should validate that the event is only emitted by the admin of the room.

    Request:
    :py:class:`fliji_sockets.models.socket.VideoTimecodeRequest`

    Response (emitted to everybody in the room except for the sender):
    `video_timecode` event

    Data:

    .. code-block:: json

            {
                "timecode": 15,
                "from_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p"
            }

    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await app.emit(
        "video_timecode",
        {"timecode": data.timecode, "from_uuid": session.user_uuid},
        room=get_room_name(data.room_uuid),
        skip_sid=sid,
    )


@app.event("current_duration")
async def current_duration(sid, data: CurrentDurationRequest):
    """
    Broadcasts the current duration of the video in a room.

    Request:
    :py:class:`fliji_sockets.models.socket.RoomActionRequest`

    Response (emitted to everybody in the room except for the sender):
    `current_duration` event

    Data:

    .. code-block:: json

                {
                    "duration": 15,
                    "is_played": true
                }

    """
    await app.emit(
        "current_duration",
        {
            "duration": data.duration,
            "is_played": data.is_played,
        },
        room=get_room_name(data.room_uuid),
        skip_sid=sid,
    )


@app.event("get_status")
async def get_status(
        sid,
        data: RoomActionRequest,
        db: Database = Depends(get_db),
):
    """
    Handles the request for the voice status of a room.

    Request:
    :py:class:`fliji_sockets.models.socket.RoomActionRequest`

    Response (emitted to the client):
    `status` event

    Data:
    :py:class:`fliji_sockets.models.user_service_api.GetStatusResponse`

    """
    user_session = await app.get_session(sid)
    if not user_session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    response = []
    room_users = await get_room_users_by_room_uuid(db, data.room_uuid)
    for room_user in room_users:
        response.append(
            {
                "first_name": room_user.get("first_name"),
                "last_name": room_user.get("last_name"),
                "avatar_url": room_user.get("avatar_url"),
                "username": room_user.get("username"),
                "uuid": room_user.get("user_uuid"),
                "status": "online",
                "mic": room_user.get("mic"),
                "mic_ban": room_user.get("mic_ban"),
                "role": room_user.get("role"),
                "right_to_speak": room_user.get("right_to_speak"),
            }
        )

    await app.emit("status", response, room=sid)


@app.event("toggle_user_mic")
async def toggle_user_mic(
        sid,
        data: ToggleVoiceUserMicRequest,
        db: Database = Depends(get_db),
):
    """
    Toggles the mic of a user in a room.
    Only the admin of the room can toggle the mic of other users.

    Request:
    :py:class:`fliji_sockets.models.socket.ToggleVoiceUserMicRequest`

    Response (emitted to everybody in the room):
    `mic_user` event

    Data:
    :py:class:`fliji_sockets.models.user_service_api.ToggleVoiceUserMicResponse`

    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    admin_room_user = await get_room_user(db, data.room_uuid, user_uuid)
    if admin_room_user.get("role") not in [RoomUserRole.ADMIN, RoomUserRole.MODERATOR]:
        await app.send_error_message(sid, "You do not have the permission to toggle the user mic.")
        return

    room_user_data = await get_room_user(db, data.room_uuid, data.user_uuid)
    if not room_user_data:
        await app.send_error_message(
            sid,
            f"Voice with uuid {data.room_uuid} or user with uuid {data.user_uuid} not found",
        )
        return

    try:
        room_user = RoomUser.model_validate(room_user_data)
    except ValidationError as e:
        await app.send_error_message(sid, f"Error toggling the user mic: {e}")
        return

    if room_user.mic:
        room_user.mic = False
    else:
        room_user.mic = True
        room_user.right_to_speak = None

    await upsert_room_user(db, room_user)

    await app.emit(
        "mic_user",
        {
            "uuid": room_user.user_uuid,
            "mic": room_user.mic,
            "right_to_speak": room_user.right_to_speak,
        },
        room=get_room_name(data.room_uuid),
    )


@app.event("transfer_room_ownership")
async def transfer_room_ownership(
        sid,
        data: TransferRoomOwnershipRequest,
        db: Database = Depends(get_db),
):
    """
    Handles the transfer of the ownership of a room.

    Request:
    :py:class:`fliji_sockets.models.socket.TransferRoomOwnershipRequest`

    Response (emitted to the room):
    `role_updated` event

    Data:
    :py:class:`fliji_sockets.models.user_service_api.TransferRoomOwnershipResponse`
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    room_data = get_room_by_uuid(db, data.room_uuid)
    if not room_data:
        await app.send_error_message(sid, f"Voice with uuid {data.room_uuid} not found")
        return

    room = Room.model_validate(room_data)
    if room.author != user_uuid:
        await app.send_error_message(sid, "Only the admin can transfer the room ownership.")
        return

    new_owner_data = get_room_user(db, data.room_uuid, data.new_owner_uuid)
    if not new_owner_data:
        await app.send_error_message(
            sid,
            f"Voice with uuid {data.room_uuid} or user with uuid {data.new_owner_uuid} not found"
        )

    new_owner = RoomUser.model_validate(new_owner_data)
    new_owner.role = RoomUserRole.ADMIN
    await upsert_room_user(db, new_owner)

    await app.emit(
        "role_updated",
        {
            "user_uuid": new_owner.user_uuid,
            "role": new_owner.role,
        },
        room=get_room_name(data.room_uuid),
    )


@app.event("kick_user")
async def kick_user(
        sid,
        data: KickUserRequest,
        db: Database = Depends(get_db),
        nc: Client = Depends(get_nats_client),
):
    """
    Change user's role in a room. Only the admin of the room can change the role of other users.

    Request:
    :py:class:`fliji_sockets.models.socket.KickUserRequest`

    Response (emitted to the room):
    `leave_user` event

    Data:

    .. code-block:: json

                {
                    "user_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
                }

    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    admin_data = await get_room_user(db, data.room_uuid, user_uuid)
    if not admin_data:
        await app.send_error_message(sid, "User not found in the room.")
        return

    admin = RoomUser.model_validate(admin_data)
    if admin.role not in [RoomUserRole.ADMIN, RoomUserRole.MODERATOR]:
        await app.send_error_message(sid, "Only the admin can kick users.")
        return

    user_data = await get_room_user(db, data.room_uuid, data.user_uuid)
    if not user_data:
        await app.send_error_message(sid, "User not found in the room.")
        return

    user = RoomUser.model_validate(user_data)
    await delete_room_users_by_user_uuid(db, user.user_uuid)

    await app.emit(
        "leave_user",
        {
            "uuid": user.user_uuid,
        },
        room=get_room_name(data.room_uuid),
    )

    await publish_user_disconnected(nc, user_uuid)


@app.event("change_role")
async def change_role(
        sid,
        data: ChangeRoleRequest,
        db: Database = Depends(get_db),
):
    """
    Change user's role in a room. Only the admin of the room can change the role of other users.

    Request:
    :py:class:`fliji_sockets.models.socket.ChangeRoleRequest`

    Response (emitted to the room):
    `role_updated` event

    Data:

    .. code-block:: json

                {
                    "user_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
                    "role": "moderator"
                }

    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    admin_data = await get_room_user(db, data.room_uuid, user_uuid)
    if not admin_data:
        await app.send_error_message(sid, "User not found in the room.")
        return

    admin = RoomUser.model_validate(admin_data)
    if admin.role != RoomUserRole.ADMIN:
        await app.send_error_message(sid, "Only the admin can change the role of other users.")
        return

    user_data = await get_room_user(db, data.room_uuid, data.user_uuid)
    if not user_data:
        await app.send_error_message(sid, "User not found in the room.")
        return

    user = RoomUser.model_validate(user_data)
    user.role = data.new_role
    await upsert_room_user(db, user)

    await app.emit(
        "role_updated",
        {
            "user_uuid": user.user_uuid,
            "role": user.role,
        },
        room=get_room_name(data.room_uuid),
    )


@app.event("confirm_room_ownership_transfer")
async def confirm_room_ownership_transfer(
        sid,
        data: ConfirmRoomOwnershipTransferRequest,
        db: Database = Depends(get_db),
        nc: Client = Depends(get_nats_client),
):
    """
    Handles the confirmation of the ownership transfer of a room.

    Request:
    :py:class:`fliji_sockets.models.socket.ConfirmRoomOwnershipTransferRequest`

    Response (emitted to the room):
    `role_updated` event

    Data:
    :py:class:`fliji_sockets.models.user_service_api.ConfirmRoomOwnershipTransferResponse`
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    room_data = get_room_by_uuid(db, data.room_uuid)
    if not room_data:
        await app.send_error_message(sid, f"Voice with uuid {data.room_uuid} not found")
        return

    room = Room.model_validate(room_data)
    if room.author != user_uuid:
        await app.send_error_message(sid, "Only the admin can confirm the room ownership transfer.")
        return

    old_owner_data = get_room_user(db, data.room_uuid, data.old_owner_uuid)
    if not old_owner_data:
        await app.send_error_message(
            sid,
            f"Voice with uuid {data.room_uuid} or user with uuid {data.old_owner_uuid} not found"
        )

    new_owner_data = get_room_user(db, data.room_uuid, data.new_owner_uuid)
    if not new_owner_data:
        await app.send_error_message(
            sid,
            f"Voice with uuid {data.room_uuid} or user with uuid {data.new_owner_uuid} not found"
        )

    new_owner = RoomUser.model_validate(new_owner_data)

    new_owner.role = RoomUserRole.ADMIN
    await upsert_room_user(db, new_owner)

    await publish_room_ownership_changed(nc, data.room_uuid, new_owner.user_uuid)

    old_owner = RoomUser.model_validate(old_owner_data)
    old_owner.role = RoomUserRole.USER
    await upsert_room_user(db, old_owner)

    room.author = new_owner.user_uuid
    await upsert_room(db, room)

    await app.emit(
        "role_updated",
        {
            "user_uuid": old_owner.user_uuid,
            "role": old_owner.role,
        },
        room=get_room_name(data.room_uuid),
    )


@app.event("send_chat_message")
async def send_chat_message(
        sid,
        data: SendChatMessageRequest,
        db: Database = Depends(get_db),
        nc: Client = Depends(get_nats_client),
):
    """
    Handles the sending of a chat message in a room.

    Request:
    :py:class:`fliji_sockets.models.socket.SendChatMessageRequest`

    Response (emitted to the room):
    `chat_message` event

    Data:
    :py:class:`fliji_sockets.models.user_service_api.SendChatMessageResponse`
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    room_data = await get_room_by_uuid(db, data.room_uuid)
    if not room_data:
        await app.send_error_message(sid, f"Room not found.")
        return

    room = Room.model_validate(room_data)

    room_user_data = await get_room_user(db, data.room_uuid, user_uuid)
    if not room_user_data:
        await app.send_error_message(sid, f"User not found in the room.")
        return

    message = ChatMessage(
        room_uuid=data.room_uuid,
        user_uuid=user_uuid,
        message=data.message,
        internal_chat_id=room.internal_chat_id,
        chat_id=room.chat_id,
    )
    await insert_chat_message(db, message)

    await publish_chat_message(nc, room.chat_id, data.room_uuid, user_uuid, data.message)

    await app.emit(
        "chat_message",
        {
            "user_uuid": user_uuid,
            "message": data.message,
            "username": session.username,
            "time": datetime.now().isoformat(),
        },
        room=get_room_name(data.room_uuid),
    )


@app.event("request_right_to_speak")
async def request_right_to_speak(sid, data: RoomActionRequest):
    """
    Handles the request for the right to speak in a room.

    Request:
    :py:class:`fliji_sockets.models.socket.RoomActionRequest`

    Response (emitted to the room):
    `right_to_speak_reqeust` event

    Data:

    .. code-block:: json

            {
                "user_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p"
            }
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    await app.emit(
        "right_to_speak_reqeust",
        {"user_uuid": user_uuid},
        room=get_room_name(data.room_uuid),
        skip_sid=sid,
    )


@app.event("handle_right_to_speak")
async def handle_right_to_speak(
        sid,
        data: HandleRightToSpeakRequest,
        db: Database = Depends(get_db),
):
    """
    Handles the handling of the right to speak request in a room.
    Only the admin of the room can handle the right to speak request.

    Request:
    :py:class:`fliji_sockets.models.socket.HandleRightToSpeakRequest`

    Response (emitted to the room):
    `right_to_speak_updated` event

    Data:
    :py:class:`fliji_sockets.models.user_service_api.HandleRightToSpeakResponse`

    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    # convert the boolean to the enum state string
    if data.right_to_speak is True:
        right_to_speak = RightToSpeakState.ACCEPTED
    else:
        right_to_speak = RightToSpeakState.DECLINED

    admin_user_data = await get_room_user(db, data.room_uuid, user_uuid)
    if not admin_user_data:
        await app.send_error_message(sid, f"User not found in the room.")
        return

    admin_user = RoomUser.model_validate(admin_user_data)
    if admin_user.role not in [RoomUserRole.ADMIN, RoomUserRole.MODERATOR]:
        await app.send_error_message(sid,
                                     "You do not have the right to handle the right to speak request.")
        return

    user_data = await get_room_user(db, data.room_uuid, data.user_uuid)
    if not user_data:
        await app.send_error_message(sid, f"User not found in the room.")
        return

    user = RoomUser.model_validate(user_data)
    if user.right_to_speak != RightToSpeakState.PENDING:
        await app.send_error_message(sid, "User did not request the right to speak.")
        return

    user.right_to_speak = right_to_speak
    await upsert_room_user(db, user)

    await app.emit(
        "right_to_speak_updated",
        {
            "user_uuid": user.user_uuid,
            "right_to_speak": user.right_to_speak,
        },
        room=get_room_name(data.room_uuid),
    )


if APP_ENV != "local":
    # remove all transient session data
    database = get_database()
    delete_all_sessions(database)


def fill_mock_data():
    """
    Fill the database with mock data.
    """
    # the seed is a random string
    # generate a random string seed
    video_uuids = [
        "213d9e98-4431-4f68-bf33-dd0111f948e5",
        "9003ea4f-8ea4-4cbb-8fe8-243860f221ce",
        "1364a011-c7ba-4bea-9297-ad3ec6cb3872",
        "1364a011-c7ba-4bea-9297-ad3ec6cb3872",
        "9003ea4f-8ea4-4cbb-8fe8-243860f221ce",
        "63fd32c3-fbb2-43be-ab94-f0f74b5e7d55",
        "f5a0531b-9eb8-4f9b-bf4c-875a6ee78a17",
        "e6e392b2-846d-472b-abcc-f9992cb2b59a",
        "7dfbbd1c-5456-47a7-bd9b-e98c23990c9f",
        "d6496ac5-144e-423b-b421-14c13ed2c218",
        "1d2a32da-435c-488d-8d42-3817a83d17ce",
        "f9de0486-d1ab-46ba-b451-706d1473bd8b",
        "a1d4c8d7-683f-4193-b2ff-aa226cb37574",
    ]

    random_avatar_seed = "".join(
        random.choices(string.ascii_uppercase + string.digits, k=8)
    )

    db = get_database()
    for video_uuid in video_uuids:
        view_session = ViewSession(
            sid="sid",
            last_update_time=datetime.now(),
            current_watch_time=15,
            video_uuid=video_uuid,
            user_uuid="0ebc493f-bf2c-46be-84f1-b6ffcd1ff161",
            avatar="https://api.dicebear.com/avatars/avataaars/" + random_avatar_seed,
            username="username",
            first_name="first_name",
            last_name="last_name",
            bio="bio",
        )
        db.view_sessions.insert_one(view_session.model_dump(exclude_none=True))


# fill_mock_data()

# Expose the sio_app for Uvicorn to run
sio_asgi_app = app.get_asgi_app()
