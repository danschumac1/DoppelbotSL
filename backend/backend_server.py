# src/backend_server.py
import json
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Dict, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.persistence import Sink

# ---------------------------
# In-memory state (rooms/users/connections)
# ---------------------------
rooms_users: Dict[str, Set[str]] = defaultdict(set)                 # room_id -> set(user_id)
room_last_activity: Dict[str, float] = defaultdict(lambda: time.time())
room_connections: Dict[str, Dict[str, WebSocket]] = defaultdict(dict)  # room_id -> user_id -> websocket

def _norm_room(room_id: str) -> str:
    return (room_id or "").strip().upper()

def _norm_user(user_id: str) -> str:
    return (user_id or "").strip()

# ---------------------------
# Lifespan (startup/shutdown)
# ---------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.sink = Sink()
    print("✅ Sink started")
    yield
    app.state.sink.shutdown()
    print("🛑 Sink stopped")

app = FastAPI(title="DoppelBot Backend", lifespan=lifespan)

# CORS (helps if you ever serve frontend separately or use tunnel domains)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock down later (your domain)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# REST API
# ---------------------------
@app.get("/api/rooms")
async def list_rooms():
    now = time.time()
    out = []
    for rid, users in rooms_users.items():
        out.append({
            "id": rid,
            "users": len(users),
            "lastActivity": int(now - room_last_activity[rid]),
        })
    out.sort(key=lambda r: r["lastActivity"])
    return out

@app.post("/api/rooms")
async def create_room(payload: dict):
    rid = _norm_room(payload.get("id"))
    if not rid:
        raise HTTPException(400, "Missing id")

    rooms_users.setdefault(rid, set())
    room_last_activity[rid] = time.time()
    return {"id": rid}

@app.post("/api/rooms/{room_id}/join")
async def join_room(room_id: str, payload: dict):
    room = _norm_room(room_id)
    rooms_users.setdefault(room, set())

    desired = (payload.get("name") or "").strip()
    base = desired if desired else "Player"
    name = base
    n = 1
    while name in rooms_users[room]:
        n += 1
        name = f"{base}{n}"

    rooms_users[room].add(name)
    room_last_activity[room] = time.time()
    return {"roomId": room, "userId": name, "displayName": name}

@app.get("/api/rooms/{room_id}/history")
async def room_history(room_id: str, limit: int = 50):
    room = _norm_room(room_id)
    msgs = app.state.sink.recent_messages(room, limit=limit)
    return {"roomId": room, "messages": msgs}

# ---------------------------
# WebSocket
# ---------------------------
@app.websocket("/ws/{room_id}/{user_id}")
async def ws_room(websocket: WebSocket, room_id: str, user_id: str):
    room = _norm_room(room_id)
    user = _norm_user(user_id)

    await websocket.accept()

    # register
    room_connections[room][user] = websocket
    rooms_users[room].add(user)
    room_last_activity[room] = time.time()

    # Sends history upon connect
    history = app.state.sink.recent_messages(room, limit=50)
    await websocket.send_json({"type": "history", "room": room, "messages": history})

    await broadcast(room, {"type": "system", "text": f"{user} joined."})


    try:
        while True:
            raw = await websocket.receive_text()
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
                room_last_activity[room] = time.time()

                # persist
                app.state.sink.emit_message(room, user, text, ts)

                # broadcast
                await broadcast(room, {"type": "chat", "user": user, "text": text, "ts": ts})

            elif t == "typing":
                await broadcast(room, {"type": "typing", "user": user, "isTyping": bool(msg.get("isTyping"))})

            elif t == "guess":
                await broadcast(room, {"type": "guess", "user": user, "who": msg.get("who")})

            else:
                await websocket.send_json({"type": "error", "text": f"unknown type: {t}"})

    except WebSocketDisconnect:
        pass
    finally:
        room_connections[room].pop(user, None)
        rooms_users[room].discard(user)
        room_last_activity[room] = time.time()
        await broadcast(room, {"type": "system", "text": f"{user} left."})

async def broadcast(room: str, payload: dict):
    dead = []
    for u, ws in list(room_connections[room].items()):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(u)
    for u in dead:
        room_connections[room].pop(u, None)
        rooms_users[room].discard(u)

# ---------------------------
# DEBUG LINES
# ---------------------------
@app.get("/api/debug/db")
async def db_debug():
    return {"db_path": str(app.state.sink.path)}

@app.get("/api/debug/messages")
async def debug_messages():
    import sqlite3
    con = sqlite3.connect(app.state.sink.path)
    rows = con.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 20").fetchall()
    con.close()
    return rows



# Serve frontend LAST
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
