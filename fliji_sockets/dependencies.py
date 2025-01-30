from nats.aio.client import Client
from pymongo.database import Database

from fliji_sockets.core.di import register_dependency, Context, container
from fliji_sockets.models.base import UserSioSession
from fliji_sockets.models.database import TimelineWatchSession, TimelineGroup
from fliji_sockets.store import get_watch_session_or_fail, get_group_or_fail


@register_dependency("db")
async def get_database() -> Database:
    from fliji_sockets.store import get_database
    return get_database()


@register_dependency("nats")
async def get_nats() -> Client:
    import nats
    from fliji_sockets.settings import NATS_TOKEN, NATS_HOST
    options = {"token": NATS_TOKEN}
    return await nats.connect(f"{NATS_HOST}", **options)


@register_dependency("sio_session")
async def get_sio_session(context: Context) -> UserSioSession:
    session = await context.app.get_session(context.sid)
    if not session:
        raise ValueError("No socket session found")

    return session


@register_dependency("timeline_session")
async def get_timeline_session(context: Context) -> TimelineWatchSession:
    """Dependency that provides current watch session"""
    db = await container.get("db")
    socket_session = await context.app.get_session(context.sid)
    watch_session = await get_watch_session_or_fail(db, socket_session.user_uuid)

    return watch_session


@register_dependency("timeline_group")
async def get_timeline_group(context: Context) -> TimelineGroup:
    """
    User must always be in a group.
    This function ensures that the internal state is correct.
    """
    db = await container.get("db")
    socket_session = await context.app.get_session(context.sid)
    watch_session = await get_watch_session_or_fail(db, socket_session.user_uuid)
    group_uuid = watch_session.group_uuid

    group = await get_group_or_fail(db, group_uuid)

    return group
