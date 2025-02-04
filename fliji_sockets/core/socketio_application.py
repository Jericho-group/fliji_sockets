import inspect
import logging
from functools import wraps
from typing import Any, Optional

import socketio
import uvicorn
from pydantic import ValidationError, BaseModel

from fliji_sockets.core.di import container, Context
from fliji_sockets.models.base import UserSioSession
from fliji_sockets.settings import REDIS_CONNECTION_STRING, LOG_LEVEL, SIO_ADMIN_USERNAME, \
    SIO_ADMIN_PASSWORD, APP_ENV


class SocketioApplication:
    def __init__(self):
        if LOG_LEVEL == "DEBUG":
            enable_socketio_logger = True
        else:
            enable_socketio_logger = False

        mgr = socketio.AsyncRedisManager(REDIS_CONNECTION_STRING)
        self.sio = socketio.AsyncServer(
            async_mode="asgi",
            cors_allowed_origins="*",
            client_manager=mgr,
            logger=enable_socketio_logger,
            engineio_logger=enable_socketio_logger,
        )
        if APP_ENV != "prod":
            self.sio.instrument(
                auth={
                    'username': SIO_ADMIN_USERNAME,
                    'password': SIO_ADMIN_PASSWORD
                }
            )

        self.sio_app = socketio.ASGIApp(self.sio)

    @staticmethod
    def get_remote_emitter() -> socketio.AsyncRedisManager:
        return socketio.AsyncRedisManager(REDIS_CONNECTION_STRING, write_only=True)

    async def resolve_dependency(self, dep: dict[str, Any], sid: str) -> Any:
        """Enhanced dependency resolver that handles session dependencies"""
        if not dep or "type" not in dep or dep["type"] not in ["dependency"] or "key" not in dep:
            return None

        dependency_key = dep["key"]

        # if the dependency is "app"
        if dependency_key == "app":
            return self

        return await container.get(dependency_key, Context(sid=sid, app=self))

    def event(self, event_name: str):
        """Enhanced event decorator with built-in auth and validation."""

        def decorator(func: Any):
            # noinspection PyUnusedLocal
            @wraps(func)
            async def wrapper(sid: str, data=None, *args, **kwargs):
                logging.critical("#######")
                logging.critical("#######")
                logging.critical("#######")
                logging.critical(event_name)
                logging.critical(args)
                logging.critical(kwargs)
                logging.critical("#######")
                logging.critical("#######")
                dependency_error = None
                sig = inspect.signature(func)

                try:
                    # Get session early to validate authentication
                    if event_name != "connect" and event_name != "disconnect":
                        session = await self.get_session(sid)
                        if not session:
                            await self.send_fatal_error_message(
                                sid, "Unauthorized: could not find user_uuid in socketio session"
                            )
                            return

                    # we create a dict for the bound parameters
                    args_dict = {}
                    if "sid" in sig.parameters:
                        args_dict["sid"] = sid

                    if "data" in sig.parameters:
                        args_dict["data"] = data

                    bound = sig.bind_partial(**args_dict)
                    bound.apply_defaults()

                    # Process parameters
                    for name, value in bound.arguments.items():
                        param = sig.parameters.get(name)
                        if param and issubclass(param.annotation,
                                                BaseModel) and "type" not in value:
                            try:
                                if isinstance(data, str):
                                    model_instance = param.annotation.model_validate_json(data)
                                else:
                                    model_instance = param.annotation.model_validate(data)
                                bound.arguments[name] = model_instance
                            except ValidationError as e:
                                await self.send_error_message(
                                    sid,
                                    f"Invalid request for model: {param.annotation.__name__}",
                                    e.errors()
                                )
                                dependency_error = e
                                break
                        elif isinstance(value, dict) and value.get("type") == "dependency":
                            try:
                                dependency_resolved = await self.resolve_dependency(value, sid)
                                bound.arguments[name] = dependency_resolved
                            except Exception as e:
                                await self.send_error_message(
                                    sid,
                                    f"Error resolving dependency: {name}",
                                    str(e)
                                )
                                dependency_error = e
                                break

                    # Handle connect event environ
                    if event_name == "connect" and len(args) > 0:
                        bound.arguments["environ"] = args[0]

                    # Handle connect event reason
                    if event_name == "disconnect":
                        logging.critical("#######")
                        logging.critical("#######")
                        logging.critical("#######")
                        logging.critical(args)
                        logging.critical(kwargs)
                        logging.critical("#######")
                        logging.critical("#######")
                        # bound.arguments["reason"] = args[0]

                    if not dependency_error:
                        await func(*bound.args, **bound.kwargs)
                except Exception as e:
                    await self.send_fatal_error_message(
                        sid, f"An unexpected error occurred: {str(e)}"
                    )
                    raise

            self.sio.on(event_name, wrapper)
            return func

        return decorator

    def get_asgi_app(self) -> socketio.ASGIApp:
        return self.sio_app

    async def get_session(self, sid) -> Optional[UserSioSession]:
        try:
            session_dict = await self.sio.get_session(sid)
        except KeyError:
            return None

        try:
            return UserSioSession.model_validate(session_dict)
        except ValidationError as e:
            logging.warning(
                f"Could not validate UserSession {e.errors()} for sid {sid}"
                + f"Raw session: {session_dict}"
            )
            return None

    async def save_session(self, sid: str, session: UserSioSession) -> None:
        await self.sio.save_session(sid, session)

    async def emit(self, event: str, data: Any, room: Optional[str] = None,
                   skip_sid: Optional[str] = None) -> None:
        if isinstance(data, BaseModel):
            data = data.model_dump(mode='json')
        await self.sio.emit(event, data, room=room, skip_sid=skip_sid)

    async def send_error_message(self, sid: str, message: str, body: Any = None) -> None:
        if body is None:
            body = {}
        await self.sio.emit("err", {"message": message, "body": body}, room=sid)
        logging.debug(f"Emitting error message to {sid}: {message}")

    async def send_fatal_error_message(self, sid: str, message: str, body: Any = None) -> None:
        if body is None:
            body = {}
        await self.sio.emit("fatal_error", {"message": message, "body": body}, room=sid)
        logging.debug(f"Emitting fatal error message to {sid}: {message}")
        await self.sio.disconnect(sid)

    async def enter_room(self, sid: str, room: str) -> None:
        await self.sio.enter_room(sid, room)

    async def leave_room(self, sid: str, room: str) -> None:
        await self.sio.leave_room(sid, room)

    def run(self) -> None:
        uvicorn.run(self.sio_app, host="127.0.0.1", log_level="debug")
