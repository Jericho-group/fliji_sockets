import logging
import random
import time
import uuid
from datetime import datetime

import jwt
from nats.aio.client import Client
from pydantic import ValidationError
from pymongo.database import Database

from fliji_sockets.dependencies import get_db, get_nats_client
from fliji_sockets.event_publisher import \
    publish_user_disconnected, \
    publish_user_online, publish_user_offline, publish_user_connected_to_timeline, \
    publish_user_joined_timeline_group, \
    publish_user_left_timeline, publish_enable_fliji_mode, \
    publish_disable_fliji_mode, publish_user_left_timeline_group
from fliji_sockets.helpers import get_room_name, configure_logging, configure_sentry
from fliji_sockets.models.base import UserSession
from fliji_sockets.models.database import TimelineWatchSession, TimelineGroup, \
    TimelineChatMessage
from fliji_sockets.models.socket import (
    OnConnectRequest,
    TimelineConnectRequest,
    TimelineJoinGroupRequest,
    TimelineSendChatMessageRequest, TimelineUpdateTimecodeRequest, TimelineJoinUserRequest,
    TimelineSetMicEnabled, TimelineSetPauseStateRequest, TimelineSetVideoEndedRequest,
    VideoSetViewedRequest, TimelineChatHistoryResponse, TimelineSingleUsersResponse,
    TimelineGroupResponse, TimelineCurrentGroupResponse
)
from fliji_sockets.settings import APP_ENV, TEST_VIDEO_UUID, JWT_SECRET
from fliji_sockets.socketio_application import SocketioApplication, Depends
from fliji_sockets.store import (
    get_database,
    upsert_timeline_watch_session, delete_timeline_watch_session_by_user_uuid,
    get_timeline_watch_session_by_user_uuid, get_timeline_group_by_uuid, upsert_timeline_group,
    get_timeline_status, delete_all_timeline_groups, delete_all_timeline_watch_sessions,
    get_timeline_group_users, insert_timeline_chat_message,
    get_timeline_chat_messages_by_video_uuid, delete_timeline_group_by_uuid,
    get_timeline_single_users, get_timeline_groups, get_timeline_group_users_data, )

app = SocketioApplication()

configure_logging()
configure_sentry()


