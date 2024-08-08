import logging
import random
import time
import uuid
from datetime import datetime

from nats.aio.client import Client
from pydantic import ValidationError
from pymongo.database import Database

from fliji_sockets.api_client import FlijiApiService, ApiException
from fliji_sockets.dependencies import get_db, get_api_service, get_nats_client
from fliji_sockets.event_publisher import publish_user_watched_video, \
    publish_user_started_watching_video, publish_user_joined_room, \
    publish_user_left_all_rooms, publish_chat_message, publish_user_disconnected, \
    publish_user_online, publish_user_offline, publish_room_ownership_changed, \
    publish_user_connected_to_timeline, publish_user_joined_timeline_group, \
    publish_user_left_timeline, publish_enable_fliji_mode, \
    publish_disable_fliji_mode, publish_user_left_timeline_group
from fliji_sockets.helpers import get_room_name, configure_logging, configure_sentry
from fliji_sockets.models.base import UserSession
from fliji_sockets.models.database import ViewSession, RoomUser, Room, ChatMessage, \
    TimelineWatchSession, TimelineGroup, TimelineChatMessage
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
    CurrentDurationRequest, ChangeRoleRequest, KickUserRequest, TimelineConnectRequest,
    TimelineJoinGroupRequest,
    TimelineSendChatMessageRequest, TimelineUpdateTimecodeRequest, TimelineJoinUserRequest,
    TimelineSetMicEnabled, TimelineSetPauseStateRequest
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
    insert_chat_message, upsert_timeline_watch_session, delete_timeline_watch_session_by_user_uuid,
    get_timeline_watch_session_by_user_uuid, get_timeline_group_by_uuid, upsert_timeline_group,
    get_timeline_status, delete_all_timeline_groups, delete_all_timeline_watch_sessions,
    get_timeline_group_users, insert_timeline_chat_message,
    get_timeline_chat_messages_by_video_uuid, delete_timeline_group_by_uuid, )

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
    Этот ивент должен быть вызван когда сокет подключается.

    В этом ивенте происходит авторизация пользователя и сохранение его данных в сессии.

    После `startup` можно вызывать другие ивенты.
    Пользователь считается онлайн после вызова этого ивента.


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
    """
    Этот ивент меняет статус пользователя на онлайн.
    После `startup` ивента пользователь и так считается онлайн.

    Этот ивент нужен для того, чтобы можно было ставить статус офлайн если пользователь
    не пользуется приложением (idle), но при этом не отключился.


    Для этого есть ивент `go_offline`. После того как пользователь проявил активность,
     нужно вызвать `go_online`.
    """
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
    """
    Этот ивент меняет статус пользователя на офлайн.
    Для принципа работы см. `go_online`.
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await publish_user_offline(nc, session.user_uuid)


@app.event("enable_fliji_mode")
async def enable_fliji_mode(
        sid,
        nc: Client = Depends(get_nats_client),
):
    """
    Включает режим флиджи для пользователя.
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await publish_enable_fliji_mode(nc, session.user_uuid)


@app.event("disable_fliji_mode")
async def disable_fliji_mode(
        sid,
        nc: Client = Depends(get_nats_client),
):
    """
    Выключает режим флиджи для пользователя.
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await publish_disable_fliji_mode(nc, session.user_uuid)


@app.event("disconnect")
async def disconnect(
        sid,
        db: Database = Depends(get_db),
        nc=Depends(get_nats_client),
):
    """
    Этот ивент отвечает за отключение пользователя от сокета.

    Можно не вызывать вручную, так как он вызывается автоматически при отключении пользователя.
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

        if view_session.get("group_uuid") is not None:
            # emit the global status event to all the users in the group that the user left
            timeline_status_data = await get_timeline_status(db, video_uuid)

            sio_room_identifier = get_room_name(video_uuid)
            await app.emit(
                "timeline_status",
                timeline_status_data.model_dump(),
                room=sio_room_identifier,
            )

    await delete_room_users_by_user_uuid(db, user_uuid)
    await delete_view_session_by_user_uuid(db, user_session.user_uuid)

    await publish_user_disconnected(nc, user_uuid)

    timeline_watch_session_data = await get_timeline_watch_session_by_user_uuid(db, user_uuid)
    timeline_watch_session = TimelineWatchSession.model_validate(timeline_watch_session_data)
    await handle_user_timeline_leave(db, nc, timeline_watch_session)


