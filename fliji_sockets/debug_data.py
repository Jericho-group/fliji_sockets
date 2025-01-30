import random
import uuid
from datetime import datetime

from pymongo.database import Database

from fliji_sockets.models.database import TimelineWatchSession, TimelineChatMessage, TimelineGroup
from fliji_sockets.settings import TEST_VIDEO_UUID
from fliji_sockets.store import upsert_timeline_group, upsert_timeline_watch_session


async def _create_debug_user(group: TimelineGroup | None = None) -> (TimelineWatchSession, TimelineGroup):
    video_uuid = TEST_VIDEO_UUID

    rand = random.randint(0, 2 ** 32 - 1)

    user_uuid = str(uuid.uuid4())

    if group is None:
        # create new group
        group = TimelineGroup(
            group_uuid=str(uuid.uuid4()),
            video_uuid=video_uuid,
            host_user_uuid=user_uuid,
            users_count=1,
        )

    watch_session = TimelineWatchSession(
        sid="sid",
        created_at=datetime.now(),
        last_update_time=datetime.now(),
        agora_id=random.randint(0, 2 ** 32 - 1),
        video_uuid=video_uuid,
        group_uuid=group.group_uuid,
        user_uuid=user_uuid,
        avatar="https://api.dicebear.com/avatars/avataaars/robot",
        avatar_thumbnail="https://api.dicebear.com/avatars/avataaars/robot",
        username=f"onetwo{rand}",
        # random string
        first_name=f"One{rand}",
        last_name=f"Two{rand}",
        bio="bio",
        mic_enabled=True,
    )

    return watch_session, group


async def load_debug_data(db: Database):
    video_uuid = TEST_VIDEO_UUID

    # groups that will hold multiple users
    base_groups = [
        TimelineGroup(
            group_uuid=str(uuid.uuid4()),
            video_uuid=TEST_VIDEO_UUID,
            host_user_uuid=str(uuid.uuid4()),
            users_count=1,
        ),
        TimelineGroup(
            group_uuid=str(uuid.uuid4()),
            video_uuid=TEST_VIDEO_UUID,
            host_user_uuid=str(uuid.uuid4()),
            users_count=1,
        ),
    ]

    user_count = 7

    for count in range(user_count):
        group = None
        if random.random() > 0.3:
            group = random.choice(base_groups)

        watch_session, group = await _create_debug_user(group)

        await upsert_timeline_group(db, group)
        await upsert_timeline_watch_session(db, watch_session)


    # get all the timeline users
    timeline_users = list(db.timeline_watch_sessions.find({}))

    # update base groups to have proper values for host uuid
    for group in base_groups:
        group_users = [user for user in timeline_users if user.get("group_uuid") == group.group_uuid]
        group.host_user_uuid = group_users[0].get("user_uuid")
        group.users_count = len(group_users)
        await upsert_timeline_group(db, group)

    chat_messages = [
        "Hey everybody!",
        "How are you?",
        "I am good.",
        "How are you?",
        "I am good.",
    ]

    for chat_message in chat_messages:
        # get random user uuid from timeline_users
        user_uuid = random.choice(timeline_users).get("user_uuid")
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