@app.event("startup")
async def startup(
        sid,
        data: OnConnectRequest,
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
    try:
        decoded = jwt.decode(data.auth_token, JWT_SECRET, algorithms=['HS256'])
    except jwt.exceptions.InvalidTokenError as e:
        logging.info(
            f"Could not decode token for sid {sid} with token {data.auth_token}. Error: {e}")
        await app.send_fatal_error_message(
            sid, f"Could not authenticate user: Invalid token."
        )
        return

    try:
        user_session = UserSession(
            user_uuid=decoded.get("user_uuid"),
            username=decoded.get("username"),
            first_name=decoded.get("first_name"),
            last_name=decoded.get("last_name"),
            bio=decoded.get("bio"),
            avatar=decoded.get("avatar"),
            avatar_thumbnail=decoded.get("avatar_thumbnail"),
        )
    except ValidationError as e:
        logging.error(f"Error validating user session: {e}")
        await app.send_fatal_error_message(sid, f"Error validating user session: {e}")
        return

    try:
        await app.save_session(
            sid,
            user_session
        )
    except Exception as e:
        logging.error(f"Could not save session: {e}")
        await app.send_fatal_error_message(sid, f"Could not save session: {e}")
        return

    logging.info(f"User {user_session.user_uuid} authenticated successfully")

    await publish_user_online(nc, user_session.user_uuid)
    await publish_enable_fliji_mode(nc, user_session.user_uuid)


@app.event("ping")
async def ping(
        sid,
):
    """
    Этот ивент нужен для проверки соединения.

    Возвращает ивент `pong`. со следующими данными:

    .. code-block:: json

        {
            "message": "pong"
        }

    """
    await app.emit("pong", {"message": "pong"}, room=sid)


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
        db: Database = Depends(get_db),
        nc: Client = Depends(get_nats_client),
):
    """
    Выключает режим флиджи для пользователя.

    Пользователь автоматически покидает таймлайн видео, если он находится в нем.
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await publish_disable_fliji_mode(nc, session.user_uuid)

    timeline_watch_session = await get_timeline_watch_session_by_user_uuid(db, session.user_uuid)

    if timeline_watch_session:
        watch_session = TimelineWatchSession.model_validate(timeline_watch_session)

        await handle_user_timeline_leave(db, nc, watch_session)


@app.event("video_set_viewed")
async def video_set_viewed(
        sid,
        data: VideoSetViewedRequest,
        nc: Client = Depends(get_nats_client),
):
    """
    Request:
    :py:class:`fliji_sockets.models.socket.VideoSetViewedRequest`

    Сохраняет информацию о просмотре видео.
    Нужно вызывать этот ивент когда пользователь закончил просмотр видео с выключенным режимом флиджи.
    Если режим флиджи включен, то при выходе из таймлайна видео, информация о просмотре сохраняется автоматически.
    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    logging.info(
        f"User {session.user_uuid} viewed video {data.video_uuid} for {data.watch_time} seconds")
    await publish_user_left_timeline(nc, session.user_uuid, data.video_uuid, data.watch_time)

    logging.info("sent user left timeline")


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

    if not user_session:
        logging.warning(f"On disconnect: user session not found for sid {sid}")
        return

    user_uuid = user_session.user_uuid

    watch_session = await get_timeline_watch_session_by_user_uuid(db, user_uuid)

    # save the dangling watch session
    if (
            watch_session is not None
            and (watch_session.get("video_uuid") is not None)
            and (watch_session.get("watch_time") is not None)
    ):
        video_uuid = watch_session.get("video_uuid")
        watch_time = watch_session.get("watch_time")
        await publish_user_left_timeline(nc, user_uuid, video_uuid, watch_time)

    await publish_user_disconnected(nc, user_uuid)

    timeline_watch_session_data = await get_timeline_watch_session_by_user_uuid(db, user_uuid)

    try:
        timeline_watch_session = TimelineWatchSession.model_validate(timeline_watch_session_data)
        await handle_user_timeline_leave(db, nc, timeline_watch_session)
    except ValidationError as e:
        logging.error(f"Error validating timeline watch session: {e}")
        logging.error(f"Could not handle user timeline leave for user {user_uuid}")


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

    await app.leave_room(watch_session.sid, get_room_name(group_uuid))
    group.users_count -= 1

    # users of the group
    group_users = await get_timeline_group_users(db, group_uuid)

    # if next to last user left the group, delete the group
    other_group_user = None
    if group.users_count <= 1:
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

    timeline_single_users = await get_timeline_single_users(db, watch_session.video_uuid)
    await app.emit(
        "timeline_single_users",
        TimelineSingleUsersResponse(root=timeline_single_users),
        room=get_room_name(watch_session.video_uuid),
    )

    timeline_groups = await get_timeline_groups(db, watch_session.video_uuid)
    await app.emit(
        "timeline_groups",
        TimelineGroupResponse(root=timeline_groups),
        room=get_room_name(watch_session.video_uuid),
    )

    timeline_current_group = await get_timeline_group_users_data(db, watch_session.video_uuid,
                                                                 group_uuid)
    if timeline_current_group:
        await app.emit(
            "timeline_current_group",
            TimelineCurrentGroupResponse(root=timeline_current_group),
            room=get_room_name(group_uuid)
        )

    # sent last for iOs compatibility
    await app.emit(
        "timeline_you_left_group",
        {"group_uuid": group_uuid},
        room=watch_session.sid
    )

    # to the other user if the group
    if other_group_user is not None:
        await app.emit(
            "timeline_you_left_group",
            {"group_uuid": group_uuid},
            room=other_group_user.sid
        )

    group_participants_uuids = []
    if group_users:
        for group_user in group_users:
            if group_user.get("user_uuid") != user_uuid:
                group_participants_uuids.append(group_user.get("user_uuid"))

    await publish_user_left_timeline_group(nc, user_uuid, group_uuid, group_participants_uuids)

    # if host left the group, change the host
    if group and (group.host_user_uuid == user_uuid):
        group_users = await get_timeline_group_users(db, group_uuid)
        if group_users:
            last_user_uuid = None

            for group_user in group_users:
                if group_user.get("user_uuid") != user_uuid:
                    last_user_uuid = group_user.get("user_uuid")
                    break

            group.host_user_uuid = last_user_uuid
            await upsert_timeline_group(db, group)


