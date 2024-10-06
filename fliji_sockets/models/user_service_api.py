from fliji_sockets.models.base import MyBaseModel


class LoginResponse(MyBaseModel):
    access_token: str
    refresh_token: str
    uuid: str


class UserDto(MyBaseModel):
    email: str
    password: str
    token: str
    uuid: str
