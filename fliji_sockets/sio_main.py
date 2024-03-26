import logging
from datetime import datetime

from pydantic import ValidationError

from fliji_sockets.api_client import FlijiApiService, ApiException, ForbiddenException
from fliji_sockets.helpers import get_room_name, configure_logging
from fliji_sockets.models.enums import RightToSpeakState
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
)
from fliji_sockets.models.base import UserSession
from fliji_sockets.models.database import ViewSession, OnlineUser
from fliji_sockets.dependencies import get_db, get_api_service
from fliji_sockets.models.user_service_api import (
    JoinRoomResponse,
    LeaveAllRoomsResponse,
    GetStatusResponse,
    ToggleVoiceUserMicResponse,
    TransferRoomOwnershipResponse,
    SendChatMessageResponse,
    HandleRightToSpeakResponse,
)
from fliji_sockets.socketio_application import SocketioApplication, Depends
from pymongo.database import Database

from fliji_sockets.store import (
    upsert_online_user,
    delete_view_session_by_socket_id,
    delete_online_user_by_socket_id,
    delete_view_session_by_user_uuid,
    delete_online_user_by_user_uuid,
    upsert_view_session,
    get_view_sessions_for_video,
    serialize_doc,
)

app = SocketioApplication()

configure_logging()


@app.event("startup")
async def startup(
    sid,
    data: OnConnectRequest,
    db: Database = Depends(get_db),
    api_service: FlijiApiService = Depends(get_api_service),
):
    logging.debug(f"validated request {data} for sid {sid}")

    user_info = await api_service.authenticate_user(data.auth_token)
    if not user_info:
        await app.send_fatal_error_message(sid, "Could not authenticate user.")
        return

    user_uuid = user_info.get("uuid")
    logging.debug(f"user_uuid found for sid {sid}")
    if not user_uuid:
        await app.send_fatal_error_message(sid, "Authentication service failed.")
        return

    logging.debug(f"authenticated user {user_uuid} for sid {sid}")

    # Set user online
    online_user = OnlineUser(
        user_uuid=user_uuid, last_online_at=datetime.now(), sid=sid
    )
    await upsert_online_user(db, online_user)

    # Also store user_uuid in the user's session for later use
    await app.save_session(sid, UserSession(user_uuid=user_uuid))


@app.event("disconnect")
async def disconnect(
    sid,
    db: Database = Depends(get_db),
    api_service: FlijiApiService = Depends(get_api_service),
):
    """This event is called when a socket disconnects.
    Handles both manual disconnection and automatic disconnection due to network issues.
    """
    user_session = await app.get_session(sid)

    # If the session data was corrupted somehow, delete whatever we can
    if not user_session:
        await delete_view_session_by_socket_id(db, sid)
        await delete_online_user_by_socket_id(db, sid)
        return

    await delete_view_session_by_user_uuid(db, user_session.user_uuid)
    await delete_online_user_by_user_uuid(db, user_session.user_uuid)

    # leave room
    user_uuid = user_session.user_uuid
    try:
        response = await api_service.leave_all_rooms(user_uuid)
        response_data = LeaveAllRoomsResponse.model_validate(response)
    except ApiException as e:
        logging.error(f"Error leaving voice rooms: {e}")
        return
    except ValidationError as e:
        await app.send_error_message(
            sid, f"Error leaving the voice rooms: couldn't validate response: {e}"
        )
        return

    for room_uuid in response_data.room_uuids:
        await app.emit(
            "leave_user",
            {"uuid": user_uuid},
            room=get_room_name(room_uuid),
            skip_sid=sid,
        )


@app.event("end_video_watch_session")
async def end_video_watch_session(sid, db: Database = Depends(get_db)):
    await delete_view_session_by_socket_id(db, sid)