async def handle_user_timeline_leave(db: Database, nc: Client,
                                     timeline_watch_session: TimelineWatchSession):
    watch_session = TimelineWatchSession.model_validate(timeline_watch_session)

    await handle_user_timeline_group_leave(nc, db, watch_session)

    await delete_timeline_watch_session_by_user_uuid(db, watch_session.user_uuid)

    try:
        await app.leave_room(watch_session.sid, get_room_name(watch_session.video_uuid))
    except Exception as e:
        logging.error(f"Error leaving room: {e}")

    await publish_user_left_timeline(nc, watch_session.user_uuid, watch_session.video_uuid,
                                     watch_session.watch_time)

    timeline_single_users = await get_timeline_single_users(db, watch_session.video_uuid)
    await app.emit(
        "timeline_single_users",
        TimelineSingleUsersResponse(root=timeline_single_users),
        room=get_room_name(watch_session.video_uuid),
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
    Event `timeline_single_users` is emitted to everybody on the timeline:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineUserDataResponse`

    Event `timeline_server_timestamp` is emitted to the user:

    Data:

    .. code-block:: json

            {
                "timestamp": 1617000000
            }

    Event `timeline_chat_history` is emitted to the user:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineChatMessage`

    Event `timeline_groups` is emitted to the user:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineGroupDataResponse`

    Event `timeline_current_group` is emitted to the user (only if the user is in a group):

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineUserDataResponse`

    """
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    # delete the old view session
    await delete_timeline_watch_session_by_user_uuid(db, user_uuid)

    # publish that the user connected to the timeline
    await publish_user_connected_to_timeline(nc, user_uuid, data.video_uuid)

    watch_session = TimelineWatchSession(
        sid=sid,
        last_update_time=datetime.now(),
        # agora_id is a random 32-bit integer
        # this is needed because the client needs to identify the user in the agora stream
        # and the agora stream id is a 32-bit integer so we can't use the user_uuid
        agora_id=random.randint(0, 2 ** 32 - 1),
        watch_time=0,
        video_uuid=data.video_uuid,
        user_uuid=user_uuid,
        mic_enabled=False,
        avatar=session.avatar,
        avatar_thumbnail=session.avatar_thumbnail,
        username=session.username,
        first_name=session.first_name,
        last_name=session.last_name,
        bio=session.bio,
    )

    await publish_enable_fliji_mode(nc, user_uuid)

    await upsert_timeline_watch_session(db, watch_session)

    sio_room_identifier = get_room_name(data.video_uuid)

    # join socketio room
    await app.enter_room(sid, sio_room_identifier)

    await app.emit(
        "timeline_server_timestamp",
        {"timestamp": int(time.time())},
        room=sid,
    )

    chat_messages = await get_timeline_chat_messages_by_video_uuid(db, watch_session.video_uuid)
    # send the initial data to the user who just connected
    await app.emit(
        "timeline_chat_history",
        TimelineChatHistoryResponse(root=chat_messages),
        room=sid,
    )

    timeline_single_users = await get_timeline_single_users(db, watch_session.video_uuid)
    await app.emit(
        "timeline_single_users",
        TimelineSingleUsersResponse(root=timeline_single_users),
        room=get_room_name(watch_session.video_uuid),
    )

    timeline_groups = await get_timeline_groups(db, watch_session.video_uuid)
    await app.emit(
        "timeline_groups",
        TimelineGroupResponse(root=timeline_groups),
        room=sid,
    )

    timeline_current_group = await get_timeline_group_users_data(db, watch_session.video_uuid,
                                                                 watch_session.group_uuid)
    if timeline_current_group:
        await app.emit(
            "timeline_current_group",
            TimelineCurrentGroupResponse(root=timeline_current_group),
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

    Event `timeline_single_users` is emitted to everybody on the timeline:

    response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineUserDataResponse`

    Event `timeline_current_group` is emitted to everybody in the group:

    data is an array of:
    :py:class:`fliji_sockets.models.database.TimelineUserDataResponse`

    Event `timeline_groups` is emitted to everybody on the timeline:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineGroupDataResponse`

    Event `timeline_you_joined_group` is emitted to the host and the joining user:

    Data:

    .. code-block:: json

        {
            "group_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
            "timecode": 1500
        }

    """

    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    timeline_watch_session = await get_timeline_watch_session_by_user_uuid(db, session.user_uuid)
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
    host_watch_session.last_update_time = datetime.now()
    host_watch_session.group_uuid = group.group_uuid

    watch_session.last_update_time = datetime.now()
    watch_session.group_uuid = group.group_uuid

    await upsert_timeline_watch_session(db, watch_session)
    await upsert_timeline_watch_session(db, host_watch_session)

    # identifier for the room of the group
    sio_group_room = get_room_name(group.group_uuid)

    # join socketio room for the group
    await app.enter_room(sid, sio_group_room)
    await app.enter_room(host_watch_session.sid, sio_group_room)

    timeline_single_users = await get_timeline_single_users(db, watch_session.video_uuid)
    await app.emit(
        "timeline_single_users",
        TimelineSingleUsersResponse(root=timeline_single_users),
        room=get_room_name(watch_session.video_uuid),
    )

    timeline_groups = await get_timeline_groups(db, watch_session.video_uuid)
    await app.emit(
        "timeline_groups",
        TimelineGroupResponse(root=timeline_groups),
        room=get_room_name(watch_session.video_uuid),
    )

    timeline_current_group = await get_timeline_group_users_data(db, watch_session.video_uuid,
                                                                 group.group_uuid)
    await app.emit(
        "timeline_current_group",
        TimelineCurrentGroupResponse(root=timeline_current_group),
        room=sio_group_room
    )

    # sent last for iOs compatibility
    await app.emit(
        "timeline_you_joined_group",
        {
            "group_uuid": group.group_uuid,
            "timecode": host_watch_session.watch_time
        },
        room=host_watch_session.sid
    )

    await app.emit(
        "timeline_you_joined_group",
        {
            "group_uuid": group.group_uuid,
            "timecode": host_watch_session.watch_time
        },
        room=sid
    )

    await publish_user_joined_timeline_group(nc, session.user_uuid, group.group_uuid)


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
    Event `timeline_user_mic_state_changed` is emitted to everybody in the group:

    Data:

    .. code-block:: json

        {
            "user_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
            "mic_enabled": true
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

    group = get_timeline_group_by_uuid(db, watch_session.group_uuid)
    if group:
        watch_session.mic_enabled = data.mic_enabled
        await upsert_timeline_watch_session(db, watch_session)

        await app.emit(
            "timeline_user_mic_state_changed",
            {
                "user_uuid": user_uuid,
                "mic_enabled": data.mic_enabled,
            },
            room=get_room_name(watch_session.group_uuid),
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
    Event `timeline_unpause` is emitted to the users on the timeline IF the group was paused:

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
        watch_session.watch_time = data.timecode
        watch_session.on_pause = False
        await upsert_timeline_watch_session(db, watch_session)
        return

    group_data = await get_timeline_group_by_uuid(db, watch_session.group_uuid)
    group = None
    if group_data:
        group = TimelineGroup.model_validate(group_data)

    if group:
        if group.host_user_uuid != user_uuid:
            await app.send_error_message(sid,
                                         "You are not the host of the group." +
                                         " You can't send the timecode.")
            return

        group.watch_time = data.timecode

        if group.on_pause:
            group.on_pause = False

            await app.emit(
                "timeline_unpause",
                {
                    "timecode": data.timecode,
                    "server_timestamp": data.server_timestamp,
                    "group_uuid": watch_session.group_uuid,
                    "user_uuid": user_uuid,
                },
                room=get_room_name(watch_session.group_uuid),
            )

        await upsert_timeline_group(db, group)

        logging.info(f"Emitting event: timeline_update_timecode: {data.timecode}")


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

    Event `timeline_single_users` is emitted to everybody on the timeline:

    response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineUserDataResponse`

    Event `timeline_current_group` is emitted to everybody in the group:

    data is an array of:
    :py:class:`fliji_sockets.models.database.TimelineUserDataResponse`

    Event `timeline_groups` is emitted to everybody on the timeline:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineGroupDataResponse`

    Event `timeline_you_joined_group` is emitted to the user joining the group:

    Data:

    .. code-block:: json

        {
            "group_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
            "timecode": 1500
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

    # join socketio room
    await app.enter_room(sid, get_room_name(group.group_uuid))

    timeline_groups = await get_timeline_groups(db, watch_session.video_uuid)
    await app.emit(
        "timeline_groups",
        TimelineGroupResponse(root=timeline_groups),
        room=get_room_name(watch_session.video_uuid),
    )

    timeline_single_users = await get_timeline_single_users(db, watch_session.video_uuid)
    await app.emit(
        "timeline_single_users",
        TimelineSingleUsersResponse(root=timeline_single_users),
        room=get_room_name(watch_session.video_uuid),
    )

    timeline_current_group = await get_timeline_group_users_data(db, watch_session.video_uuid,
                                                                 watch_session.group_uuid)
    await app.emit(
        "timeline_current_group",
        TimelineCurrentGroupResponse(root=timeline_current_group),
        room=get_room_name(group.group_uuid)
    )

    # sent last for iOs compatibility
    await app.emit(
        "timeline_you_joined_group",
        {
            "group_uuid": group.group_uuid,
            "timecode": group.watch_time,
        },
        room=sid
    )

    await publish_user_joined_timeline_group(nc, user_uuid, group.group_uuid)


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

    Event `timeline_single_users` is emitted to everybody on the timeline:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineUserDataResponse`

    Event `timeline_groups` is emitted to the user:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineGroupDataResponse`

    Event `timeline_current_group` is emitted to the user (only if the user is in a group):

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineUserDataResponse`

    `timeline_you_left_group` is emitted to the user

    Data:

    .. code-block:: json

        {
            "group_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
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
    Event `timeline_single_users` is emitted to everybody on the timeline:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineUserDataResponse`

    If the user left the group as well, the following events are emitted:
    Event `timeline_groups` is emitted to the user:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineGroupDataResponse`

    Event `timeline_current_group` is emitted to the user (only if the user is in a group):

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineUserDataResponse`

    Event is emitted `timeline_you_left_group` to the user

    Data:

    .. code-block:: json

        {
            "group_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
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

    await handle_user_timeline_leave(db, nc, watch_session)


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


@app.event("timeline_set_video_ended")
async def timeline_set_video_ended(
        sid, data: TimelineSetVideoEndedRequest, db: Database = Depends(get_db),
):
    """
    Отметить, что видео закончилось.
    Используется одинаково для хоста группы и одиночного пользователя.

    Request:
    :py:class:`fliji_sockets.models.socket.SetVideoEndedRequest`

    Response
    Event `timeline_video_ended` is emitted to all the users on the timeline:

    Data:

    .. code-block:: json

            {
                "video_duration": 15
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
        watch_session.watch_time = data.video_duration
        watch_session.video_ended = True
        await upsert_timeline_watch_session(db, watch_session)

        sio_room = get_room_name(watch_session.video_uuid)

        await app.emit(
            "timeline_video_ended",
            {
                "video_duration": data.video_duration,
            },
            room=sio_room,
        )
        return

    group = await get_timeline_group_by_uuid(db, watch_session.group_uuid)
    group = TimelineGroup.model_validate(group)

    if group.host_user_uuid != user_uuid:
        await app.send_error_message(sid,
                                     "You are not the host of the group." +
                                     " You can't send the timecode.")
        return

    group.video_ended = True
    group.watch_time = data.video_duration

    await upsert_timeline_group(db, group)

    sio_room = get_room_name(watch_session.video_uuid)

    await app.emit(
        "timeline_video_ended",
        {
            "video_duration": data.video_duration,
        },
        room=sio_room,
    )


@app.event("timeline_get_status")
async def timeline_get_status(
        sid,
        db: Database = Depends(get_db),
):
    """
    Запросить статус таймлайна видео.
    Этот ивент отправляется глобально всем пользователям на таймлайне.

    Локально нужно держать таймер когда приходил последний статус.
    Если он не обновлялся больше 5 секунд, то отправляется запрос timeline_get_status.
    Если другой пользователь уже запросил статус, то при обработке статус
    таймер у других участников должен сбрасываться, чтобы не было слишком много запросов.


    Response
    Event `timeline_positions` is emitted to everybody globally:
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

    if timeline_watch_session is not None:
        watch_session = TimelineWatchSession.model_validate(timeline_watch_session)

        # emit the global status event
        timeline_status_data = await get_timeline_status(db, watch_session.video_uuid)
        await app.emit(
            "timeline_positions",
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

    Если пользователь в группе, то нужно сначала отправить ивент

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
        created_at=datetime.now(),
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

    # timeline groups and watch sessions
    delete_all_timeline_groups(database)
    delete_all_timeline_watch_sessions(database)
    # delete_all_timeline_chat_messages(database)


clear_data_on_startup()


def fill_mock_data():
    db = get_database()

    video_uuid = TEST_VIDEO_UUID
    group1_uuid = "0ebc493f-bf2c-46be-84f1-b22fcd1ff165"
    group2_uuid = "abdf521d-bf2c-46be-84f1-b22fcd1ff121"

    timeline_users = [
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=30 * 1000,
            video_uuid=video_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="onetwo",
            first_name="One",
            last_name="Two",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=50 * 1000,
            video_uuid=video_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="willsmith",
            first_name="Will",
            last_name="Smith",
            bio="bio",
            mic_enabled=False,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=10 * 1000,
            video_uuid=video_uuid,
            group_uuid=group2_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="jarjar",
            first_name="Jar Jar",
            last_name="Binks",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=10 * 1000,
            video_uuid=video_uuid,
            group_uuid=group2_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="obiwan",
            first_name="Obi-Wan",
            last_name="Kenobi",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=100 * 1000,
            video_uuid=video_uuid,
            group_uuid=group1_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="alice",
            first_name="Alice",
            last_name="Alice",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=100 * 1000,
            video_uuid=video_uuid,
            group_uuid=group1_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="JoHn",
            last_name="Muir",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=100 * 1000,
            video_uuid=video_uuid,
            group_uuid=group1_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="JoHn",
            last_name="Muir",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=100 * 1000,
            video_uuid=video_uuid,
            group_uuid=group1_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="JoHn",
            last_name="Muir",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=100 * 1000,
            video_uuid=video_uuid,
            group_uuid=group1_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="JoHn",
            last_name="Muir",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=100 * 1000,
            video_uuid=video_uuid,
            group_uuid=group1_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="JoHn",
            last_name="Muir",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=100 * 1000,
            video_uuid=video_uuid,
            group_uuid=group1_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="JoHn",
            last_name="Muir",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=100 * 1000,
            video_uuid=video_uuid,
            group_uuid=group1_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="JoHn",
            last_name="Muir",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=100 * 1000,
            video_uuid=video_uuid,
            group_uuid=group1_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="JoHn",
            last_name="Muir",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=100 * 1000,
            video_uuid=video_uuid,
            group_uuid=group1_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="JoHn",
            last_name="Muir",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=100 * 1000,
            video_uuid=video_uuid,
            group_uuid=group1_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="JoHn",
            last_name="Muir",
            bio="bio",
            mic_enabled=True,
        ),
        TimelineWatchSession(
            sid="sid",
            last_update_time=datetime.now(),
            agora_id=random.randint(0, 2 ** 32 - 1),
            watch_time=100 * 1000,
            video_uuid=video_uuid,
            group_uuid=group1_uuid,
            user_uuid=str(uuid.uuid4()),
            avatar="https://api.dicebear.com/avatars/avataaars/robot",
            avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
            username="username",
            first_name="JoHn",
            last_name="Muir",
            bio="bio",
            mic_enabled=True,
        ),
    ]
    group1 = TimelineGroup(
        group_uuid=group1_uuid,
        video_uuid=video_uuid,
        host_user_uuid=timeline_users[5].user_uuid,
        users_count=2,
    )

    group2 = TimelineGroup(
        group_uuid=group2_uuid,
        video_uuid=video_uuid,
        host_user_uuid=timeline_users[2].user_uuid,
        users_count=2,
    )

    db.timeline_groups.update_one(
        {"group_uuid": group1.group_uuid},
        {"$set": group1.model_dump(exclude_none=True)},
        upsert=True,
    )

    db.timeline_groups.update_one(
        {"group_uuid": group2.group_uuid},
        {"$set": group2.model_dump(exclude_none=True)},
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
            created_at=datetime.now(),
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
