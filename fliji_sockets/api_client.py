import logging

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

    async def get_status(self, voice_uuid: str):
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.get(
                    f"{self.base_url}/socket/voice/status/{voice_uuid}",
                    headers={"X-API-KEY": self.api_key},
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
                f"Failed to get voice status with status code {response.status_code}"
            )
            logging.error(response.text)

            raise ApiException(f"Failed to get voice status for {voice_uuid}")

    async def toggle_voice_user_mic(
        self, voice_uuid: str, user_uuid: str, from_user_uuid: str
    ) -> dict or None:
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.post(
                    f"{self.base_url}/socket/voice/toggle-mic/{voice_uuid}",
                    data={"user_uuid": user_uuid, "from_user_uuid": from_user_uuid},
                    headers={"X-API-KEY": self.api_key},
                    timeout=5,
                )
                if response.status_code == 200:
                    return response.json()
            except httpx.TimeoutException:
                logging.error("Voice room service timed out")
                return None

            if response.status_code == 404:
                return None

            if response.status_code == 403:
                raise ForbiddenException()

            logging.error(
                f"Failed to toggle mic with status code {response.status_code}"
            )
            logging.error(response.text)

            raise ApiException(f"Failed to toggle mic in {voice_uuid}")

    async def transfer_room_ownership(
        self, voice_uuid: str, new_owner_uuid: str, from_user_uuid: str
    ) -> dict or None:
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.post(
                    f"{self.base_url}/socket/voice/transfer-owner/{voice_uuid}",
                    data={
                        "new_owner_uuid": new_owner_uuid,
                        "from_user_uuid": from_user_uuid,
                    },
                    headers={"X-API-KEY": self.api_key},
                    timeout=5,
                )
                if response.status_code == 200:
                    return response.json()
            except httpx.TimeoutException:
                logging.error("Voice room service timed out")
                return None

            if response.status_code == 404:
                return None

            if response.status_code == 403:
                raise ForbiddenException()

            logging.error(
                f"Failed to transfer room ownership with status code {response.status_code}"
            )
            logging.error(response.text)

            raise ApiException(f"Failed to transfer ownership in {voice_uuid}")

    async def confirm_room_ownership_transfer(
        self, voice_uuid: str, old_owner_uuid: str, from_user_uuid: str
    ) -> dict or None:
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.post(
                    f"{self.base_url}/socket/voice/confirm-ownership-transfer/{voice_uuid}",
                    data={
                        "old_owner_uuid": old_owner_uuid,
                        "from_user_uuid": from_user_uuid,
                    },
                    headers={"X-API-KEY": self.api_key},
                    timeout=5,
                )
                if response.status_code == 200:
                    return response.json()
            except httpx.TimeoutException:
                logging.error("Voice room service timed out")
                return None

            if response.status_code == 404:
                return None

            if response.status_code == 403:
                raise ForbiddenException()

            logging.error(
                f"Failed to confirm room ownership transfer with status code {response.status_code}"
            )
            logging.error(response.text)

            raise ApiException(f"Failed to confirm ownership transfer in {voice_uuid}")

    async def send_chat_message(
        self, voice_uuid: str, user_uuid: str, message: str
    ) -> dict or None:
        async with httpx.AsyncClient() as httpx_client:
            try:
                response = await httpx_client.post(
                    f"{self.base_url}/socket/voice/send-chat-message/{voice_uuid}",
                    data={"user_uuid": user_uuid, "message": message},
                    headers={"X-API-KEY": self.api_key},
                    timeout=5,
                )
                if response.status_code == 200:
                    return response.json()
            except httpx.TimeoutException:
                logging.error("Voice room service timed out")
                return None

            if response.status_code == 404:
                return None

            if response.status_code == 403:
                raise ForbiddenException()

            logging.error(
                f"Failed to send chat message with status code {response.status_code}"
            )
            logging.error(response.text)

            raise ApiException(f"Failed to send chat message in {voice_uuid}")
