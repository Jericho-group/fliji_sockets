from fliji_sockets.models.base import MyBaseModel


class TimelineSetVideoEndedRequest(MyBaseModel):
    video_duration: int


class OnConnectRequest(MyBaseModel):
    auth_token: str



class TimelineConnectRequest(MyBaseModel):
    video_uuid: str


class TimelineJoinGroupRequest(MyBaseModel):
    group_uuid: str


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
    server_timestamp: int


class TimelineUpdateTimecodeRequest(MyBaseModel):
    timecode: int
    server_timestamp: int


class TimelineSetPauseStateRequest(MyBaseModel):
    timecode: int


class TimelineSendChatMessageRequest(MyBaseModel):
    message: str


class TimelineUserDataResponse(MyBaseModel):
    user_uuid: str
    username: str
    first_name: str | None = None
    last_name: str | None = None
    mic_enabled: bool | None = None
    on_pause: bool | None = None
    avatar: str | None = None
    avatar_thumbnail: str | None = None
    video_ended: bool | None = None
    bio: str | None = None
    watch_time: int | None = None


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
