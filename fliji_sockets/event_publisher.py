import json

from nats.aio.client import Client


async def publish_user_online(nc: Client, user_uuid: str):
    payload = {
        "user_uuid": user_uuid,
    }

    await nc.publish("user.online", json.dumps(payload).encode())
    await nc.flush()


async def publish_enable_fliji_mode(nc: Client, user_uuid: str):
    payload = {
        "user_uuid": user_uuid,
    }

    await nc.publish("user.fliji_mode_enabled", json.dumps(payload).encode())
    await nc.flush()


async def publish_disable_fliji_mode(nc: Client, user_uuid: str):
    payload = {
        "user_uuid": user_uuid,
    }

    await nc.publish("user.fliji_mode_disabled", json.dumps(payload).encode())
    await nc.flush()


async def publish_user_offline(nc: Client, user_uuid: str):
    payload = {
        "user_uuid": user_uuid,
    }

    await nc.publish("user.offline", json.dumps(payload).encode())
    await nc.flush()


async def publish_user_disconnected(nc: Client, user_uuid: str):
    payload = {
        "user_uuid": user_uuid,
    }

    await nc.publish("user.disconnected", json.dumps(payload).encode())
    await nc.flush()


async def publish_user_connected_to_timeline(nc: Client, user_uuid: str, video_uuid: str):
    payload = {
        "user_uuid": user_uuid,
        "video_uuid": video_uuid,
    }

    await nc.publish("timeline.user_connected", json.dumps(payload).encode())
    await nc.flush()


async def publish_user_joined_timeline_group(nc: Client, user_uuid: str, group_uuid: str):
    payload = {
        "user_uuid": user_uuid,
        "group_uuid": group_uuid,
    }

    await nc.publish("timeline.user_joined_group", json.dumps(payload).encode())
    await nc.flush()


async def publish_user_left_timeline_group(nc: Client, user_uuid: str, group_uuid: str,
                                           group_participants_uuids: list[str]):
    payload = {
        "user_uuid": user_uuid,
        "group_uuid": group_uuid,
        "group_participants_uuids": group_participants_uuids,
    }

    await nc.publish("timeline.user_left_group", json.dumps(payload).encode())
    await nc.flush()


async def publish_user_left_timeline(nc: Client, user_uuid: str, video_uuid: str, watch_time: int):
    payload = {
        "user_uuid": user_uuid,
        "video_uuid": video_uuid,
        "watch_time": 0,
    }

    await nc.flush()
    await nc.publish("timeline.user_left", json.dumps(payload).encode())


async def publish_timeline_chat_message(nc: Client, video_uuid: str, author_uuid: str,
                                        message: str):
    payload = {
        "video_uuid": video_uuid,
        "author_uuid": author_uuid,
        "message": message,
    }

    await nc.publish("timeline.sent_message", json.dumps(payload).encode())
    await nc.flush()
