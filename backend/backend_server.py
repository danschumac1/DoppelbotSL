# src/backend_server.py
import json
import os
import time
import uuid
import random
import asyncio
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Dict, Set, Optional, List
from backend.ai.shadows import ShadowAIManager


from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.persistence import Sink

# ---------------------------
# Game Constants
# ---------------------------
MIN_PLAYERS = 3
MAX_PLAYERS = 5
TOTAL_ROUNDS = 3
VOTE_SECONDS = 200
CHAT_SECONDS = 120

PHASE_LOBBY = "LOBBY"
PHASE_CHAT  = "CHAT"
PHASE_VOTE  = "VOTE"
PHASE_SCORE = "SCORE"

# ---------------------------
# Helpers
# ---------------------------

def _norm_room(room_id: str) -> str:
    return (room_id or "").strip().upper()

def now_ts() -> int:
    return int(time.time())


# ---------------------------
# Random username generator
# ---------------------------
_ADJ = [
    "Orbit", "Pebble", "Crimson", "Velvet", "Neon", "Silver", "Lunar", "Echo",
    "Mango", "Arctic", "Cinder", "Kite", "Nova", "Coral", "Quartz", "Aqua",
]
_NOUN = [
    "Fox", "Comet", "Otter", "Wisp", "Raven", "Tiger", "Koala", "Falcon",
    "Panda", "Lynx", "Cobra", "Finch", "Gecko", "Dolphin", "Badger", "Hawk",
]

def generate_username(taken: Set[str]) -> str:
    # try a bunch of times before falling back
    for _ in range(200):
        name = f"{random.choice(_ADJ)}{random.choice(_NOUN)}"
        if name not in taken:
            return name
    # fallback
    i = 2
    base = "Player"
    name = base
    while name in taken:
        name = f"{base}{i}"
        i += 1
    return name

# ---------------------------
# In-memory state (rooms/users/connections)
# ---------------------------
room_last_activity: Dict[str, float] = defaultdict(lambda: time.time())
room_connections: Dict[str, Dict[str, WebSocket]] = defaultdict(dict)  # room_id -> player_id -> websocket

@dataclass
class Player:
    player_id: str
    username: str
    is_ai: bool = False           # SERVER ONLY (do not leak until game_over)
    connected: bool = True
    is_host: bool = False
    eliminated: bool = False

@dataclass
class RoomState:
    room_id: str
    host_player_id: Optional[str] = None
    phase: str = PHASE_LOBBY
    round: int = 0  # 0 in lobby, then 1..3
    players: Dict[str, Player] = field(default_factory=dict)  # player_id -> Player
    vote_ends_at: Optional[int] = None
    vote_task_id: int = 0

    # votes_by_round[round][voter_id] = target_id
    votes_by_round: Dict[int, Dict[str, str]] = field(default_factory=lambda: defaultdict(dict))

    # ai_top_voted_by_round[round] = bool
    ai_top_voted_by_round: Dict[int, bool] = field(default_factory=dict)

    ai_player_id: Optional[str] = None

    chat_ends_at: Optional[int] = None
    vote_ends_at: Optional[int] = None
    
    phase_task_id: int = 0

rooms: Dict[str, RoomState] = {}

def get_room(room_id: str) -> RoomState:
    room_id = _norm_room(room_id)
    if room_id not in rooms:
        rooms[room_id] = RoomState(room_id=room_id)
    return rooms[room_id]