async def handle_user_timeline_group_leave(nc: Client, db: Database,
                                           watch_session: TimelineWatchSession):
    if watch_session.group_uuid is None:
        return

    user_uuid = watch_session.user_uuid

    # later we will clear the group_uuid from the watch session, so we need to save it here
    group_uuid = watch_session.group_uuid

    group_data = await get_timeline_group_by_uuid(db, group_uuid)

    group = None
    try:
        group = TimelineGroup.model_validate(group_data)
    except ValidationError as e:
        logging.error(f"Error validating timeline group: {e}")

    if group is None:
        logging.warning(f"Group {group_uuid} not found. Could not leave the group.")
        return

    app.leave_room(watch_session.sid, get_room_name(group_uuid))
    group.users_count -= 1

    # users of the group
    group_users = await get_timeline_group_users(db, group_uuid)

    # if next to last user left the group, delete the group
    if group.users_count <= 1:
        other_group_user = None
        # find the last user in the users list
        if group_users:
            for group_user in group_users:
                if group_user.get("user_uuid") != user_uuid:
                    try:
                        other_group_user = TimelineWatchSession.model_validate(group_user)
                    except ValidationError as e:
                        logging.error(f"Error validating timeline watch session: {e}")

        # move the last user out of the group
        if other_group_user:
            other_group_user.group_uuid = None
            logging.debug(f"Setting group of {other_group_user.user_uuid} to None")
            await upsert_timeline_watch_session(db, other_group_user)
        group = None

        await delete_timeline_group_by_uuid(db, group_uuid)
    else:
        await upsert_timeline_group(db, group)

    # leave the room
    logging.debug(f"Leaving room {group_uuid} for user {user_uuid}")
    watch_session.group_uuid = None
    await upsert_timeline_watch_session(db, watch_session)

    # emit the global status event to all the users in the group that the user left
    timeline_status_data = await get_timeline_status(db, watch_session.video_uuid)
    sio_room_identifier = get_room_name(watch_session.video_uuid)
    await app.emit(
        "timeline_status",
        timeline_status_data.model_dump(),
        room=sio_room_identifier
    )

    group_participants_uuids = []
    if group_users:
        for group_user in group_users:
            if group_user.get("user_uuid") != user_uuid:
                group_participants_uuids.append(group_user.get("user_uuid"))

    await publish_user_left_timeline_group(nc, user_uuid, group_uuid, group_participants_uuids)

    # if host left the group, change the host
    if group.host_uuid == user_uuid:
        group_users = await get_timeline_group_users(db, group_uuid)
        if group_users:
            last_user = None

            for group_user in group_users:
                if group_user.get("user_uuid") != user_uuid:
                    last_user = group_user.get("user_uuid")
                    break

            group.host_user_uuid = last_user.get("user_uuid")
            await upsert_timeline_group(db, group)


async def handle_user_timeline_leave(db: Database, nc: Client,
                                     timeline_watch_session: TimelineWatchSession):
    watch_session = TimelineWatchSession.model_validate(timeline_watch_session)

    await handle_user_timeline_group_leave(nc, db, watch_session)

    await delete_timeline_watch_session_by_user_uuid(db, watch_session.user_uuid)

    try:
        app.leave_room(watch_session.sid, get_room_name(watch_session.video_uuid))
    except Exception as e:
        logging.error(f"Error leaving room: {e}")

    await publish_user_left_timeline(nc, watch_session.user_uuid, watch_session.video_uuid)

    # emit the global status event to all the users in the group that the user left
    timeline_status_data = await get_timeline_status(db, watch_session.video_uuid)
    sio_room_identifier = get_room_name(watch_session.video_uuid)
    await app.emit(
        "timeline_status",
        timeline_status_data.model_dump(),
        room=sio_room_identifier
    )


@app.event("end_video_watch_session")
async def end_video_watch_session(
        sid,
        data: EndVideoWatchSessionRequest,
        db: Database = Depends(get_db),
        nc: Client = Depends(get_nats_client),
):
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
                                     "You do not have the right" +
                                     " to handle the right to speak request.")
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


