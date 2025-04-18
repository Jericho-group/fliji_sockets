import random
from datetime import datetime

import jwt
from pydantic import ValidationError

from fliji_sockets.core.di import Depends
from fliji_sockets.event_publisher import \
    publish_user_disconnected, \
    publish_user_online, publish_user_connected_to_timeline, \
    publish_enable_fliji_mode
from fliji_sockets.events.common import *
from fliji_sockets.helpers import get_room_name
from fliji_sockets.models.base import UserSioSession
from fliji_sockets.models.database import TimelineWatchSession, TimelineGroup, \
    TimelineChatMessage
from fliji_sockets.models.socket import (
    TimelineConnectRequest,
    TimelineSendChatMessageRequest, TimelineUpdateTimecodeRequest, TimelineSetMicEnabled,
    TimelinePauseRequest, TimelineChatHistoryResponse,
    TimelineGroupResponse, TimelineCurrentGroupResponse, TimelineChangeGroupRequest,
    TimelineUserAvatars, TimelineReConnectRequest
)
from fliji_sockets.settings import JWT_SECRET
from fliji_sockets.store import (
    upsert_timeline_watch_session, delete_timeline_watch_session_by_user_uuid,
    get_timeline_watch_session_by_user_uuid, upsert_timeline_group,
    insert_timeline_chat_message,
    get_timeline_chat_messages_by_video_uuid, get_timeline_group_users_data,
    get_group_or_fail, get_watch_session_or_fail, get_timeline_user_avatars,
    get_video_watch_session_count, )


# async def connect(
#         sid,
#         app: SocketioApplication = Depends("app"),
#         environ=None,
#         nc: Client = Depends("nats"),
# ):
#     if environ is None or not isinstance(environ, dict) or environ.get("token") is None:
#         logging.info(f"Token not found for sid {sid}")
#         raise ConnectionRefusedError(
#             f"Token not found for sid {sid}"
#         )
#
#     token = environ.get("token")
#
#     try:
#         decoded = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
#     except jwt.exceptions.InvalidTokenError as e:
#         logging.info(
#             f"Could not decode token for sid {sid} with token {token[:10]}... Error: {e}")
#         raise ConnectionRefusedError(
#             f"Could not decode token for sid {sid} with token {token[:10]}... Error: {e}")
#
#     try:
#         user_session = UserSioSession(
#             user_uuid=decoded.get("user_uuid"),
#             username=decoded.get("username"),
#             first_name=decoded.get("first_name"),
#             last_name=decoded.get("last_name"),
#             bio=decoded.get("bio"),
#             avatar=decoded.get("avatar"),
#             avatar_thumbnail=decoded.get("avatar_thumbnail"),
#         )
#     except ValidationError as e:
#         logging.error(f"Error validating user session: {e}")
#         raise ConnectionRefusedError(f"Error validating user session: {e}")
#
#     try:
#         await app.save_session(
#             sid,
#             user_session
#         )
#     except Exception as e:
#         logging.error(f"Could not save session: {e}")
#
#     logging.info(f"User {user_session.user_uuid} authenticated successfully")
#
#     await publish_user_online(nc, user_session.user_uuid)
#     await publish_enable_fliji_mode(nc, user_session.user_uuid)

