import asyncio

from pymongo.database import Database

# noinspection PyUnresolvedReferences
import fliji_sockets.dependencies  # Ensure dependencies are registered
# noinspection PyUnresolvedReferences
import fliji_sockets.events.handlers  # Ensure events are registered
from fliji_sockets.core.di import container
from fliji_sockets.core.socketio_application import SocketioApplication
from fliji_sockets.debug_data import load_debug_data
from fliji_sockets.events.handlers import register_events
from fliji_sockets.helpers import configure_logging, configure_sentry, run_async_task
from fliji_sockets.settings import APP_ENV
from fliji_sockets.store import delete_all_timeline_groups, delete_all_timeline_watch_sessions

# Configure logging and monitoring
configure_logging()
configure_sentry()

# Create a new event loop for a background thread
loop = asyncio.new_event_loop()


def clear_data_on_startup(database: Database):
    # timeline groups and watch sessions
    delete_all_timeline_groups(database)
    delete_all_timeline_watch_sessions(database)
    # delete_all_timeline_chat_messages(database)


async def setup_dependencies():
    """Initialize async dependencies."""
    db = await container.get("db")

    clear_data_on_startup(db)

    if APP_ENV in ["dev", "local"]:
        await load_debug_data(db)

    sio_app = SocketioApplication()
    register_events(sio_app)

    return sio_app


# Run the async function in a separate thread
app = run_async_task(setup_dependencies(), loop=loop)

if not app:
    raise RuntimeError("SocketioApplication not initialized")

# Expose `asgi_app` for Uvicorn
asgi_app = app.get_asgi_app()