@app.event("timeline_connect")
async def timeline_connect(
        sid,
        data: TimelineConnectRequest,
        nc: Client = Depends(get_nats_client),
        db: Database = Depends(get_db),
):
    """
    Подключение к таймлайну видео.
    После подключения пользователь получает статус таймлайна и историю чата.
    Только после этого ивента можно вызывать остальные timeline_* ивенты.

    Request:
    :py:class:`fliji_sockets.models.socket.TimelineConnectRequest`

    Response
    Event `timeline_status` is emitted to everybody globally:
    :py:class:`fliji_sockets.models.socket.TimelineStatusResponse`

    Event `timeline_server_timestamp` is emitted to the user:

    Data:

    .. code-block:: json

            {
                "timestamp": 1617000000
            }

    Event `timeline_chat_history` is emitted to the user:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineChatMessage`
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    session_already_exists = await get_timeline_watch_session_by_user_uuid(db, user_uuid)
    if session_already_exists is None:
        await publish_user_connected_to_timeline(nc, user_uuid, data.video_uuid)

    # delete the old view session
    await delete_timeline_watch_session_by_user_uuid(db, user_uuid)

    watch_session = TimelineWatchSession(
        sid=sid,
        last_update_time=datetime.now(),
        watch_time=0,
        video_uuid=data.video_uuid,
        user_uuid=user_uuid,
        mic_enabled=False,
        avatar=session.avatar,
        username=session.username,
        first_name=session.first_name,
        last_name=session.last_name,
        bio=session.bio,
    )

    await upsert_timeline_watch_session(db, watch_session)

    sio_room_identifier = get_room_name(data.video_uuid)

    # join socketio room
    app.enter_room(sid, sio_room_identifier)

    # emit the global status event
    timeline_status_data = (await get_timeline_status(db, data.video_uuid)).model_dump()
    await app.emit(
        "timeline_status",
        timeline_status_data,
        room=sio_room_identifier,
    )

    await app.emit(
        "timeline_server_timestamp",
        {"timestamp": int(time.time())},
        room=sid,
    )

    chat_messages = await get_timeline_chat_messages_by_video_uuid(db, watch_session.video_uuid)
    chat_messages_response_data = []
    for chat_message in chat_messages:
        msg = TimelineChatMessage.model_validate(chat_message)
        chat_messages_response_data.append(
            {
                "id": str(msg.id),
                "user_uuid": msg.user_uuid,
                "message": msg.message,
                "username": msg.username,
                "user_avatar": msg.user_avatar,
                "first_name": msg.first_name,
                "last_name": msg.last_name,
                "created_at": msg.created_at.isoformat(),
            }
        )

    await app.emit(
        "timeline_chat_history",
        chat_messages_response_data,
        room=sid,
    )


@app.event("timeline_join_user")
async def timeline_join_user(
        sid,
        data: TimelineJoinUserRequest,
        nc: Client = Depends(get_nats_client),
        db: Database = Depends(get_db),
):
    """
    Присоединиться к одиночному пользователю на таймлайне видео.

    Request:
    :py:class:`fliji_sockets.models.socket.TimelineJoinUserRequest`

    Response
    Event `timeline_status` is emitted to everybody globally:
    :py:class:`fliji_sockets.models.socket.TimelineStatusResponse`

    Also emits `timeline_group_user_joined` event to the host.
    This can be used to show a notification to the host.

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

    timeline_watch_session = await get_timeline_watch_session_by_user_uuid(db, user_uuid)
    watch_session = TimelineWatchSession.model_validate(timeline_watch_session)

    host_timeline_watch_session = await get_timeline_watch_session_by_user_uuid(db, data.user_uuid)
    host_watch_session = TimelineWatchSession.model_validate(host_timeline_watch_session)

    if host_watch_session.group_uuid is not None:
        await app.send_error_message(sid, "User is already in a group.")
        return

    # create a new group
    group = TimelineGroup(
        group_uuid=str(uuid.uuid4()),
        video_uuid=watch_session.video_uuid,
        host_user_uuid=data.user_uuid,
        users_count=2,
        watch_time=host_watch_session.watch_time,
        on_pause=host_watch_session.on_pause,
    )
    await upsert_timeline_group(db, group)

    # update the watch sessions
    watch_session.last_update_time = datetime.now()
    watch_session.group_uuid = group.group_uuid

    host_watch_session.last_update_time = datetime.now()
    host_watch_session.group_uuid = group.group_uuid

    await upsert_timeline_watch_session(db, watch_session)
    await upsert_timeline_watch_session(db, host_watch_session)

    # identifier for the room of the group
    sio_group_room = get_room_name(group.group_uuid)

    # identifier for the room of the timeline video (global)
    sio_timeline_room = get_room_name(watch_session.video_uuid)

    # join socketio room for the group
    app.enter_room(sid, sio_group_room)
    app.enter_room(host_watch_session.sid, sio_group_room)

    # emit the global status event
    timeline_status_data = await get_timeline_status(db, group.video_uuid)
    await app.emit(
        "timeline_status",
        timeline_status_data.model_dump(),
        room=sio_timeline_room,
    )

    await app.emit(
        "timeline_group_user_joined",
        {
            "user_uuid": user_uuid,
        },
        room=sio_group_room,
    )

    await publish_user_joined_timeline_group(nc, user_uuid, group.group_uuid)


