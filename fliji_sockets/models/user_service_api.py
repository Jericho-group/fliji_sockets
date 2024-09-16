from fliji_sockets.models.base import MyBaseModel


class AuthUserResponse(MyBaseModel):
    uuid: str
    image: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    bio: str | None = None


class LoginResponse(MyBaseModel):
    token: str
    uuid: str


class UserDto(MyBaseModel):
    email: str
    password: str
    token: str
    uuid: str
