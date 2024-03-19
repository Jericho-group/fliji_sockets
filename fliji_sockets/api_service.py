import logging

from fliji_sockets.settings import USER_SERVICE_URL
import httpx


class FlijiApiService:
    """
    A class to interact with the backend API. Uses httpx to make requests to the API.
    """

    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = USER_SERVICE_URL + "/api/v1"

    async def authenticate_user(self, token) -> dict or None:
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.get(
                    f"{self.base_url}/users/my",
                    headers={"Authorization": "Bearer " + token},
                    timeout=5,
                )
                if response.status_code == 200:
                    return response.json()  # Assuming JSON response with user_uuid
            except httpx.TimeoutException:
                logging.error("Authentication service timed out")
                return None
