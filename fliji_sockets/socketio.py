import json
import logging

import socketio
import httpx
from datetime import datetime
from bson import json_util

from pydantic import ValidationError

from fliji_sockets.data_models import ViewSession, UpdateViewSessionRequest
from fliji_sockets.settings import USER_SERVICE_URL
from fliji_sockets.store import (
    get_db,
    upsert_view_session,
    delete_all_sessions,
    get_session_by_socket_id,
    get_view_sessions_for_video,
    serialize_doc,
)

# Set up global MongoDB connection
db = get_db()
sessions_collection = db.view_sessions

# Create a Socket.IO server
sio = socketio.AsyncServer(async_mode="asgi")
app = socketio.ASGIApp(sio)


def on_startup():
    # delete all leftover sessions on startup (in case of a crash)
    delete_all_sessions(db)


on_startup()


async def send_error_message(sid, message, body=None):
    """Send an error message to the client."""
    if body is None:
        body = {}

    await sio.emit("error", {"message": message, "body": body}, room=sid)


async def check_get_session(sid):
    """Checks if the user is authenticated. If not, disconnect the user. If yes, return the
    session."""
    session = await get_session_by_socket_id(db, sid)
    if not session or "user_uuid" not in session:
        await send_error_message(sid, "Unauthorized")
        await sio.disconnect(sid)
        return None
    return session


async def authenticate_user(token):
    """Mock function to simulate an HTTP request to the auth service."""
    async with httpx.AsyncClient() as httpx_client:
        try:
            response = await httpx_client.get(
                f"{USER_SERVICE_URL}/api/v1/users/my",
                headers={"Authorization": "Bearer " + token},
                timeout=5,
            )
            if response.status_code == 200:
                return response.json()  # Assuming JSON response with user_uuid
        except httpx.TimeoutException:
            logging.error("Authentication service timed out")
            return None

        return None


@sio.event
async def connect(sid, environ):
    pass


@sio.event
async def on_connect(sid, data):
    token = data.get("auth_token")
    user_info = await authenticate_user(token)
    if not user_info:
        await send_error_message(sid, "Could not authenticate user. Disconnecting.")
        await sio.disconnect(sid)
        logging.debug(f"user info not found for sid {sid}")
        return
    user_uuid = user_info.get("uuid")
    logging.debug(f"user_uuid found for sid {sid}")
    if not user_uuid:
        await send_error_message(sid, "Authentication service failed. Disconnecting.")
        await sio.disconnect(sid)
        # print("user_uuid not found")
        return
    logging.debug(f"authenticated user {user_uuid} for sid {sid}")

    session = ViewSession(
        sid=sid,
        user_uuid=user_uuid,
        last_update_time=datetime.now(),
        start_time=datetime.now(),
    )

    await upsert_view_session(db, session)
    logging.debug(f"session created for user {user_uuid} for sid {sid}")

    # Also store user_uuid in the user's session for later use
    await sio.save_session(sid, {"user_uuid": user_uuid})


@sio.event
async def update_watch_time(sid, data):
    logging.debug(f"received update watch time event for sid {sid}")
    now = datetime.now()

    session = await check_get_session(sid)
    if not session:
        logging.debug(f"session not found for sid {sid}")
        return

    logging.debug(f"session found for sid {sid} with user_uuid {session['user_uuid']}")

    # validate with pydantic
    try:
        update_view_session_request = UpdateViewSessionRequest.model_validate(data)
        logging.debug(f"validated request {update_view_session_request} for sid {sid}")
    except ValidationError as e:
        logging.debug(
            f"validation error for UpdateViewSessionRequest {e.errors()} for sid {sid}"
        )
        await send_error_message(sid, "Invalid request", e.errors())
        return

    # Assuming data contains the 'current_time' in the video being watched
    current_time = update_view_session_request.current_watch_time
    video_uuid = update_view_session_request.video_uuid
    try:
        view_session = ViewSession(
            sid=sid,
            last_update_time=now,
            current_watch_time=current_time,
            video_uuid=video_uuid,
            user_uuid=session["user_uuid"],
        )
    except ValidationError as e:
        logging.debug(f"validation error for ViewSession {e.errors()} for sid {sid}")
        await send_error_message(sid, "Invalid request", e.errors())
        return

    await upsert_view_session(db, view_session)


@sio.event
async def end_video_watch_session(sid):
    # delete the session from the database
    sessions_collection.delete_one({"sid": sid})


@sio.event
async def get_sessions_for_video(sid):
    session = await check_get_session(sid)
    if not session:
        return

    # Assuming data contains the 'video_uuid' for which the user wants to get the sessions
    video_uuid = session["video_uuid"]
    view_sessions = await get_view_sessions_for_video(db, video_uuid)

    await sio.emit(
        "current_video_view_sessions", serialize_doc(view_sessions), room=sid
    )


@sio.event
async def disconnect(sid):
    # This handles both manual disconnects and connection drops
    await end_video_watch_session(sid)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1")
