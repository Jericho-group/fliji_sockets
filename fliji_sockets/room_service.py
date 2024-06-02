from fliji_sockets.models.enums import RoomUserRole, RoomMode


class RoomService():
    def __init__(self):
        pass

    @staticmethod
    def get_right_to_speak(user_role: RoomUserRole, room_mode: RoomMode):
        if room_mode == RoomMode.OPEN_MIC:
            return True
        if user_role == RoomUserRole.ADMIN:
            return True

        return False
