import logging
from datetime import datetime

from fliji_sockets.api_service import FlijiApiService
from fliji_sockets.data_models import (
    OnConnectRequest,
    OnlineUser,
    UserSession,
    UpdateViewSessionRequest,
    ViewSession,
    GetViewSessionsForVideoRequest,
)
from fliji_sockets.dependencies import get_db, get_api_service
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
async def disconnect(sid, db: Database = Depends(get_db)):
    """This event is called when a socket disconnects.
    Handles both manual disconnection and automatic disconnection due to network issues.
    """
    # Try to delete the session by user_uuid first, if it fails, delete by socket_id
    user_session = await app.get_session(sid)
    if user_session:
        await delete_view_session_by_user_uuid(db, user_session.user_uuid)
        await delete_online_user_by_user_uuid(db, user_session.user_uuid)
    else:
        await delete_view_session_by_socket_id(db, sid)
        await delete_online_user_by_socket_id(db, sid)


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

# Expose the sio_app for Uvicorn to run
sio_asgi_app = app.get_asgi_app()
