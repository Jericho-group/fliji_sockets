from datetime import datetime

from pydantic import Field

from fliji_sockets.models.base import PyObjectId, MyBaseModel


class TimelineWatchSession(MyBaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, validation_alias="_id")
    user_uuid: str
    sid: str
    video_uuid: str | None = None
    agora_id: int | None = None
    group_uuid: str | None = None
    watch_time: int | None = None
    on_pause: bool | None = False
    video_ended: bool | None = False
    last_update_time: datetime
    mic_enabled: bool
    avatar: str | None = None
    avatar_thumbnail: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    bio: str | None = None


class TimelineGroup(MyBaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, validation_alias="_id")
    group_uuid: str
    video_uuid: str
    host_user_uuid: str
    users_count: int
    on_pause: bool | None = False
    video_ended: bool | None = False
    watch_time: int | None = None


class TimelineChatMessage(MyBaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, validation_alias="_id")
    video_uuid: str
    user_uuid: str
    username: str
    user_avatar: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    message: str
    created_at: datetime
