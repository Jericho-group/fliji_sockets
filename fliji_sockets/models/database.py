from datetime import datetime
from typing import Optional

from pydantic import Field

from fliji_sockets.models.base import PyObjectId, MyBaseModel


class ViewSession(MyBaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, validation_alias="_id")
    user_uuid: str
    sid: str
    video_uuid: Optional[str] = None
    start_time: Optional[datetime] = None
    current_watch_time: Optional[int] = None
    last_update_time: datetime

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


class OnlineUser(MyBaseModel):
    user_uuid: str
    last_online_at: datetime
    sid: str

    class Config:
        json_extra_schema = {
            "example": {
                "user_uuid": "32d6b6e3-3f3e-4e3d-8f3e-3e3d3e3d3e3d",
                "last_online_at": "2021-08-01 12:00:00",
                "sid": "1234567890",
            },
        }
