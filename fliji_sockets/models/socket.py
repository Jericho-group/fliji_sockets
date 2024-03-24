from fliji_sockets.models.base import MyBaseModel


class UpdateViewSessionRequest(MyBaseModel):
    video_uuid: str
    current_watch_time: int


class GetViewSessionsForVideoRequest(MyBaseModel):
    video_uuid: str


class JoinRoomRequest(MyBaseModel):
    room_uuid: str


class OnConnectRequest(MyBaseModel):
    auth_token: str


class MostWatchedVideosResponse(MyBaseModel):
    # loads from _id to video_uuid
    video_uuid: str
    watching_count: int

    class Config:
        json_extra_schema = {
            "example": {
                "video_uuid": "32d6b6e3-3f3e-4e3d-8f3e-3e3d3e3d3e3d",
                "watch_count": 100,
            },
        }
