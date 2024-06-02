from fliji_sockets.models.base import MyBaseModel
from fliji_sockets.models.enums import RoomPermissions, RoomMode, RoomUserRole


class RoomCreatedEvent(MyBaseModel):
    uuid: str
    author: str
    video_uuid: str
    chat_id: str
    permissions: RoomPermissions
    mode: RoomMode
    name: str


class RoomUpdatedEvent(MyBaseModel):
    uuid: str
    author: str
    video_uuid: str
    chat_id: str
    permissions: RoomPermissions
    mode: RoomMode
    name: str


class RoomDeletedEvent(MyBaseModel):
    room_uuid: str


class UserJoinedEvent(MyBaseModel):
    room_uuid: str
    user_uuid: str
    username: str
    room_mode: RoomMode
    role: RoomUserRole
    first_name: str | None = None
    last_name: str | None = None
    avatar_url: str | None = None
