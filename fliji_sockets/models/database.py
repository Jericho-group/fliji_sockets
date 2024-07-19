from datetime import datetime

from pydantic import Field

from fliji_sockets.models.base import PyObjectId, MyBaseModel
from fliji_sockets.models.enums import RoomUserRole


class ViewSession(MyBaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, validation_alias="_id")
    user_uuid: str
    sid: str
    video_uuid: str | None = None
    start_time: datetime | None = None
    current_watch_time: int | None = None
    last_update_time: datetime
    avatar: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    bio: str | None = None

    class Config:
        json_extra_schema = {
            "example": {
                "id": "1234567890",
                "user_uuid": "32d6b6e3-3f3e-4e3d-8f3e-3e3d3e3d3e3d",
                "sid": "1234567890",
                "video_uuid": "32d6b6e3-3f3e-4e3d-8f3e-3e3d3e3d3e3d",
                "start_time": "2021-08-01 12:00:00",
                "last_update_time": "2021-08-01 12:00:00",
            },
        }


class TimelineWatchSession(MyBaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, validation_alias="_id")
    user_uuid: str
    sid: str
    video_uuid: str | None = None
    group_uuid: str | None = None
    watch_time: int | None = None
    last_update_time: datetime
    avatar: str | None = None
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
    watch_time: int | None = None


class Room(MyBaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, validation_alias="_id")
    uuid: str
    author: str
    video_uuid: str
    user_limit: int | None = None
    permissions: int
    mode: str
    name: str
    chat_id: int
    created_at: datetime
    updated_at: datetime
    time_leave: datetime | None = None


class Chat(MyBaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, validation_alias="_id")


class ChatMessage(MyBaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, validation_alias="_id")
    chat_id: int
    room_uuid: str
    internal_chat_id: str
    user_uuid: str
    message: str


class RoomUser(MyBaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, validation_alias="_id")
    room_uuid: str
    user_uuid: str
    username: str
    first_name: str | None = None
    last_name: str | None = None
    avatar_url: str | None = None
    chat_id: int | None = None
    internal_chat_id: str | None = None
    mic: bool
    role: str
    right_to_speak: bool
    mic_ban: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_mongo(cls, data) -> "RoomUser":
        if "role" in data:
            data["role"] = RoomUserRole(data["role"])  # convert string to enum
        return cls(**data)
