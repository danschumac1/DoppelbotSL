# src/backend_server.py
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.persistence import Sink
from ai.shadows import ShadowAIManager

from game.api import register_api
from game.ws import ws_room
from game.util import norm_room
from game.state import room_connections, rooms, room_last_activity


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.sink = Sink()

    async def send_chat(room_id: str, username: str, text: str):
        ts = int(time.time())
        app.state.sink.emit_message(room_id, username, text, ts)
        await broadcast(room_id, {
            "type": "chat_message",
            "data": {"user": username, "text": text, "ts": ts}
        })

    app.state.shadow_ai = ShadowAIManager(send_chat)
    print("✅ Sink started")
    yield
    app.state.sink.shutdown()
    print("🛑 Sink stopped")


app = FastAPI(title="DoppelBot Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def broadcast(room_id: str, payload: dict):
    dead = []
    for pid, ws in list(room_connections[room_id].items()):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(pid)

    for pid in dead:
        room_connections[room_id].pop(pid, None)
        room = rooms.get(room_id)
        if room and pid in room.players:
            room.players[pid].connected = False

async def send_chat_message(room_id: str, username: str, text: str):
    text = (text or "").strip()
    if not text:
        return

    ts = int(time.time())
    room_last_activity[room_id] = time.time()
    app.state.sink.emit_message(room_id, username, text, ts)

    await broadcast(room_id, {
        "type": "chat_message",
        "data": {"user": username, "text": text, "ts": ts}
    })

# Register REST API routes
register_api(
    app,
    get_sink=lambda: app.state.sink,
    broadcast=broadcast,
    get_shadow_ai=lambda: app.state.shadow_ai
)


@app.websocket("/ws/{room_id}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, player_id: str):
    rid = norm_room(room_id)
    await ws_room(
        websocket, rid, player_id,
        sink=app.state.sink,
        broadcast=broadcast,
        send_chat_message=send_chat_message,
        shadow_ai=app.state.shadow_ai
    )

# Serve frontend
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
