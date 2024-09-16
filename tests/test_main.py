import asyncio
import uuid
from multiprocessing import Process
from time import sleep

import pytest
import socketio
import uvicorn

from fliji_sockets.api_client import FlijiApiService
from tests.test_helper import TestHelper


@pytest.fixture(scope="session")
def server():
    proc = Process(target=uvicorn.run, args=("fliji_sockets.sio_main:sio_asgi_app",),
                   kwargs={"host": "127.0.0.1", "port": 8095, "timeout_graceful_shutdown": 5})
    proc.start()
    sleep(2)  # Give the server a second to start
    yield
    proc.terminate()
    proc.join()


@pytest.fixture(scope="module")
def sio_client(server):
    sio = socketio.SimpleClient()
    sio.connect('http://localhost:8095')
    sleep(1)
    yield sio
    sio.disconnect()


@pytest.fixture(scope="module")
def sio_clients(server, request):
    num_clients = request.param
    clients = []
    for _ in range(num_clients):
        sio = socketio.Client()
        sio.connect('http://localhost:8095')
        sleep(1)
        clients.append(sio)
    yield clients
    for client in clients:
        client.disconnect()


def test_timeline_connect(sio_client):
    user = TestHelper.get_user(1)
    print(user)

    sio_client.emit('startup', {'auth_token': user.token})
    sleep(1)

    sio_client.emit('timeline_connect', {'video_uuid': str(uuid.uuid4())})
    response = sio_client.receive()

    response_event_name = response[0]
    response_event_data = response[1]

    assert response_event_name == 'timeline_status'

    # assert that the current user is in the response data
    users = response_event_data['users']

    assert len(users) == 1

    timeline_user = users[0]
    assert timeline_user['user_uuid'] == user.uuid


def test_online_offline(sio_client):
    user = TestHelper.get_user(1)
    print(user)

    sio_client.emit('startup', {'auth_token': user.token})
    sleep(1)

    # verify that the user is online
    api_client = FlijiApiService()
    response: dict = asyncio.run(api_client.get_user_profile(user.token))

    assert response['is_online'] is True

    # go offline
    sio_client.emit('go_offline')
    sleep(0.2)

    # verify that the user is offline
    response = asyncio.run(api_client.get_user_profile(user.token))
    assert response['is_online'] is False

    # go online
    sio_client.emit('go_online')
    sleep(0.2)

    # verify that the user is online
    response = asyncio.run(api_client.get_user_profile(user.token))
    assert response['is_online'] is True


def test_fliji_mode(sio_client):
    user = TestHelper.get_user(1)
    print(user)

    sio_client.emit('startup', {'auth_token': user.token})
    sleep(1)

    sio_client.emit("enable_fliji_mode")
    sleep(0.2)

    api_client = FlijiApiService()
    # verify that the user is in fliji mode
    response: dict = asyncio.run(api_client.get_user_profile(user.token))

    assert response['fliji_mode_enabled'] is True

    # disable fliji mode
    sio_client.emit("disable_fliji_mode")
    sleep(0.2)

    # verify that the user is not in fliji mode
    response = asyncio.run(api_client.get_user_profile(user.token))
    assert response['fliji_mode_enabled'] is False


def test_add_video_view(sio_client):
    user = TestHelper.get_user(1)
    video = TestHelper.get_video(user.token)

    # video detail data
    api_client = FlijiApiService()
    sio_client.emit('startup', {'auth_token': user.token})
    sleep(1)

    # timeline connect
    sio_client.emit('timeline_connect', {'video_uuid': video['uuid']})

    sleep(.2)

    # leave the timeline
    sio_client.emit('timeline_leave')

    sleep(.2)

    # get video detail
    response: dict = asyncio.run(api_client.get_video(user.token, video['uuid']))

    assert response['is_viewed'] is True