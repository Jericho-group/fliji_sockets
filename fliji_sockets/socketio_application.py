import inspect
import logging
from typing import Callable, Any

import socketio
import uvicorn

from pydantic import ValidationError

from pydantic import BaseModel

from fliji_sockets.models.base import UserSession
from fliji_sockets.settings import REDIS_CONNECTION_STRING


def Depends(dependency_callable: Callable):
    """A simple wrapper to mark a dependency for injection."""

    # Marking this as an async dependency
    async def async_dependency_wrapper():
        return await dependency_callable()

    return {"type": "dependency", "callable": async_dependency_wrapper}


class SocketioApplication:
    def __init__(self):
        mgr = socketio.AsyncRedisManager(REDIS_CONNECTION_STRING)
        self.sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*",
                                        client_manager=mgr,
                                        logger=True,
                                        engineio_logger=True,
                                        )
        self.sio_app = socketio.ASGIApp(self.sio)

    @staticmethod
    def get_remote_emitter() -> socketio.AsyncRedisManager:
        return socketio.AsyncRedisManager(REDIS_CONNECTION_STRING, write_only=True, logger=True)

    async def resolve_dependency(self, dep: dict[str, Any]):
        if dep["type"] == "dependency":
            # If it's marked as a dependency, call the associated callable
            return await dep["callable"]()
        return None

    def event(self, event_name: str):
        def decorator(func: Callable):
            async def wrapper(sid, data=None, *args, **kwargs):
                validation_error = None

                sig = inspect.signature(func)
                # Check if 'data' is in the function's parameters
                if "data" in sig.parameters:
                    # Include 'data' in initial binding
                    bound = sig.bind_partial(sid=sid, data=data)
                else:
                    # Exclude 'data' from initial binding
                    bound = sig.bind_partial(sid=sid)
                bound.apply_defaults()

                for name, value in bound.arguments.items():
                    param = sig.parameters.get(name)
                    if issubclass(param.annotation, BaseModel):
                        # Handle Pydantic model validation
                        try:
                            # Deserialize the data into the model if it's a string
                            if isinstance(data, str):
                                model_instance = param.annotation.model_validate_json(
                                    data
                                )
                            else:
                                model_instance = param.annotation.model_validate(data)

                            bound.arguments[name] = model_instance
                        except ValidationError as e:
                            await self.send_error_message(
                                sid, "Invalid request", e.errors()
                            )
                            validation_error = e
                            break
                    elif isinstance(value, dict) and value.get("type") == "dependency":
                        # Resolve the dependency
                        dependency_resolved = await self.resolve_dependency(value)
                        bound.arguments[name] = dependency_resolved

                if not validation_error:
                    await func(*bound.args, **bound.kwargs)

            self.sio.on(event_name, wrapper)
            return func

        return decorator

    def get_asgi_app(self) -> socketio.ASGIApp:
        return self.sio_app

    async def get_session(self, sid) -> UserSession | None:
        session_dict = await self.sio.get_session(sid)
        try:
            return UserSession.model_validate(session_dict)
        except ValidationError as e:
            logging.warning(
                f"Could not validate UserSession  {e.errors()} for sid {sid}"
                + f"Raw session: {session_dict}"
            )
            return None

    async def save_session(self, sid, session: UserSession) -> None:
        await self.sio.save_session(sid, session)

    async def emit(self, event, data, room=None, skip_sid=None) -> None:
        await self.sio.emit(event, data, room=room, skip_sid=skip_sid)

    async def send_error_message(self, sid, message, body=None) -> None:
        """Send an error message to the client."""
        if body is None:
            body = {}

        await self.sio.emit("err", {"message": message, "body": body}, room=sid)
        logging.debug(f"Emitting error message to {sid}: {message}")

    def enter_room(self, sid, room) -> None:
        self.sio.enter_room(sid, room)

    def leave_room(self, sid, room) -> None:
        self.sio.leave_room(sid, room)

    async def send_fatal_error_message(self, sid, message, body=None) -> None:
        """Send a fatal error message to the client."""
        if body is None:
            body = {}

        await self.sio.emit("fatal_error", {"message": message, "body": body}, room=sid)
        logging.debug(f"Emitting fatal error message to {sid}: {message}")

        # disconnect the user
        await self.sio.disconnect(sid)

    def run(self) -> None:
        uvicorn.run(self.sio_app, host="127.0.0.1", log_level="debug")