@app.event("timeline_set_mic_enabled")
async def timeline_set_mic_enabled(
        sid,
        data: TimelineSetMicEnabled,
        db: Database = Depends(get_db),
):
    """
    Включить или выключить микрофон на таймлайне видео.

    Request:
    :py:class:`fliji_sockets.models.socket.TimelineSetMicEnabled`

    Response
    Event `timeline_status` is emitted to everybody globally:
    :py:class:`fliji_sockets.models.socket.TimelineStatusResponse`
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    timeline_watch_session = await get_timeline_watch_session_by_user_uuid(db, user_uuid)
    watch_session = TimelineWatchSession.model_validate(timeline_watch_session)

    watch_session.mic_enabled = data.mic_enabled
    await upsert_timeline_watch_session(db, watch_session)

    sio_timeline_room = get_room_name(watch_session.video_uuid)
    if sio_timeline_room:
        # emit the global status event
        timeline_status_data = await get_timeline_status(db, watch_session.video_uuid)
        await app.emit(
            "timeline_status",
            timeline_status_data.model_dump(),
            room=sio_timeline_room,
        )


@app.event("timeline_fetch_chat_history")
async def timeline_fetch_chat_history(
        sid,
        db: Database = Depends(get_db),
):
    """
    Оставлено для совместимости. При `timeline_connect` уже отправляется история чата.

    Получить историю чата на таймлайне видео.

    Response
    Event `timeline_chat_history` is emitted to the user:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineChatMessage`
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    timeline_watch_session = await get_timeline_watch_session_by_user_uuid(db, user_uuid)
    watch_session = TimelineWatchSession.model_validate(timeline_watch_session)

    chat_messages = await get_timeline_chat_messages_by_video_uuid(db, watch_session.video_uuid)
    response_data = []
    for chat_message in chat_messages:
        msg = TimelineChatMessage.model_validate(chat_message)
        response_data.append(
            {
                "id": str(msg.id),
                "user_uuid": msg.user_uuid,
                "message": msg.message,
                "username": msg.username,
                "user_avatar": msg.user_avatar,
                "first_name": msg.first_name,
                "last_name": msg.last_name,
                "created_at": msg.created_at.isoformat(),
            }
        )

    await app.emit(
        "timeline_chat_history",
        response_data,
        room=sid,
    )


@app.event("timeline_update_timecode")
async def timeline_update_timecode(
        sid,
        data: TimelineUpdateTimecodeRequest,
        db: Database = Depends(get_db),
):
    """
    Обновить таймкод для пользователя на таймлайне.
    Если пользователь находится в группе и является хостом,
    таймкод обновляется для группы и отправляется событие всем пользователям
    в группе.

    Если пользователь не находится в группе, таймкод обновляется для пользователя.

    Если видео было на паузе, то при обновлении таймкода on_pause ставится в False.

    Request:
    :py:class:`fliji_sockets.models.socket.TimelineUpdateTimecodeRequest`

    Response
    Event `timeline_timecode` is emitted to users in the group:

    Data:

    .. code-block:: json

        {
            "timecode": 15,
            "server_timestamp": "1934023948234"
        }
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    timeline_watch_session = await get_timeline_watch_session_by_user_uuid(db, user_uuid)
    watch_session = TimelineWatchSession.model_validate(timeline_watch_session)

    user_in_group = watch_session.group_uuid is not None

    if not user_in_group:
        watch_session.watch_time = data.timecode
        watch_session.on_pause = False
        await upsert_timeline_watch_session(db, watch_session)
        return

    group = await get_timeline_group_by_uuid(db, watch_session.group_uuid)
    group = TimelineGroup.model_validate(group)

    if group.host_user_uuid != user_uuid:
        await app.send_error_message(sid,
                                     "You are not the host of the group." +
                                     " You can't send the timecode.")
        return

    group.watch_time = data.timecode
    group.on_pause = False

    await upsert_timeline_group(db, group)

    sio_room_identifier = get_room_name(watch_session.group_uuid)

    await app.emit(
        "timeline_timecode",
        {
            "timecode": data.timecode,
            "server_timestamp": data.server_timestamp,
        },
        room=sio_room_identifier,
    )


@app.event("timeline_join_group")
async def timeline_join_group(
        sid,
        data: TimelineJoinGroupRequest,
        nc: Client = Depends(get_nats_client),
        db: Database = Depends(get_db),
):
    """
    Присоединиться к группе пользователей на таймлайне видео.

    Request:
    :py:class:`fliji_sockets.models.socket.TimelineJoinGroupRequest`

    Response
    Event `timeline_status` is emitted to everybody globally:
    :py:class:`fliji_sockets.models.socket.TimelineStatusResponse`
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    timeline_watch_session = await get_timeline_watch_session_by_user_uuid(db, user_uuid)
    timeline_group = await get_timeline_group_by_uuid(db, data.group_uuid)

    watch_session = TimelineWatchSession.model_validate(timeline_watch_session)
    group = TimelineGroup.model_validate(timeline_group)

    previous_group_uuid = watch_session.group_uuid
    if previous_group_uuid is not None:
        # leave the previous group if the user was already in the group
        await handle_user_timeline_group_leave(nc, db, watch_session)

    watch_session.group_uuid = group.group_uuid
    group.users_count += 1

    await upsert_timeline_watch_session(db, watch_session)
    await upsert_timeline_group(db, group)

    sio_room_identifier = get_room_name(group.group_uuid)

    # join socketio room
    app.enter_room(sid, sio_room_identifier)

    # emit the global status event that the user joined the group
    timeline_status_data = await get_timeline_status(db, group.video_uuid)
    await app.emit(
        "timeline_status",
        timeline_status_data.model_dump(),
        room=sio_room_identifier,
    )


@app.event("timeline_leave_group")
async def timeline_leave_group(
        sid,
        nc: Client = Depends(get_nats_client),
        db: Database = Depends(get_db),
):
    """
    Покинуть группу пользователей на таймлайне видео.

    При `timeline_leave` пользователь покидает группу автоматически.

    При `timeline_join_group` пользователь автоматически покидает группу и присоединяется к другой.

    Этот ивент нужен только когда пользователь хочет покинуть группу и остаться один.

    Response
    Event `timeline_status` is emitted to everybody globally:
    :py:class:`fliji_sockets.models.socket.TimelineStatusResponse`
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    timeline_watch_session = await get_timeline_watch_session_by_user_uuid(db, user_uuid)
    watch_session = TimelineWatchSession.model_validate(timeline_watch_session)

    if not watch_session.group_uuid:
        await app.send_error_message(sid, "User is not in a group.")
        return

    await handle_user_timeline_group_leave(nc, db, watch_session)


@app.event("timeline_leave")
async def timeline_leave(
        sid,
        nc: Client = Depends(get_nats_client),
        db: Database = Depends(get_db),
):
    """
    Отключиться от таймлайна видео.

    Response
    Event `timeline_status` is emitted to everybody globally:
    :py:class:`fliji_sockets.models.socket.TimelineStatusResponse`
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    timeline_watch_session = await get_timeline_watch_session_by_user_uuid(db, user_uuid)
    watch_session = TimelineWatchSession.model_validate(timeline_watch_session)

    await handle_user_timeline_leave(db, nc, watch_session)

    # emit the global status event
    timeline_status_data = await get_timeline_status(db, watch_session.video_uuid)
    await app.emit(
        "timeline_status",
        timeline_status_data.model_dump(),
        room=get_room_name(watch_session.video_uuid),
    )


@app.event("timeline_get_server_timestamp")
async def timeline_get_server_timestamp(
        sid,
):
    """
    Оставлено для совместимости. При `timeline_connect` уже отправляется серверное время.

    Получить timestamp серверного времени.

    Response
    Event `timeline_server_timestamp` is emitted to the user:

    Data:

    .. code-block:: json

            {
                "timestamp": 1617000000
            }
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await app.emit(
        "timeline_server_timestamp",
        {"timestamp": int(time.time())},
        room=sid,
    )


@app.event("timeline_get_status")
async def timeline_get_status(
        sid,
        db: Database = Depends(get_db),
):
    """
    Пока не используется.


    Запросить статус таймлайна видео.
    Этот ивент отправляется глобально всем пользователям на таймлайне.

    Локально нужно держать таймер когда приходил последний статус.
    Если он не обновлялся больше 5 секунд, то отправляется запрос timeline_get_status.
    Если другой пользователь уже запросил статус, то при обработке статус
    таймер у других участников должен сбрасываться, чтобы не было слишком много запросов.

    Response
    Event `timeline_status` is emitted to everybody globally:
    :py:class:`fliji_sockets.models.socket.TimelineStatusResponse`
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    timeline_watch_session = await get_timeline_watch_session_by_user_uuid(db, user_uuid)
    watch_session = TimelineWatchSession.model_validate(timeline_watch_session)

    # emit the global status event
    timeline_status_data = await get_timeline_status(db, watch_session.video_uuid)
    await app.emit(
        "timeline_status",
        timeline_status_data.model_dump(),
        room=get_room_name(watch_session.video_uuid),
    )


@app.event("timeline_set_pause")
async def timeline_set_pause(
        sid,
        data: TimelineSetPauseStateRequest,
        db: Database = Depends(get_db),
):
    """
    Поставить видео на паузу.
    Этот ивент нужен чтобы у других пользователей на таймлайне видео
    отображалось что видео на паузе.

    group_uuid будет null если пользователь не в группе.

    Request:
    :py:class:`fliji_sockets.models.socket.TimelineSetPauseStateRequest`

    Response
    Event `timeline_pause` is emitted to the users on the timeline:

    Data:

    .. code-block:: json

        {
            "timecode": 15,
            "group_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
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

    timeline_watch_session = await get_timeline_watch_session_by_user_uuid(db, user_uuid)
    watch_session = TimelineWatchSession.model_validate(timeline_watch_session)

    user_in_group = watch_session.group_uuid is not None

    if not user_in_group:
        watch_session.on_pause = True
        watch_session.watch_time = data.timecode
        await upsert_timeline_watch_session(db, watch_session)
    else:
        group_data = await get_timeline_group_by_uuid(db, watch_session.group_uuid)
        group = TimelineGroup.model_validate(group_data)

        if group.host_user_uuid != user_uuid:
            await app.send_error_message(sid, "You are not the host of the group.")
            return

        group.on_pause = True
        group.watch_time = data.timecode
        await upsert_timeline_group(db, group)

    sio_room_identifier = get_room_name(watch_session.video_uuid)

    await app.emit(
        "timeline_pause",
        {
            "timecode": data.timecode,
            "server_timestamp": data.server_timestamp,
            "group_uuid": watch_session.group_uuid,
            "user_uuid": user_uuid,
        },
        room=sio_room_identifier,
    )


@app.event("timeline_send_chat_message")
async def timeline_send_chat_message(
        sid,
        data: TimelineSendChatMessageRequest,
        db: Database = Depends(get_db),
):
    """
    Отправить сообщение в чат на таймлайне видео.

    Ивент о новом сообщении отправляется всем пользователям на таймлайне.

    Request:
    :py:class:`fliji_sockets.models.socket.TimelineSendChatMessageRequest`

    Response (emitted to the room):
    `timeline_chat_message` event

    :py:class:`fliji_sockets.models.database.TimelineChatMessage`
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    timeline_watch_session = await get_timeline_watch_session_by_user_uuid(db, user_uuid)
    watch_session = TimelineWatchSession.model_validate(timeline_watch_session)

    chat_message = TimelineChatMessage(
        user_uuid=user_uuid,
        message=data.message,
        user_avatar=watch_session.avatar,
        username=watch_session.username,
        first_name=watch_session.first_name,
        last_name=watch_session.last_name,
        video_uuid=watch_session.video_uuid,
        created_at=datetime.now().isoformat(),
    )

    await insert_timeline_chat_message(db, chat_message)

    await app.emit(
        "timeline_chat_message",
        {
            "id": str(chat_message.id),
            "user_uuid": chat_message.user_uuid,
            "message": chat_message.message,
            "username": chat_message.username,
            "user_avatar": chat_message.user_avatar,
            "first_name": chat_message.first_name,
            "last_name": chat_message.last_name,
            "created_at": chat_message.created_at.isoformat(),
        },
        room=get_room_name(watch_session.video_uuid),
    )


def clear_data_on_startup():
    # remove all transient session data
    database = get_database()
    delete_all_sessions(database)

    # timeline groups and watch sessions
    delete_all_timeline_groups(database)
    delete_all_timeline_watch_sessions(database)
    # delete_all_timeline_chat_messages(database)


clear_data_on_startup()


def fill_mock_data():
    db = get_database()

    # Dev
    user_uuids = [
        "cfece5a4-3c73-42b3-bcf3-8ebec14b6325",
        "20765a99-ca3c-44b4-97e4-795b403bb7b7",
        "fbd607fc-6b98-4010-872c-e18d19617ec5",
        "47cb7ac1-bd4a-4595-8775-38b5ed8c7162",
    ]

    # Local
    # user_uuids = [
    #     "4f3fc122-ddec-4cb6-bd5e-461078bdb9f0",
    #     "d14aaf88-01fc-461f-a45d-9c81ce682630",
    #     "c08bd461-ae64-46ae-a6c3-8668d8e495ec",
    #     "7e8dc504-9db6-4448-95c9-978ca211225a"
    # ]

    video_uuid = "9d2b6a97-d054-4c68-96ed-af0cb82b97db"
    group_uuid = "0ebc493f-bf2c-46be-84f1-b22fcd1ff165"
    timeline_users = [
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            watch_time=250,
            video_uuid=video_uuid,
            user_uuid=user_uuids.pop(),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="One",
            last_name="Two",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            watch_time=650,
            video_uuid=video_uuid,
            user_uuid=user_uuids.pop(),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="Will",
            last_name="Smith",
            bio="bio",
            mic_enabled=False,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            watch_time=950,
            video_uuid=video_uuid,
            group_uuid=group_uuid,
            user_uuid=user_uuids.pop(),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="Alice",
            last_name="Alice",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            watch_time=950,
            video_uuid=video_uuid,
            group_uuid=group_uuid,
            user_uuid=user_uuids.pop(),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="JoHn",
            last_name="Muir",
            bio="bio",
            mic_enabled=True,
        ),
    ]
    group = TimelineGroup(
        group_uuid=group_uuid,
        video_uuid=video_uuid,
        host_user_uuid=timeline_users[2].user_uuid,
        users_count=2,
    )

    db.timeline_groups.update_one(
        {"group_uuid": group.group_uuid},
        {"$set": group.model_dump(exclude_none=True)},
        upsert=True,
    )

    for user in timeline_users:
        db.timeline_watch_sessions.update_one(
            {"user_uuid": user.user_uuid},
            {"$set": user.model_dump(exclude_none=True)},
            upsert=True,
        )

    chat_messages = [
        "Hey everybody!",
        "How are you?",
        "I am good.",
        "How are you?",
        "I am good.",
    ]

    for chat_message in chat_messages:
        # get random user uuid from timeline_users
        user_uuid = random.choice(timeline_users).user_uuid
        msg = TimelineChatMessage(
            user_uuid=user_uuid,
            message=chat_message,
            username="username",
            first_name="first_name",
            last_name="last_name",
            video_uuid=video_uuid,
            created_at=datetime.now().isoformat(),
        )

        # upsert the message by user_uuid and video_uuid and message
        db.timeline_chat_messages.update_one(
            {"user_uuid": msg.user_uuid, "video_uuid": msg.video_uuid, "message": msg.message},
            {"$set": msg.model_dump(exclude_none=True)},
            upsert=True,
        )


if APP_ENV == "dev" or APP_ENV == "local":
    fill_mock_data()

# Expose the sio_app for Uvicorn to run
sio_asgi_app = app.get_asgi_app()
