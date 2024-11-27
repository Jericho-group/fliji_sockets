from typing import Any, Annotated

from bson import ObjectId
from pydantic import BaseModel, ConfigDict
from pydantic_core import core_schema


class ObjectIdAnnotation:
    @classmethod
    def __get_pydantic_core_schema__(
            cls, _source_type: Any, _handler: Any
    ) -> core_schema.CoreSchema:
        object_id_schema = core_schema.chain_schema(
            [
                core_schema.str_schema(),
                core_schema.no_info_plain_validator_function(cls.validate),
            ]
        )
        return core_schema.json_or_python_schema(
            json_schema=core_schema.str_schema(),
            python_schema=core_schema.union_schema(
                [core_schema.is_instance_schema(ObjectId), object_id_schema]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda x: str(x)
            ),
        )

    @classmethod
    def validate(cls, value):
        if not ObjectId.is_valid(value):
            raise ValueError("Invalid id")

        return ObjectId(value)


# Deprecated, use PydanticObjectId instead.
class ObjectIdField(ObjectId):
    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type: Any, _handler: Any):
        return ObjectIdAnnotation.__get_pydantic_core_schema__(_source_type, _handler)


PyObjectId = Annotated[ObjectId, ObjectIdAnnotation]


class MyBaseModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class UserSession(MyBaseModel):
    user_uuid: str
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    bio: str | None = None
    avatar: str | None = None
    avatar_thumbnail: str | None = None
