from fliji_sockets.models.base import MyBaseModel


class AuthUserResponse(MyBaseModel):
    uuid: str
    image: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    bio: str | None = None