async def connect(
        sid,
        data,
        app: SocketioApplication = Depends("app"),
        nc: Client = Depends("nats"),
):
    # logging.info(f"ENVIRON {data}")
    query_string = data.get('QUERY_STRING', '')
    params = dict(q.split("=") for q in query_string.split("&") if "=" in q)
    token = params.get("token")

    if not token:
        logging.info(f"Token not found for sid {sid}")
        raise ConnectionRefusedError(f"Token not found for sid {sid}")

    logging.info(f"Received token: {token}")

    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
    except jwt.exceptions.InvalidTokenError as e:
        logging.info(
            f"Could not decode token for sid {sid} with token {token[:10]}... Error: {e}")
        raise ConnectionRefusedError(
            f"Could not decode token for sid {sid} with token {token[:10]}... Error: {e}")

    try:
        user_session = UserSioSession(
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
        raise ConnectionRefusedError(f"Error validating user session: {e}")

    try:
        await app.save_session(
            sid,
            user_session
        )
    except Exception as e:
        logging.error(f"Could not save session: {e}")

    logging.info(f"User {user_session.user_uuid} authenticated successfully")

    await publish_user_online(nc, user_session.user_uuid)
    await publish_enable_fliji_mode(nc, user_session.user_uuid)


async def ping(
        sid,
        app: SocketioApplication = Depends("app"),
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


async def disconnect(
        sid,
        reason = None,
        app: SocketioApplication = Depends("app"),
        db: Database = Depends("db"),
        nc: Client = Depends("nats"),
):
    """
    Этот ивент отвечает за отключение пользователя от сокета.

    Можно не вызывать вручную, так как он вызывается автоматически при отключении пользователя.
    """
    if reason:
        logging.info(f"User {sid} disconnected with reason: {reason}")

    user_session = await app.get_session(sid)

    if not user_session:
        logging.warning(f"On disconnect: user session not found for sid {sid}")
        return

    user_uuid = user_session.user_uuid
    await publish_user_disconnected(nc, user_uuid)

    timeline_watch_session_data = await get_timeline_watch_session_by_user_uuid(db, user_uuid)
    if not timeline_watch_session_data:
        return

    try:
        timeline_watch_session = TimelineWatchSession.model_validate(
            timeline_watch_session_data)
        await handle_user_leaving_timeline(app, db, nc, timeline_watch_session)
    except ValidationError as e:
        logging.error(
            f"Could not handle user timeline leave for user {user_uuid}. "
            f"Error validating timeline watch session: {e}")


async def timeline_connect(
        sid,
        data: TimelineConnectRequest,
        app: SocketioApplication = Depends("app"),
        nc: Client = Depends("nats"),
        db: Database = Depends("db"),
        session: UserSioSession = Depends("sio_session"),
):
    """
    Подключение к таймлайну видео.
    После подключения пользователь получает статус таймлайна и историю чата.
    Только после этого ивента можно вызывать остальные timeline_* ивенты.

    Request:
    :py:class:`fliji_sockets.models.socket.TimelineConnectRequest`

    Event `timeline_chat_history` is emitted to the user:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineChatMessage`

    Event `timeline_groups` is emitted to the user:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineGroupDataResponse`

    Event `timeline_user_avatars` is emitted to the user
    (or to everybody on the timeline if there were less than 6 users):
    The data is an array of (max 6 elements):

    Response is:
    :py:class:`fliji_sockets.models.socket.TimelineUserAvatarsResponse`

    """
    user_uuid = session.user_uuid

    # delete the old view session
    await delete_timeline_watch_session_by_user_uuid(db, user_uuid)

    # publish that the user connected to the timeline
    await publish_user_connected_to_timeline(nc, user_uuid, data.video_uuid)
    # This is left as legacy, on mobile there's no fliji mode
    # and the default behaviour is as if fliji mode is enabled
    # TODO: remove fliji mode
    await publish_enable_fliji_mode(nc, user_uuid)

    # create a single group on the timeline for the user
    group = TimelineGroup(
        group_uuid=str(uuid.uuid4()),
        video_uuid=data.video_uuid,
        host_user_uuid=user_uuid,
        users_count=1,
        watch_time=0
    )
    await upsert_timeline_group(db, group)

    watch_session = TimelineWatchSession(
        sid=sid,
        last_update_time=datetime.now(),
        created_at=datetime.now(),
        # agora_id is a random 32-bit integer
        # this is needed because the client needs to identify the user in the agora stream
        # and the agora stream id is a 32-bit integer so we can't use the user_uuid
        agora_id=random.randint(0, 2 ** 32 - 1),
        video_uuid=data.video_uuid,
        group_uuid=group.group_uuid,
        user_uuid=user_uuid,
        mic_enabled=False,
        avatar=session.avatar,
        avatar_thumbnail=session.avatar_thumbnail,
        username=session.username,
        first_name=session.first_name,
        last_name=session.last_name,
        bio=session.bio,
    )
    await upsert_timeline_watch_session(db, watch_session)

    sio_video_room_identifier = get_room_name(data.video_uuid)
    sio_group_room_identifier = get_room_name(group.group_uuid)

    # join socketio rooms
    await app.enter_room(sid, sio_video_room_identifier)
    await app.enter_room(sid, sio_group_room_identifier)

    # send the initial data to the user who just connected
    chat_messages = await get_timeline_chat_messages_by_video_uuid(db, watch_session.video_uuid)
    await app.emit(
        "timeline_chat_history",
        TimelineChatHistoryResponse(root=chat_messages),
        room=sid,
    )

    timeline_groups = await get_timeline_groups(db, watch_session.video_uuid)
    await app.emit(
        "timeline_groups",
        TimelineGroupResponse(root=timeline_groups),
        room=get_room_name(watch_session.video_uuid),
    )

    timeline_user_avatars = await get_timeline_user_avatars(db, watch_session.video_uuid)
    timeline_user_count = await get_video_watch_session_count(db, watch_session.video_uuid)

    if timeline_user_count < 6:
        room = get_room_name(watch_session.video_uuid)
    else:
        room = sid

    await app.emit(
        "timeline_user_avatars",
        {
            "users": TimelineUserAvatars(root=timeline_user_avatars).model_dump(),
            "count": timeline_user_count,
        },
        room=room,
    )

    # We don't send the current group to the user,
    # so that the app wouldn't render the current group with one user
    # but the global group list of the timeline
    # This code is left here just for explanation
    # timeline_current_group = await get_timeline_group_users_data(db, watch_session.group_uuid)
    # if timeline_current_group:
    #     await app.emit(
    #         "timeline_current_group",
    #         TimelineCurrentGroupResponse(root=timeline_current_group),
    #         room=sid,
    #     )


async def timeline_set_mic_enabled(
        data: TimelineSetMicEnabled,
        app: SocketioApplication = Depends("app"),
        db: Database = Depends("db"),
        watch_session: TimelineWatchSession = Depends("timeline_session"),
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
    watch_session.mic_enabled = data.mic_enabled
    await upsert_timeline_watch_session(db, watch_session)

    await app.emit(
        "timeline_user_mic_state_changed",
        {
            "user_uuid": watch_session.user_uuid,
            "mic_enabled": data.mic_enabled,
        },
        room=get_room_name(watch_session.group_uuid),
    )


async def timeline_update_timecode(
        sid,
        data: TimelineUpdateTimecodeRequest,
        app: SocketioApplication = Depends("app"),
        db: Database = Depends("db"),
        session: UserSioSession = Depends("sio_session"),
        group: TimelineGroup = Depends("timeline_group"),
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

    Event `timeline_timecode` is emitted to the users on the timeline:

    Data:

    .. code-block:: json

        {
            "timecode": 15,
            "group_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
            "user_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
        }
    """
    user_uuid = session.user_uuid

    if group.host_user_uuid != user_uuid:
        await app.send_error_message(sid,
                                     "You are not the host of the group." +
                                     " You can't send the timecode.")
        return

    group.watch_time = data.timecode

    # if group.on_pause:
    #     group.on_pause = False
    #
    #     await app.emit(
    #         "timeline_unpause",
    #         {
    #             "timecode": data.timecode,
    #             "group_uuid": group.group_uuid,
    #             "user_uuid": user_uuid,
    #         },
    #         room=get_room_name(group.group_uuid),
    #     )

    # await app.emit(
    #     "timeline_timecode",
    #     {
    #         "timecode": data.timecode,
    #         "group_uuid": group.group_uuid,
    #         "user_uuid": user_uuid,
    #     },
    #     room=get_room_name(group.video_uuid),
    # )

    await upsert_timeline_group(db, group)

    groups = await get_timeline_groups(db, group.video_uuid)
    await app.emit(
        "timeline_groups",
        TimelineGroupResponse(root=groups),
        room=get_room_name(group.video_uuid),
    )


async def timeline_change_group(
        sid,
        data: TimelineChangeGroupRequest,
        app: SocketioApplication = Depends("app"),
        nc: Client = Depends("nats"),
        db: Database = Depends("db"),
        watch_session: TimelineWatchSession = Depends("timeline_session"),
        group: TimelineGroup = Depends("timeline_group"),
):
    """
    Сменить группу пользователя на таймлайне видео.

    Request:
    :py:class:`fliji_sockets.models.socket.TimelineChangeGroupRequest`

    Event `timeline_current_group` is emitted to everybody in the new group:

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

    If you left the group, the following events are also emitted:
    Event `timeline_you_left_group` is emitted to the user:

    Data:

    .. code-block:: json

        {
            "group_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
        }


    Event `timeline_current_group` is emitted to everybody in the old group:

    data is an array of:
    :py:class:`fliji_sockets.models.database.TimelineUserDataResponse`

    If you leave the group to join a new single room, the following events are emitted:
    Event `timeline_groups` is emitted to everybody on the timeline.
    NOTE, `timeline_current_group` is not emitted in this case for joining a single room.
    """

    # if we simply want to leave the group and join a single room
    if data.user_uuid is None and data.group_uuid is None:
        # if we are already in a single group - do nothing
        if (watch_session.user_uuid == group.host_user_uuid) and (group.users_count == 1):
            await app.send_error_message(sid, "You are already in a single group.")
            return

        await handle_user_leaving_group(app, nc, db, watch_session)
        await handle_user_joining_new_single_room(app, db, watch_session)

    # we have an option to join to a group by uuid of one of the participants
    if data.user_uuid is not None:
        try:
            target_user_watch_session = await get_watch_session_or_fail(db, data.user_uuid)
            group_uuid = target_user_watch_session.group_uuid
        except Exception as e:
            logging.warning(f"Couldn't get watch session for user with uuid {data.user_uuid}: {e}")
            await app.send_error_message(sid, f"Could not find user with uuid {data.user_uuid}.")
            return
    else:
        group_uuid = data.group_uuid

    # disable user mic when change or leave group
    watch_session.mic_enabled = False
    await upsert_timeline_watch_session(db, watch_session)

    # join an existing room
    if group_uuid:
        try:
            new_group = await get_group_or_fail(db, group_uuid)
        except Exception as e:
            await app.send_error_message(sid, "Could not get group.")
            logging.error(f"Error getting group: {e}")
            return

        # leave the old group. this sends events, too
        await handle_user_leaving_group(app, nc, db, watch_session)
        watch_session.group_uuid = new_group.group_uuid
        new_group.users_count += 1
        await upsert_timeline_watch_session(db, watch_session)
        await upsert_timeline_group(db, new_group)
        # join socketio room
        await app.enter_room(sid, get_room_name(new_group.group_uuid))

        timeline_current_group = await get_timeline_group_users_data(db, new_group.group_uuid)
        await app.emit(
            "timeline_current_group",
            TimelineCurrentGroupResponse(root=timeline_current_group),
            room=get_room_name(new_group.group_uuid)
        )

        # sent last for iOs compatibility
        await app.emit(
            "timeline_you_joined_group",
            {
                "group_uuid": new_group.group_uuid,
                "timecode": new_group.watch_time,
            },
            room=sid
        )

        # sent event to host user for start chat
        if len(timeline_current_group) == 2:
            host_user_sid = await get_watch_session_or_fail(db, new_group.host_user_uuid)
            await app.emit(
                "timeline_start_voice_chat",
                {"group_uuid": new_group.group_uuid},
                room=host_user_sid.sid
            )

    timeline_groups = await get_timeline_groups(db, watch_session.video_uuid)
    await app.emit(
        "timeline_groups",
        TimelineGroupResponse(root=timeline_groups),
        room=get_room_name(watch_session.video_uuid),
    )


async def timeline_leave(
        watch_session: TimelineWatchSession = Depends("timeline_session"),
        app: SocketioApplication = Depends("app"),
        nc: Client = Depends("nats"),
        db: Database = Depends("db"),
):
    """
    Отключиться от таймлайна видео.

    If the user left the group as well, the following events are emitted:
    Event `timeline_groups` is emitted to everybody on the timeline:

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineGroupDataResponse`

    Event `timeline_current_group` is emitted to users in the group if the user left the room

    Response is an array of:
    :py:class:`fliji_sockets.models.database.TimelineUserDataResponse`

    Event is emitted `timeline_you_left_group` to the user

    Data:

    .. code-block:: json

        {
            "group_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
        }

    """
    await handle_user_leaving_timeline(app, db, nc, watch_session)


async def timeline_pause(
        sid,
        data: TimelinePauseRequest,
        app: SocketioApplication = Depends("app"),
        db: Database = Depends("db"),
        session: UserSioSession = Depends("sio_session"),
        group: TimelineGroup = Depends("timeline_group"),
):
    """
    Поставить видео на паузу.
    Event `timeline_pause` is emitted to the users on the timeline:

    Data:

    .. code-block:: json

        {
            "timecode": 15,
            "group_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
            "user_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
        }
    """
    user_uuid = session.user_uuid

    if group.host_user_uuid != user_uuid:
        await app.send_error_message(sid, "You are not the host of the group.")
        return

    group.on_pause = True
    group.watch_time = data.timecode
    await upsert_timeline_group(db, group)

    sio_room_identifier = get_room_name(group.video_uuid)

    await app.emit(
        "timeline_pause",
        {
            "timecode": data.timecode,
            "group_uuid": group.group_uuid,
            "user_uuid": user_uuid,
        },
        room=sio_room_identifier,
    )


async def timeline_unpause(
        sid,
        data: TimelinePauseRequest,
        app: SocketioApplication = Depends("app"),
        db: Database = Depends("db"),
        session: UserSioSession = Depends("sio_session"),
        group: TimelineGroup = Depends("timeline_group"),
):
    """
    Снять видео с паузы.

    Может отправлять только хост группы.

    Event `timeline_unpause` is emitted to the users on the timeline:

    Data:

    .. code-block:: json

        {
            "timecode": 15,
            "group_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
            "user_uuid": "a3f4c5d6-7e8f-9g0h-1i2j-3k4l5m6n7o8p",
        }
    """
    user_uuid = session.user_uuid

    if group.host_user_uuid != user_uuid:
        await app.send_error_message(sid, "You are not the host of the group.")
        return

    group.on_pause = True
    group.watch_time = data.timecode
    await upsert_timeline_group(db, group)

    sio_room_identifier = get_room_name(group.video_uuid)

    await app.emit(
        "timeline_unpause",
        {
            "timecode": data.timecode,
            "group_uuid": group.group_uuid,
            "user_uuid": user_uuid,
        },
        room=sio_room_identifier,
    )


async def timeline_send_chat_message(
        data: TimelineSendChatMessageRequest,
        app: SocketioApplication = Depends("app"),
        db: Database = Depends("db"),
        watch_session: TimelineWatchSession = Depends("timeline_session"),
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
    chat_message = TimelineChatMessage(
        user_uuid=watch_session.user_uuid,
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


async def timeline_reconnect(
        sid,
        data: TimelineReConnectRequest,
        app: SocketioApplication = Depends("app"),
        nc: Client = Depends("nats"),
        db: Database = Depends("db"),
        session: UserSioSession = Depends("sio_session"),
):

    user_uuid = session.user_uuid

    # delete the old view session
    await delete_timeline_watch_session_by_user_uuid(db, user_uuid)

    # publish that the user connected to the timeline
    await publish_user_connected_to_timeline(nc, user_uuid, data.video_uuid)

    # create a single group on the timeline for the user
    group = TimelineGroup(
        group_uuid=str(uuid.uuid4()),
        video_uuid=data.video_uuid,
        host_user_uuid=user_uuid,
        users_count=1,
        watch_time=0
    )

    watch_session = TimelineWatchSession(
        sid=sid,
        last_update_time=datetime.now(),
        created_at=datetime.now(),
        agora_id=random.randint(0, 2 ** 32 - 1),
        video_uuid=data.video_uuid,
        group_uuid=group.group_uuid,
        user_uuid=user_uuid,
        mic_enabled=False,
        avatar=session.avatar,
        avatar_thumbnail=session.avatar_thumbnail,
        username=session.username,
        first_name=session.first_name,
        last_name=session.last_name,
        bio=session.bio,
    )

    try:
        old_group = await get_group_or_fail(db, data.group_uuid)
        watch_session.group_uuid = old_group.group_uuid
        group = old_group
        group.users_count += 1
    except Exception:
        pass

    await upsert_timeline_group(db, group)
    await upsert_timeline_watch_session(db, watch_session)

    sio_video_room_identifier = get_room_name(data.video_uuid)
    sio_group_room_identifier = get_room_name(group.group_uuid)

    # join socketio rooms
    await app.enter_room(sid, sio_video_room_identifier)
    await app.enter_room(sid, sio_group_room_identifier)

    timeline_current_group = await get_timeline_group_users_data(db, group.group_uuid)
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

    if len(timeline_current_group) == 2:
        host_user_sid = await get_watch_session_or_fail(db, group.host_user_uuid)
        await app.emit(
            "timeline_start_voice_chat",
            {"group_uuid": group.group_uuid},
            room=host_user_sid.sid
        )

    timeline_groups = await get_timeline_groups(db, watch_session.video_uuid)
    await app.emit(
        "timeline_groups",
        TimelineGroupResponse(root=timeline_groups),
        room=get_room_name(watch_session.video_uuid),
    )


def register_events(app: SocketioApplication) -> None:
    app.event("connect")(connect)
    app.event("disconnect")(disconnect)
    app.event("ping")(ping)
    app.event("timeline_connect")(timeline_connect)
    app.event("timeline_reconnect")(timeline_reconnect)
    app.event("timeline_set_mic_enabled")(timeline_set_mic_enabled)
    app.event("timeline_update_timecode")(timeline_update_timecode)
    app.event("timeline_change_group")(timeline_change_group)
    app.event("timeline_leave")(timeline_leave)
    app.event("timeline_pause")(timeline_pause)
    app.event("timeline_unpause")(timeline_unpause)
    app.event("timeline_send_chat_message")(timeline_send_chat_message)

