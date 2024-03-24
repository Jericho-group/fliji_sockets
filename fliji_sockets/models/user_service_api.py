from fliji_sockets.models.base import MyBaseModel


class JoinRoomResponse(MyBaseModel):
    uuid: str
    status: str
    mic: bool
    role: str
    admin_socket_id: str | None = None


class LeaveAllRoomsResponse(MyBaseModel):
    room_uuids: list[str]
