from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from typing import Dict, Set
from collections import defaultdict
import asyncio, time, os, json

app = FastAPI(title="DoppelBot Backend")

# In-memory state (swap to DB later)
rooms_users: Dict[str, Set[str]] = defaultdict(set)        # room_id -> {user_id}
room_last_activity: Dict[str, float] = defaultdict(lambda: time.time())
room_connections: Dict[str, Dict[str, WebSocket]] = defaultdict(dict)  # room_id -> user_id -> ws

# --- Serve frontend/ at "/" ---
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

# --- REST: rooms ---
@app.get("/api/rooms")
async def list_rooms():
    now = time.time()
    out = [{
        "id": rid,
        "users": len(users),
        "lastActivity": int(now - room_last_activity[rid]),
    } for rid, users in rooms_users.items()]
    out.sort(key=lambda r: r["lastActivity"])
    return out

@app.post("/api/rooms")
async def create_room(payload: dict):
    rid = (payload.get("id") or "").strip().upper()
    if not rid:
        raise HTTPException(400, "Missing id")
    rooms_users.setdefault(rid, set())
    room_last_activity[rid] = time.time()
    return {"id": rid}

@app.post("/api/rooms/{room_id}/join")
async def join_room(room_id: str, payload: dict):
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

# --- WebSocket: /ws/{room}/{user} ---
@app.websocket("/ws/{room_id}/{user_id}")
async def ws_room(websocket: WebSocket, room_id: str, user_id: str):
    room = room_id.strip().upper()
    user = user_id.strip()
    await websocket.accept()

    # register
    room_connections[room][user] = websocket
    rooms_users[room].add(user)
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
                room_last_activity[room] = time.time()
                await broadcast(room, {
                    "type": "chat", "user": user, "text": text, "ts": int(time.time())
                })
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
