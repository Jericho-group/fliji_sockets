import logging

from fliji_sockets.settings import USER_SERVICE_URL, USER_SERVICE_API_KEY
import httpx


class ApiException(Exception):
    pass


class FlijiApiService:
    """
    A class to interact with the backend API. Uses httpx to make requests to the API.
    """

    def __init__(self):
        self.api_key = USER_SERVICE_API_KEY
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

    async def join_room(self, voice_uuid: str, user_uuid: str) -> dict or None:
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.post(
                    f"{self.base_url}/socket/voice/join/{voice_uuid}",
                    headers={"X-API-KEY": self.api_key},
                    data={"user_uuid": user_uuid},
                    timeout=5,
                )
                if response.status_code == 200:
                    return response.json()
            except httpx.TimeoutException:
                logging.error("Voice room service timed out")
                return None

            if response.status_code == 404:
                return None

            logging.error(
                f"Failed to get voice room with status code {response.status_code}"
            )
            logging.error(response.text)

            raise ApiException("Failed to get voice room")

    async def leave_all_rooms(self, user_uuid: str) -> dict or None:
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.post(
                    f"{self.base_url}/socket/voice/leave-all",
                    headers={"X-API-KEY": self.api_key},
                    data={"user_uuid": user_uuid},
                    timeout=5,
                )
                if response.status_code == 200:
                    return response.json()
            except httpx.TimeoutException:
                logging.error("Voice room service timed out")
                return None

            if response.status_code == 404:
                return None

            logging.error(
                f"Failed to leave voice rooms with status code {response.status_code}"
            )
            logging.error(response.text)

            raise ApiException("Failed to leave voice rooms")
