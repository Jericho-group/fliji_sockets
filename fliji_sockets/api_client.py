import logging

from fliji_sockets.models.enums import RightToSpeakState
from fliji_sockets.settings import USER_SERVICE_URL, USER_SERVICE_API_KEY
import httpx


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
        self.base_url = USER_SERVICE_URL + "/sockets-api/v1"

    async def authenticate_user(self, token) -> dict or None:
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.get(
                    f"{self.base_url}/auth",
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