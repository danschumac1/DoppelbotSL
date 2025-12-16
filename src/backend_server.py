from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from typing import Dict, Set
from contextlib import asynccontextmanager
from collections import defaultdict
from src.persistence import Sink 
import time, os, json


# Lifespan: startup / shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.sink = Sink()
    print("[lifespan] Sink started")

    yield 

    # Shutdown
    app.state.sink.shutdown()
    print("[lifespan] Sink stopped")


# Create FastAPI app with lifespan handler
app = FastAPI(title="DoppelBot Backend", lifespan=lifespan)


# In-memory room state (Need to move to own file later)

rooms_users: Dict[str, Set[str]] = defaultdict(set)
room_last_activity: Dict[str, float] = defaultdict(lambda: time.time())
room_connections: Dict[str, Dict[str, WebSocket]] = defaultdict(dict)


# Serve frontend
FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend")
)
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


# REST: rooms
@app.get("/api/rooms")
async def list_rooms():
    """Return a list of active rooms with user count and last activity."""
    now = time.time()
    out = [
        {
            "id": rid,
            "users": len(users),
            "lastActivity": int(now - room_last_activity[rid]),
        }
        for rid, users in rooms_users.items()
    ]
    out.sort(key=lambda r: r["lastActivity"])
    return out


@app.post("/api/rooms")
async def create_room(payload: dict):
    """Create a room with a specified ID (uppercased)."""
    rid = (payload.get("id") or "").strip().upper()
    if not rid:
        raise HTTPException(400, "Missing id")
    rooms_users.setdefault(rid, set())
    room_last_activity[rid] = time.time()
    return {"id": rid}


@app.post("/api/rooms/{room_id}/join")
async def join_room(room_id: str, payload: dict):
    """
    Join a room with a unique display name.
    If name is taken, append a number.
    """
    room_id = room_id.strip().upper()
    rooms_users.setdefault(room_id, set())

    desired = (payload.get("name") or "").strip()
    base = desired if desired else "Player"
    name = base
    n = 1
    while name in rooms_users[room_id]:
        n += 1
        name = f"{base}{n}"
    rooms_users[room_id].add(name)
    room_last_activity[room_id] = time.time()
    return {"roomId": room_id, "userId": name, "displayName": name}


@app.get("/api/rooms/{room_id}/history")
async def room_history(room_id: str, limit: int = 50):
    """
    Return recent persisted messages for a room.
    Uses Sink.recent_messages (SQLite).
    """
    rid = room_id.strip().upper()
    sink: Sink = app.state.sink
    return sink.recent_messages(rid, limit=limit)


# WebSocket: chat per room
@app.websocket("/ws/{room_id}/{user_id}")
async def ws_room(websocket: WebSocket, room_id: str, user_id: str):
    room = room_id.strip().upper()
    user = user_id.strip()
    sink: Sink = app.state.sink

    await websocket.accept()

    # Register connection
    room_connections[room][user] = websocket
    rooms_users[room].add(user)
    room_last_activity[room] = time.time()

    # Send recent history to this user only
    history = sink.recent_messages(room, limit=50)
    await websocket.send_json({"type": "history", "messages": history})

    # Notify others in the room
    await broadcast(room, {"type": "system", "text": f"{user} joined."})

    try:
        while True:
            raw = await websocket.receive_text()
            # Try to parse JSON, fallback to plain chat string
            try:
                msg = json.loads(raw)
            except Exception:
                msg = {"type": "chat", "text": raw}

            t = msg.get("type", "chat")

            if t == "chat":
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                ts = int(time.time())

                # Update activity and persist message
                room_last_activity[room] = time.time()
                sink.emit_message(room, user, text, ts)

                # Broadcast chat message to room
                await broadcast(
                    room,
                    {
                        "type": "chat",
                        "user": user,
                        "text": text,
                        "ts": ts,
                    },
                )

            elif t == "typing":
                await broadcast(
                    room,
                    {
                        "type": "typing",
                        "user": user,
                        "isTyping": bool(msg.get("isTyping")),
                    },
                )

            elif t == "guess":
                await broadcast(
                    room,
                    {
                        "type": "guess",
                        "user": user,
                        "who": msg.get("who"),
                    },
                )

            else:
                await websocket.send_json(
                    {"type": "error", "text": f"unknown type: {t}"}
                )

    except WebSocketDisconnect:
        # Client disconnected;
        pass

    finally:
        # Remove connection and notify others
        room_connections[room].pop(user, None)
        rooms_users[room].discard(user)
        room_last_activity[room] = time.time()
        await broadcast(room, {"type": "system", "text": f"{user} left."})


# Helpers
async def broadcast(room: str, payload: dict):
    """
    Send a JSON payload to every connected WebSocket in a room.
    Drops dead connections.
    """
    dead = []
    for u, ws in list(room_connections[room].items()):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(u)
    for u in dead:
        room_connections[room].pop(u, None)
        rooms_users[room].discard(u)