@app.event("update_watch_time")
async def update_watch_time(
    sid, data: UpdateViewSessionRequest, db: Database = Depends(get_db)
):
    logging.debug(f"received update watch time event for sid {sid}")
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    view_session = ViewSession(
        sid=sid,
        last_update_time=datetime.now(),
        current_watch_time=data.current_watch_time,
        video_uuid=data.video_uuid,
        user_uuid=session.user_uuid,
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
    await app.emit(
        "current_video_view_sessions", serialize_doc(view_sessions), room=sid
    )


@app.event("join_room")
async def join_room(
    sid, data: JoinRoomRequest, api_service: FlijiApiService = Depends(get_api_service)
):
    # session = await app.get_session(sid)
    # if not session:
    #     await app.send_fatal_error_message(
    #         sid, "Unauthorized: could not find user_uuid in socketio session"
    #     )
    #     return
    # user_uuid = session.user_uuid
    user_uuid = "82c52b5f-6ff3-4c44-a000-a94952a85326"

    try:
        response_data = await api_service.join_room(data.room_uuid, user_uuid)
        response = JoinRoomResponse.model_validate(response_data)
    except ApiException as e:
        await app.send_error_message(sid, f"Error joining the voice room: {e}")
        return
    except ValidationError as e:
        await app.send_error_message(
            sid, f"Error joining the voice room: couldn't validate response: {e}"
        )
        return

    if not response:
        await app.send_error_message(sid, f"Voice with uuid {data.room_uuid} not found")
        return

    # join socketio room
    app.enter_room(sid, get_room_name(data.room_uuid))

    # emit the event to all the participants in the room about the new user
    await app.emit(
        "new_user",
        {
            "uuid": user_uuid,
            "status": "online",
            "mic": response.mic,
            "role": response.role,
        },
        room=get_room_name(data.room_uuid),
        skip_sid=sid,
    )


@app.event("leave_room")
async def leave_room(sid, api_service: FlijiApiService = Depends(get_api_service)):
    user_session = await app.get_session(sid)
    if not user_session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = user_session.user_uuid

    try:
        response = await api_service.leave_all_rooms(user_uuid)
        response_data = LeaveAllRoomsResponse.model_validate(response)
    except ApiException as e:
        logging.error(f"Error leaving voice rooms: {e}")
        return
    except ValidationError as e:
        await app.send_error_message(
            sid, f"Error leaving the voice rooms: couldn't validate response: {e}"
        )
        return

    for room_uuid in response_data.room_uuids:
        app.leave_room(sid, get_room_name(room_uuid))
        await app.emit(
            "leave_user",
            {"uuid": user_uuid},
            room=get_room_name(room_uuid),
            skip_sid=sid,
        )


@app.event("video_play")
async def video_play(sid, data: RoomActionRequest):
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await app.emit("video_play", data, room=get_room_name(RoomActionRequest.room_uuid))


@app.event("video_pause")
async def video_play(sid, data: RoomActionRequest):
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await app.emit("video_pause", data, room=get_room_name(RoomActionRequest.room_uuid))


@app.event("video_timecode")
async def video_timecode(sid, data: RoomActionRequest):
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    await app.emit(
        "video_timecode",
        data,
        room=get_room_name(RoomActionRequest.room_uuid),
        skip_sid=sid,
    )


@app.event("current_duration")
async def current_duration(sid, data: RoomActionRequest):
    await app.emit(
        "current_duration",
        data,
        room=get_room_name(RoomActionRequest.room_uuid),
        skip_sid=sid,
    )


@app.event("get_status")
async def get_status(
    sid,
    data: RoomActionRequest,
    api_service: FlijiApiService = Depends(get_api_service),
):
    user_session = await app.get_session(sid)
    if not user_session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return

    try:
        response_data = await api_service.get_status(data.room_uuid)
        response = GetStatusResponse.model_validate({"users": response_data})
    except ApiException as e:
        await app.send_error_message(sid, f"Error getting the voice status: {e}")
        return
    except ValidationError as e:
        await app.send_error_message(
            sid, f"Error getting the voice status: couldn't validate response: {e}"
        )
        return

    if not response:
        await app.send_error_message(sid, f"Voice with uuid {data.room_uuid} not found")
        return

    await app.emit("status", response.model_dump(), room=sid)


@app.event("toggle_user_mic")
async def toggle_user_mic(
    sid,
    data: ToggleVoiceUserMicRequest,
    api_service: FlijiApiService = Depends(get_api_service),
):
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    try:
        response_data = await api_service.toggle_voice_user_mic(
            data.room_uuid, data.user_uuid, from_user_uuid=user_uuid
        )
        response = ToggleVoiceUserMicResponse.model_validate(response_data)
    except ApiException as e:
        await app.send_error_message(sid, f"Error toggling the user mic: {e}")
        return
    except ForbiddenException as e:
        await app.send_error_message(sid, f"Error toggling the user mic: {e}")
        return
    except ValidationError as e:
        await app.send_error_message(
            sid, f"Error toggling the user mic: couldn't validate response: {e}"
        )
        return

    if not response:
        await app.send_error_message(
            sid,
            f"Voice with uuid {data.room_uuid} or user with uuid {data.user_uuid} not found",
        )
        return

    await app.emit(
        "mic_user",
        response.model_dump(),
        room=get_room_name(data.room_uuid),
    )


@app.event("transfer_room_ownership")
async def transfer_room_ownership(
    sid,
    data: TransferRoomOwnershipRequest,
    api_service: FlijiApiService = Depends(get_api_service),
):
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    try:
        response_data = await api_service.transfer_room_ownership(
            data.room_uuid, new_owner_uuid=data.new_owner_uuid, from_user_uuid=user_uuid
        )
        response = TransferRoomOwnershipResponse.model_validate(response_data)
    except ApiException as e:
        await app.send_error_message(sid, f"Error transferring room ownership: {e}")
        return
    except ValidationError as e:
        await app.send_error_message(
            sid, f"Error transferring room ownership: couldn't validate response: {e}"
        )
        return

    if not response:
        await app.send_error_message(sid, f"Voice with uuid {data.room_uuid} not found")
        return

    await app.emit(
        "role_updated",
        response.model_dump(),
        room=get_room_name(data.room_uuid),
    )


@app.event("confirm_room_ownership_transfer")
async def confirm_room_ownership_transfer(
    sid,
    data: ConfirmRoomOwnershipTransferRequest,
    api_service: FlijiApiService = Depends(get_api_service),
):
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    try:
        response_data = await api_service.confirm_room_ownership_transfer(
            data.room_uuid, old_owner_uuid=data.old_owner_uuid, from_user_uuid=user_uuid
        )
        response = TransferRoomOwnershipResponse.model_validate(response_data)
    except ApiException as e:
        await app.send_error_message(
            sid, f"Error confirming room ownership transfer: {e}"
        )
        return
    except ValidationError as e:
        await app.send_error_message(
            sid,
            f"Error confirming room ownership transfer: couldn't validate response: {e}",
        )
        return

    if not response:
        await app.send_error_message(sid, f"Voice with uuid {data.room_uuid} not found")
        return

    await app.emit(
        "role_updated",
        response.model_dump(),
        room=get_room_name(data.room_uuid),
    )


@app.event("send_chat_message")
async def send_chat_message(
    sid,
    data: SendChatMessageRequest,
    api_service: FlijiApiService = Depends(get_api_service),
):
    session = await app.get_session(sid)
    if not session:
        await app.send_fatal_error_message(
            sid, "Unauthorized: could not find user_uuid in socketio session"
        )
        return
    user_uuid = session.user_uuid

    try:
        response_data = await api_service.send_chat_message(
            data.room_uuid, user_uuid=user_uuid, message=data.message
        )
        response = SendChatMessageResponse.model_validate(response_data)
    except ApiException as e:
        await app.send_error_message(sid, f"Error sending chat message: {e}")
        return
    except ValidationError as e:
        await app.send_error_message(
            sid, f"Error sending chat message: couldn't validate response: {e}"
        )
        return

    if not response:
        await app.send_error_message(sid, f"Voice with uuid {data.room_uuid} not found")
        return

    await app.emit(
        "chat_message",
        response.model_dump(),
        room=get_room_name(data.room_uuid),
    )


@app.event("request_right_to_speak")
async def request_right_to_speak(sid):
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
        room=get_room_name(RoomActionRequest.room_uuid),
        skip_sid=sid,
    )


@app.event("handle_right_to_speak")
async def handle_right_to_speak(
    sid,
    data: HandleRightToSpeakRequest,
    api_service: FlijiApiService = Depends(get_api_service),
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

    try:
        response_data = await api_service.handle_right_to_speak(
            data.room_uuid,
            from_user_uuid=user_uuid,
            user_uuid=data.user_uuid,
            right_to_speak=right_to_speak,
        )
        response = HandleRightToSpeakResponse.model_validate(response_data)

    except ApiException as e:
        await app.send_error_message(sid, f"Error handling right to speak: {e}")
        return
    except ForbiddenException as e:
        await app.send_error_message(sid, f"Error handling right to speak: {e}")
        return
    except ValidationError as e:
        await app.send_error_message(
            sid, f"Error handling right to speak: couldn't validate response: {e}"
        )
        return

    if not response:
        await app.send_error_message(
            sid,
            f"Voice with uuid {data.room_uuid} or user with uuid {data.user_uuid} not found",
        )
        return

    await app.emit(
        "right_to_speak_updated",
        response.model_dump(),
        room=get_room_name(data.room_uuid),
    )


# Expose the sio_app for Uvicorn to run
sio_asgi_app = app.get_asgi_app()
