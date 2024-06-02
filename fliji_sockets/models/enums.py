from enum import Enum


class RightToSpeakState(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class RoomPermissions(Enum):
    PUBLIC_ROOM = 0
    SUBSCRIBERS_ROOM = 1
    PRIVATE_ROOM = 2


class RoomMode(Enum):
    OPEN_MIC = 'open_mic'
    MIC_REQUEST = 'mic_request'


class RoomUserRole(Enum):
    USER = 'user'
    ADMIN = 'admin'
