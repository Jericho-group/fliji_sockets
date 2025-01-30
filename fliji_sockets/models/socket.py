from datetime import datetime

from pydantic import RootModel

from fliji_sockets.models.base import MyBaseModel, PyObjectId


class TimelineSetVideoEndedRequest(MyBaseModel):
    video_duration: int


class OnConnectRequest(MyBaseModel):
    auth_token: str


class TimelineConnectRequest(MyBaseModel):
    video_uuid: str


class TimelineJoinGroupRequest(MyBaseModel):
    group_uuid: str


class TimelineChangeGroupRequest(MyBaseModel):
    group_uuid: str | None = None
    user_uuid: str | None = None


class TimelineJoinUserRequest(MyBaseModel):
    user_uuid: str
    video_uuid: str


class TimelineSetMicEnabled(MyBaseModel):
    mic_enabled: bool


class TimelineFetchChatMessages(MyBaseModel):
    mic_enabled: bool


class TimelineSendTimecodeToGroupRequest(MyBaseModel):
    group_uuid: str
    timecode: int


class TimelineUpdateTimecodeRequest(MyBaseModel):
    timecode: int


class TimelinePauseRequest(MyBaseModel):
    timecode: int


class TimelineSendChatMessageRequest(MyBaseModel):
    message: str


class TimelineChatMessageResponse(MyBaseModel):
    id: PyObjectId
    user_uuid: str
    message: str
    username: str
    user_avatar: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    created_at: datetime


class TimelineUserDataResponse(MyBaseModel):
    user_uuid: str
    username: str
    first_name: str | None = None
    agora_id: int | None = None
    last_name: str | None = None
    mic_enabled: bool | None = None
    on_pause: bool | None = None
    avatar: str | None = None
    avatar_thumbnail: str | None = None
    video_ended: bool | None = None
    bio: str | None = None
    watch_time: int | None = None
    is_host: bool | None = None


class TimelineGroupDataResponse(MyBaseModel):
    group_uuid: str
    host_user_uuid: str
    on_pause: bool | None = None
    users_count: int
    video_ended: bool | None = None
    watch_time: int | None = None
    users: list[TimelineUserDataResponse]


class TimelineStatusResponse(MyBaseModel):
    video_uuid: str
    groups: list[TimelineGroupDataResponse]
    users: list[TimelineUserDataResponse]


class TimelineUserAvatar(MyBaseModel):
    user_uuid: str
    avatar: str
    username: str
    first_name: str | None = None
    last_name: str | None = None
    mic_enabled: bool | None = None


class TimelineUserAvatars(RootModel, MyBaseModel):
    root: list[TimelineUserAvatar]


class TimelineUserAvatarsResponse(MyBaseModel):
    users: list[TimelineUserAvatar]
    count: int

class TimelineChatHistoryResponse(RootModel, MyBaseModel):
    root: list[TimelineChatMessageResponse]


class TimelineCurrentGroupResponse(RootModel, MyBaseModel):
    root: list[TimelineUserDataResponse]


class TimelineGroupResponse(RootModel, MyBaseModel):
    root: list[TimelineGroupDataResponse]
