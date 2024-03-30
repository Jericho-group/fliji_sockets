from bson import ObjectId
from pydantic import BaseModel
from pydantic_core.core_schema import ValidationInfo


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


class UserSession(MyBaseModel):
    user_uuid: str
    username: str | None = None
    avatar: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    bio: str | None = None