def room_public_snapshot(room: RoomState) -> dict:
    # Snapshot safe for clients (no is_ai)
    players = []
    for p in room.players.values():
        players.append({
            "playerId": p.player_id,
            "username": p.username,
            "connected": p.connected,
            "isHost": (p.player_id == room.host_player_id),
            "eliminated": p.eliminated
        })
    players.sort(key=lambda x: (not x["isHost"], x["username"]))
    snap = {
        "roomId": room.room_id,
        "phase": room.phase,
        "round": room.round,
        "hostPlayerId": room.host_player_id,
        "players": players,
        "minPlayers": MIN_PLAYERS,
        "maxPlayers": MAX_PLAYERS,
        "totalRounds": TOTAL_ROUNDS,
    }
    
    if room.phase == PHASE_CHAT and room.chat_ends_at:
        snap["chatEndsAt"] = room.chat_ends_at
    if room.phase == PHASE_VOTE and room.vote_ends_at:
        snap["voteEndsAt"] = room.vote_ends_at
    
    return snap

# ---------------------------
# Lifespan (startup/shutdown)
# ---------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.sink = Sink()

    async def send_chat(room_id: str, username: str, text: str):
        ts = int(time.time())
        app.state.sink.emit_message(room_id, username, text, ts)
        await broadcast(room_id, {"type": "chat_message", "data": {"user": username, "text": text, "ts": ts}})
    
    app.state.shadow_ai = ShadowAIManager(send_chat)

    print("✅ Sink started")
    yield
    app.state.sink.shutdown()
    print("🛑 Sink stopped")

