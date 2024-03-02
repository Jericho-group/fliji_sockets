from datetime import datetime
from typing import Optional

from bson import ObjectId
from pydantic import BaseModel, Field, ValidationInfo


class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v, info: ValidationInfo):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid objectid")
        return ObjectId(v)

    @classmethod
    def __get_pydantic_json_schema__(cls, field_schema):
        field_schema.update(type="string")
        return field_schema


class MyBaseModel(BaseModel):
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}


class UpdateViewSessionRequest(MyBaseModel):
    video_uuid: str
    current_watch_time: int


class MostWatchedVideosResponse(MyBaseModel):
    # loads from _id to video_uuid
    video_uuid: str
    watching_count: int

    class Config:
        # import by alias
        allow_population_by_field_name = True
        json_extra_schema = {
            "example": {
                "video_uuid": "32d6b6e3-3f3e-4e3d-8f3e-3e3d3e3d3e3d",
                "watch_count": 100,
            },
        }


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
