class Response:
    def __init__(self, sio, sid):
        self.sio = sio
        self.sid = sid

    async def emit(self, event, data):
        await self.sio.emit(event, data, room=self.sid)


class ErrorResponse(Response):
    async def send_error(self, message, body=None):
        body = body or {}
        await self.emit("error", {"message": message, "body": body})
