import logging
import uuid

from nats.aio.client import Client
from pymongo.database import Database

from fliji_sockets.core.socketio_application import SocketioApplication
from fliji_sockets.event_publisher import publish_user_left_timeline_group, \
    publish_user_left_timeline
from fliji_sockets.helpers import get_room_name
from fliji_sockets.models.database import TimelineGroup, TimelineWatchSession
from fliji_sockets.models.socket import TimelineGroupResponse, TimelineCurrentGroupResponse, \
    TimelineUserAvatarsResponse
from fliji_sockets.store import upsert_timeline_group, \
    upsert_timeline_watch_session, get_timeline_groups, get_timeline_group_users_data, \
    get_timeline_group_users, delete_timeline_group_by_uuid, \
    delete_timeline_watch_session_by_user_uuid, get_group_or_fail, get_video_watch_session_count


async def handle_user_joining_new_single_room(
        app: SocketioApplication,
        db: Database,
        watch_session: TimelineWatchSession):
    """
    This is a helper function to handle user joining the single room.
    The users are always in a group.
    When the user joins the timeline, a group is created for them.

    This function is for the cases when the users left the group and would be left without a group.
    In this case, we create a new group for them.

    If the user is already in a group, we do nothing.
    """
    # null checks
    if watch_session is None:
        return

    if watch_session.group_uuid is not None:
        return

    group = TimelineGroup(
        group_uuid=str(uuid.uuid4()),
        video_uuid=watch_session.video_uuid,
        host_user_uuid=watch_session.user_uuid,
        users_count=1,
        watch_time=0,
    )
    await upsert_timeline_group(db, group)
    watch_session.group_uuid = group.group_uuid
    await upsert_timeline_watch_session(db, watch_session)

    await app.enter_room(watch_session.sid, get_room_name(group.group_uuid))


async def handle_user_leaving_group(
        app: SocketioApplication,
        nc: Client, db: Database,
        watch_session: TimelineWatchSession,
):
    """
    A helper function to handle user leaving the timeline.

    Does nothing if either the user is not in a group or the group is not found.
    """
    user_uuid = watch_session.user_uuid
    # later we will clear the group_uuid from the watch session, so we need to save it here
    group_uuid = watch_session.group_uuid

    group = await get_group_or_fail(db, group_uuid)

    try:
        await app.leave_room(watch_session.sid, get_room_name(group_uuid))
    except Exception as e:
        logging.error(f"Error leaving sio for for user uuid:{user_uuid}: {e}")

    # users of the group
    group_users = list(await get_timeline_group_users(db, group_uuid))

    # if host left the group and there are still people, change the host
    if group.host_user_uuid == user_uuid:
        last_user_uuid = None
        # find the one with the
        for group_user in group_users:
            if group_user.get("user_uuid") != user_uuid:
                last_user_uuid = group_user.get("user_uuid")
                break

        group.host_user_uuid = last_user_uuid


    group.users_count -= 1
    # if the last user left the group, delete the group
    if len(group_users) <= 1:
        await delete_timeline_group_by_uuid(db, group_uuid)
    else:
        await upsert_timeline_group(db, group)

    # leave the room
    logging.debug(f"Leaving room {group_uuid} for user {user_uuid}")
    watch_session.group_uuid = None
    await upsert_timeline_watch_session(db, watch_session)

    # timeline_groups = await get_timeline_groups(db, watch_session.video_uuid)
    # await app.emit(
    #     "timeline_groups",
    #     TimelineGroupResponse(root=timeline_groups),
    #     room=get_room_name(watch_session.video_uuid),
    #     skip_sid=watch_session.sid
    # )

    # we sent an update to users left in the group if the group still exists
    timeline_current_group = await get_timeline_group_users_data(db, group_uuid)
    if timeline_current_group:
        await app.emit(
            "timeline_current_group",
            TimelineCurrentGroupResponse(root=timeline_current_group),
            room=get_room_name(group_uuid)
        )

    # sent last for iOs compatibility
    # when users is the only one in the group, we treat it as though the user left the group
    if group.users_count == 1:
        await app.emit(
            "timeline_you_left_group",
            {"group_uuid": group_uuid},
            room=watch_session.sid
        )

    # collects the users that the user had conversations with
    group_participants_uuids = []
    if group_users:
        for group_user in group_users:
            if group_user.get("user_uuid") != user_uuid:
                group_participants_uuids.append(group_user.get("user_uuid"))

    await publish_user_left_timeline_group(nc, user_uuid, group_uuid, group_participants_uuids)


async def handle_user_leaving_timeline(app: SocketioApplication, db: Database, nc: Client,
                                       timeline_watch_session: TimelineWatchSession):
    watch_session = TimelineWatchSession.model_validate(timeline_watch_session)
    logging.debug(f"Handling user leaving timeline: {watch_session}")

    watch_time = 0
    try:
        group = await get_group_or_fail(db, watch_session.group_uuid)
        watch_time = group.watch_time
    except Exception as e:
        logging.error(f"Error getting group: {e}")

    await handle_user_leaving_group(app, nc, db, watch_session)

    await delete_timeline_watch_session_by_user_uuid(db, watch_session.user_uuid)

    try:
        await app.leave_room(watch_session.sid, get_room_name(watch_session.video_uuid))
    except Exception as e:
        logging.error(f"Error leaving room: {e}")

    await publish_user_left_timeline(nc, watch_session.user_uuid, watch_session.video_uuid,
                                     watch_time)

    timeline_user_avatars = await get_timeline_group_users_data(db, watch_session.group_uuid)
    timeline_user_count = await get_video_watch_session_count(db, watch_session.video_uuid)
    await app.emit(
        "timeline_user_avatars",
        TimelineUserAvatarsResponse(users=timeline_user_avatars, count=timeline_user_count),
        room=get_room_name(watch_session.video_uuid),
    )
