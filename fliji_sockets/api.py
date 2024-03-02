from typing import List

from fastapi import FastAPI, Depends

from fliji_sockets.data_models import ViewSession
from fliji_sockets.helpers import configure_logging
from fliji_sockets.store import (
    get_db,
    get_view_sessions_for_video,
    get_view_session_by_user_uuid,
    get_view_sessions_count_for_video,
    get_most_watched_videos,
    get_most_watched_videos_by_user_uuids,
)
from pymongo.database import Database

configure_logging()


def get_database() -> Database:
    return get_db()


app = FastAPI()


@app.get("/sessions/video/{video_uuid}")
async def list_view_sessions_for_video(
    video_uuid: str, db: Database = Depends(get_database)
) -> List[dict]:
    view_sessions = await get_view_sessions_for_video(db, video_uuid)
    return view_sessions


@app.get("/sessions/video/{video_uuid}/count")
async def get_view_sessions_count_for_video(
    video_uuid: str, db: Database = Depends(get_database)
) -> list[ViewSession]:
    count = await get_view_sessions_count_for_video(db, video_uuid)
    return count


@app.get("/sessions/user/{user_uuid}")
async def user_current_session(
    user_uuid: str, db: Database = Depends(get_database)
) -> ViewSession:
    view_session = await get_view_session_by_user_uuid(db, user_uuid)
    return view_session


@app.get("/videos/most-watching")
async def most_watched_videos(
    page: int = 1, page_size: int = 15, db: Database = Depends(get_database)
) -> dict:
    # pages use 0 based index so we subtract 1
    most_watched = await get_most_watched_videos(db, page=page - 1, page_size=page_size)
    return most_watched


@app.post("/videos/most-watching-by-users")
async def most_watched_videos_by_user_uuids(
    user_uuids: list[str],
    page: int = 1,
    page_size: int = 15,
    db: Database = Depends(get_database),
) -> dict:
    # pages use 0 based index so we subtract 1
    most_watched = await get_most_watched_videos_by_user_uuids(
        db, page=page - 1, page_size=page_size, user_uuids=user_uuids
    )
    return most_watched
