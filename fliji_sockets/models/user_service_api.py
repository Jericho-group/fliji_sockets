from fliji_sockets.models.base import MyBaseModel


class JoinRoomResponse(MyBaseModel):
    uuid: str
    status: str
    mic: bool
    role: str
    admin_socket_id: str | None = None


class LeaveAllRoomsResponse(MyBaseModel):
    room_uuids: list[str]


class GetStatusVoiceUser(MyBaseModel):
    username: str
    uuid: str
    status: str
    role: str
    mic: bool | None = None
    mic_ban: bool | None = None
    right_to_speak: bool | None = None


class GetStatusResponse(MyBaseModel):
    users: list[GetStatusVoiceUser]


class ToggleVoiceUserMicResponse(MyBaseModel):
    mic: bool
    right_to_speak: str | None = None
    user_uuid: str


class TransferRoomOwnershipResponse(MyBaseModel):
    user_uuid: str
    role: str


class ConfirmRoomOwnershipTransferResponse(MyBaseModel):
    user_uuid: str
    role: str

class SendChatMessageResponse(MyBaseModel):
    message: str
    user_uuid: str
    username: str
    time: str
