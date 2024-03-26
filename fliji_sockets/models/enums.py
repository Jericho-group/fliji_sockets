from enum import Enum


class RightToSpeakState(Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
