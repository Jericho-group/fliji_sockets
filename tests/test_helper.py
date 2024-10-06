import asyncio

from tests.test_api_client import FlijiApiService
from fliji_sockets.models.user_service_api import UserDto, LoginResponse


class TestHelper:
    @staticmethod
    def get_user(user_number: int) -> UserDto:
        api_client = FlijiApiService()
        password = "password"
        email = f"test{user_number}@example.com"

        # run api_client.login synchronously
        login_response: LoginResponse = asyncio.run(api_client.login(email, password))

        user = UserDto(
            email=email,
            password=password,
            token=login_response.access_token,
            uuid=login_response.uuid,
        )

        return user


    @staticmethod
    def get_video(token: str) -> dict:
        api_client = FlijiApiService()

        # run api_client.login synchronously
        response = asyncio.run(api_client.get_trending_videos(token))

        return response[0]
