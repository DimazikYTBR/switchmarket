from fastapi import WebSocket


class OrderConnectionManager:
    def __init__(self) -> None:
        self.active: dict[int, set[WebSocket]] = {}

    async def connect(self, order_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.setdefault(order_id, set()).add(websocket)

    def disconnect(self, order_id: int, websocket: WebSocket) -> None:
        connections = self.active.get(order_id)
        if connections and websocket in connections:
            connections.remove(websocket)
        if connections is not None and not connections:
            self.active.pop(order_id, None)

    async def broadcast(self, order_id: int, message: dict) -> None:
        connections = self.active.get(order_id, set())
        stale = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(order_id, connection)


manager = OrderConnectionManager()
