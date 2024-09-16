import logging

import httpx

from fliji_sockets.models.user_service_api import LoginResponse
from fliji_sockets.settings import USER_SERVICE_URL, USER_SERVICE_API_KEY


class ApiException(Exception):
    pass


class ForbiddenException(Exception):
    def __init__(self, message="You are not allowed to perform this action."):
        super().__init__(message)


class FlijiApiService:
    """
    A class to interact with the backend API. Uses httpx to make requests to the API.
    """

    def __init__(self):
        self.api_key = USER_SERVICE_API_KEY
        self.base_sockets_url = USER_SERVICE_URL + "/sockets-api/v1"
        self.base_main_url = USER_SERVICE_URL + "/api/v1"

    async def authenticate_user(self, token) -> dict or None:
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.get(
                    f"{self.base_sockets_url}/auth",
                    headers={
                        "Authorization": "Bearer " + token,
                        "X-API-KEY": self.api_key,
                    },
                    timeout=5,
                )
                if response.status_code == 200:
                    return response.json()  # Assuming JSON response with user_uuid
            except httpx.TimeoutException:
                logging.error("Authentication service timed out")
                return None

    async def login(self, email: str, password: str) -> LoginResponse or None:
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.post(
                    f"{self.base_main_url}/auth/login",
                    json={"email": email, "password": password},
                    timeout=5,
                )
                if response.status_code == 200:
                    response = response.json()
                    return LoginResponse(**response)
                else:  # Handle other status codes
                    # log the error
                    logging.error(f"Error logging in user: {response.status_code}. {response.text}")
                    raise ApiException()

            except httpx.TimeoutException:
                logging.error("Api service timed out")
                return None

    async def get_user_profile(self, token: str) -> dict or None:
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.get(
                    f"{self.base_main_url}/users/profile",
                    headers={"Authorization": "Bearer " + token, },
                    timeout=5,
                )
                if response.status_code == 200:
                    response = response.json()
                    return response
                else:  # Handle other status codes
                    # log the error
                    logging.error(
                        f"Error getting user profile: {response.status_code}. {response.text}")
                    raise ApiException()

            except httpx.TimeoutException:
                logging.error("Api service timed out")
                return None

    async def get_trending_videos(self, token: str) -> dict or None:
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.get(
                    f"{self.base_main_url}/video/trending",
                    headers={"Authorization": "Bearer " + token, },
                    timeout=5,
                )
                if response.status_code == 200:
                    response = response.json()
                    return response
                else:  # Handle other status codes
                    # log the error
                    logging.error(
                        f"Error getting trending videos: {response.status_code}. {response.text}")
                    raise ApiException()

            except httpx.TimeoutException:
                logging.error("Api service timed out")
                return None

    async def get_video(self, token: str, video_uuid: str) -> dict or None:
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.get(
                    f"{self.base_main_url}/video/{video_uuid}",
                    headers={"Authorization": "Bearer " + token, },
                    timeout=5,
                )
                if response.status_code == 200:
                    response = response.json()
                    return response
                else:  # Handle other status codes
                    # log the error
                    logging.error(
                        f"Error getting trending videos: {response.status_code}. {response.text}")
                    raise ApiException()

            except httpx.TimeoutException:
                logging.error("Api service timed out")
                return None