app = FastAPI(title="DoppelBot Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock down later
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
    for rid, room in rooms.items():
        out.append({
            "id": rid,
            "users": len(room.players),
            "lastActivity": int(now - room_last_activity[rid]),
            "phase": room.phase,
            "round": room.round,
        })
    out.sort(key=lambda r: r["lastActivity"])
    return out

@app.post("/api/rooms")
async def create_room(payload: dict):
    rid = _norm_room(payload.get("id"))
    if not rid:
        raise HTTPException(400, "Missing id")
    get_room(rid)
    room_last_activity[rid] = time.time()
    return {"id": rid}

@app.post("/api/rooms/{room_id}/join")
async def join_room(room_id: str, payload: dict):
    """
    MVP: ignore user-provided name. Server assigns random username + UUID player_id.
    """
    room = get_room(room_id)

    if len(room.players) >= MAX_PLAYERS:
        raise HTTPException(400, f"Room full (max {MAX_PLAYERS}).")

    taken_names = {p.username for p in room.players.values()}
    username = generate_username(taken_names)
    player_id = str(uuid.uuid4())

    is_first = (len(room.players) == 0)
    p = Player(player_id=player_id, username=username, is_host=is_first)
    room.players[player_id] = p

    if is_first:
        room.host_player_id = player_id
        room.phase = PHASE_LOBBY
        room.round = 0

    room_last_activity[room.room_id] = time.time()

    return {
        "roomId": room.room_id,
        "playerId": player_id,
        "username": username,
        "isHost": (player_id == room.host_player_id),
        "snapshot": room_public_snapshot(room),
    }

@app.post("/api/rooms/{room_id}/start")
async def start_game(room_id: str, payload: dict):
    room = get_room(room_id)
    caller = (payload.get("playerId") or "").strip()
    if not caller:
        raise HTTPException(400, "Missing playerId")

    # Host-only
    if caller != room.host_player_id:
        raise HTTPException(403, "Only host can start the game.")

    # Room size rules
    n = len(room.players)
    if n < MIN_PLAYERS:
        raise HTTPException(400, f"Need at least {MIN_PLAYERS} players to start.")
    if n > MAX_PLAYERS:
        raise HTTPException(400, f"Too many players (max {MAX_PLAYERS}).")

    # Only start from lobby
    if room.phase != PHASE_LOBBY:
        raise HTTPException(400, "Game already started.")

    # ---- Reset game state ----
    room.round = 1
    room.votes_by_round.clear()

    # cancel any old timers
    room.phase_task_id += 1
    room.chat_ends_at = None
    room.vote_ends_at = None

    # reset per-player state
    for p in room.players.values():
        p.eliminated = False
        p.is_ai = False

    # Assign AI internally (do NOT reveal)
    ai_player_id = random.choice(list(room.players.keys()))
    room.ai_player_id = ai_player_id
    room.players[ai_player_id].is_ai = True

    room_last_activity[room.room_id] = time.time()

    app.state.shadow_ai.reset_for_room()

    # create shadows for all humans (eligible players)
    for pid, p in room.players.items():
        # only make shadows for humans (all players are humans in current MVP)
        app.state.shadow_ai.ensure_shadow(pid, p.username)


    # Start round 1 chat (this broadcasts snapshot + sets chatEndsAt + schedules timer)
    await enter_chat_phase(room)

    return {"ok": True, "snapshot": room_public_snapshot(room)}


@app.get("/api/rooms/{room_id}/history")
async def room_history(room_id: str, limit: int = 50):
    room = _norm_room(room_id)
    msgs = app.state.sink.recent_messages(room, limit=limit)
    return {"roomId": room, "messages": msgs}

# ---------------------------
# Game mechanics
# ---------------------------
def require_player(room: RoomState, player_id: str) -> Player:
    if player_id not in room.players:
        raise HTTPException(400, "Unknown playerId.")
    return room.players[player_id]

def compute_top_voted(votes: Dict[str, str]) -> Optional[str]:
    """
    votes: voter_id -> target_id
    Returns top target_id, tie broken randomly.
    """
    if not votes:
        return None
    counts: Dict[str, int] = defaultdict(int)
    for _voter, target in votes.items():
        counts[target] += 1
    maxv = max(counts.values())
    tied = [tid for tid, c in counts.items() if c == maxv]
    return random.choice(tied)

def humans_win(room: RoomState) -> bool:
    # Humans win if AI top-voted in >= 2 of 3 rounds
    hits = sum(1 for r in range(1, TOTAL_ROUNDS + 1) if room.ai_top_voted_by_round.get(r))
    return hits >= 2

def eligible_players(room: RoomState) -> List[Player]:
    return [p for p in room.players.values() if not p.eliminated]

def eligible_voter_ids(room: RoomState) -> Set[str]:
    return {p.player_id for p in room.players.values() if not p.eliminated}

def eligible_target_ids(room: RoomState) -> Set[str]:
    # Usually same as eligible voters; adjust later if needed
    return eligible_voter_ids(room)

def compute_top_voted(votes: Dict[str, str]) -> Optional[str]:
    if not votes:
        return None
    counts: Dict[str, int] = defaultdict(int)
    for _voter, target in votes.items():
        counts[target] += 1
    maxv = max(counts.values())
    tied = [tid for tid, c in counts.items() if c == maxv]
    return random.choice(tied)

async def resolve_vote_and_eliminate(room: RoomState):
    # cancel any pending timer instances
    room.phase_task_id += 1
    room.vote_ends_at = None

    r = room.round
    votes = room.votes_by_round.get(r, {})

    # pick top vote (random tie-break)
    top = compute_top_voted(votes)

    eliminated_username = None
    eliminated_player_id = None

    # only eliminate if valid and not already eliminated
    if top and top in room.players and not room.players[top].eliminated:
        room.players[top].eliminated = True
        eliminated_username = room.players[top].username
        eliminated_player_id = top

    await broadcast(room.room_id, {
        "type": "elimination",
        "data": {
            "round": r,
            "eliminatedPlayerId": eliminated_player_id,
            "eliminatedUsername": eliminated_username
        }
    })

    # end conditions
    alive = eligible_players(room)
    if r >= TOTAL_ROUNDS or len(alive) <= 1:
        room.phase = PHASE_SCORE
        room.chat_ends_at = None
        room.vote_ends_at = None

        await broadcast(room.room_id, {"type": "phase_changed", "data": {"phase": room.phase, "round": room.round}})
        await broadcast(room.room_id, {"type": "room_snapshot", "data": room_public_snapshot(room)})
        await broadcast(room.room_id, {
            "type": "game_over",
            "data": {
                "remaining": [p.username for p in alive],
                "eliminated": [p.username for p in room.players.values() if p.eliminated],
            }
        })
        return

    # next round
    room.round += 1
    await enter_chat_phase(room)



async def enter_vote_phase(room: RoomState):
    room.phase = PHASE_VOTE
    room.vote_ends_at = now_ts() + VOTE_SECONDS
    room.chat_ends_at = None
    room.votes_by_round[room.round] = {}
    room.phase_task_id += 1
    my_id = room.phase_task_id

    await broadcast(room.room_id, {"type": "phase_changed", "data": {"phase": room.phase, "round": room.round}})
    await broadcast(room.room_id, {"type": "room_snapshot", "data": room_public_snapshot(room)})

    async def timer():
        await asyncio.sleep(VOTE_SECONDS)
        if room.phase == PHASE_VOTE and room.phase_task_id == my_id:
            await resolve_vote_and_eliminate(room)

    asyncio.create_task(timer())

async def enter_chat_phase(room: RoomState):
    room.phase = PHASE_CHAT
    room.chat_ends_at = now_ts() + CHAT_SECONDS
    room.vote_ends_at = None
    room.phase_task_id += 1
    my_id = room.phase_task_id

    await broadcast(room.room_id, {"type": "phase_changed", "data": {"phase": room.phase, "round": room.round}})
    await broadcast(room.room_id, {"type": "room_snapshot", "data": room_public_snapshot(room)})

    async def timer():
        await asyncio.sleep(CHAT_SECONDS)
        if room.phase == PHASE_CHAT and room.phase_task_id == my_id:
            await enter_vote_phase(room)

    asyncio.create_task(timer())



# ---------------------------
# WebSocket
# ---------------------------
@app.websocket("/ws/{room_id}/{player_id}")
async def ws_room(websocket: WebSocket, room_id: str, player_id: str):
    room = get_room(room_id)
    pid = (player_id or "").strip()

    # Ensure player exists
    if pid not in room.players:
        # client should call /join first
        await websocket.accept()
        await websocket.send_json({"type": "error", "text": "Unknown playerId. Call /join first."})
        await websocket.close()
        return

    await websocket.accept()

    # register connection
    room_connections[room.room_id][pid] = websocket
    room.players[pid].connected = True
    room_last_activity[room.room_id] = time.time()

    # Send snapshot + history
    await websocket.send_json({"type": "room_snapshot", "data": room_public_snapshot(room)})

    history = app.state.sink.recent_messages(room.room_id, limit=50)
    await websocket.send_json({"type": "history", "room": room.room_id, "messages": history})

    await broadcast(room.room_id, {"type": "system", "text": f"{room.players[pid].username} joined."})
    await broadcast(room.room_id, {"type": "room_snapshot", "data": room_public_snapshot(room)})

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                msg = {"type": "send_chat", "data": {"text": raw}}

            t = msg.get("type")

            # -------------------------
            # CHAT
            # -------------------------
            if t == "send_chat":
                data = msg.get("data") or {}
                text = (data.get("text") or "").strip()

                # Must exist in room
                if pid not in room.players:
                    await websocket.send_json({"type": "error", "text": "Unknown player."})
                    continue

                player = room.players[pid]

                # Phase gate
                if room.phase != PHASE_CHAT:
                    await websocket.send_json({"type": "error", "text": "Chat is not enabled right now."})
                    continue

                # Human permission gate (eliminated humans cannot type)
                if player.eliminated:
                    await websocket.send_json({"type": "error", "text": "You are eliminated and cannot chat."})
                    continue

                # Send the human message through the canonical pipeline
                await send_chat_message(room.room_id, player.username, text)

                # Trigger AI shadows (including eliminated owners)
                # This method should decide WHICH shadows respond to avoid spam.
                await app.state.shadow_ai.on_room_message(
                    room_id=room.room_id,
                    human_sender_player_id=pid,
                    human_sender_username=player.username,
                    human_text=text,
                    room=room,           
                )

                continue

            # -------------------------
            # VOTE
            # -------------------------
            elif t == "cast_vote":
                data = msg.get("data") or {}
                voter = room.players[pid]
                if voter.eliminated:
                    await websocket.send_json({"type": "error", "text": "You are eliminated and cannot vote."})
                    continue

                if room.phase != PHASE_VOTE:
                    await websocket.send_json({"type": "error", "text": "Not in vote phase."})
                    continue

                target = (data.get("targetPlayerId") or "").strip()
                print("VOTE targetPlayerId:", target)
                print("ROOM player keys:", list(room.players.keys()))


                # target must exist AND must be eligible (not eliminated)
                if target not in room.players or room.players[target].eliminated:
                    await websocket.send_json({"type": "error", "text": "Invalid vote target."})
                    continue

                # only count eligible voters
                eligible = eligible_voter_ids(room)

                # record vote (allow overwrite)
                room.votes_by_round[room.round][pid] = target

                submitted = len(room.votes_by_round[room.round])
                total = len(eligible)

                await broadcast(room.room_id, {"type": "vote_progress", "data": {"round": room.round, "submitted": submitted, "total": total}})

                # resolve early when all eligible voted
                if submitted >= total:
                    await resolve_vote_and_eliminate(room)


            # -------------------------
            # PHASE CONTROL (host) USING AS DEBUG REMOVE IN FINAL VERSION
            # -------------------------
            elif t == "end_chat":
                # Host can end chat early and move to vote
                if pid != room.host_player_id:
                    await websocket.send_json({"type": "error", "text": "Only host can end chat."})
                    continue
                if room.phase != PHASE_CHAT:
                    await websocket.send_json({"type": "error", "text": "Not in chat phase."})
                    continue

                await enter_vote_phase(room)
                room.votes_by_round[room.round] = {}  # reset votes for this round
                await broadcast(room.room_id, {"type": "phase_changed", "data": {"phase": room.phase, "round": room.round}})
                await broadcast(room.room_id, {"type": "room_snapshot", "data": room_public_snapshot(room)})

            elif t == "request_snapshot":
                await websocket.send_json({"type": "room_snapshot", "data": room_public_snapshot(room)})

            elif t == "typing":
                # optional: keep it
                data = msg.get("data") or {}
                await broadcast(room.room_id, {
                    "type": "typing",
                    "data": {"playerId": pid, "user": room.players[pid].username, "isTyping": bool(data.get("isTyping"))}
                })

            else:
                await websocket.send_json({"type": "error", "text": f"unknown type: {t}"})

    except WebSocketDisconnect:
        pass
    finally:
        # unregister
        room_connections[room.room_id].pop(pid, None)
        if pid in room.players:
            room.players[pid].connected = False
        room_last_activity[room.room_id] = time.time()

        # broadcast leave + snapshot
        if pid in room.players:
            await broadcast(room.room_id, {"type": "system", "text": f"{room.players[pid].username} left."})
            await broadcast(room.room_id, {"type": "room_snapshot", "data": room_public_snapshot(room)})

async def broadcast(room_id: str, payload: dict):
    dead = []
    for pid, ws in list(room_connections[room_id].items()):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(pid)
    for pid in dead:
        room_connections[room_id].pop(pid, None)
        # don't remove the player from the room; mark disconnected only
        room = rooms.get(room_id)
        if room and pid in room.players:
            room.players[pid].connected = False

async def send_chat_message(room_id: str, username: str, text: str):
    text = (text or "").strip()
    if not text:
        return

    ts = int(time.time())
    room_last_activity[room_id] = time.time()

    # Persist
    app.state.sink.emit_message(room_id, username, text, ts)

    # Broadcast (single source of truth)
    await broadcast(room_id, {
        "type": "chat_message",
        "data": {"user": username, "text": text, "ts": ts}
    })


# ---------------------------
# DEBUG LINES (keep)
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
