# src/game/state.py
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from collections import defaultdict

from .constants import (
    PHASE_LOBBY, PHASE_CHAT, PHASE_VOTE, PHASE_SCORE,
    MIN_PLAYERS, MAX_PLAYERS, TOTAL_ROUNDS
)

@dataclass
class Player:
    player_id: str
    username: str
    is_ai: bool = False        # server-only
    connected: bool = True
    eliminated: bool = False

@dataclass
class RoomState:
    room_id: str
    host_player_id: Optional[str] = None
    phase: str = PHASE_LOBBY
    round: int = 0

    players: Dict[str, Player] = field(default_factory=dict)

    # Timers
    chat_ends_at: Optional[int] = None
    vote_ends_at: Optional[int] = None

    # Timer cancellation guard
    phase_task_id: int = 0

    # votes_by_round[round][voter_id] = target_id
    votes_by_round: Dict[int, Dict[str, str]] = field(default_factory=lambda: defaultdict(dict))

    # server-only AI assignment (do not reveal)
    ai_player_id: Optional[str] = None

# in-memory stores
rooms: Dict[str, RoomState] = {}
room_connections: Dict[str, Dict[str, object]] = defaultdict(dict)  # room_id -> player_id -> websocket
room_last_activity: Dict[str, float] = defaultdict(lambda: time.time())

def get_room(room_id: str) -> RoomState:
    if room_id not in rooms:
        rooms[room_id] = RoomState(room_id=room_id)
    return rooms[room_id]

def room_public_snapshot(room: RoomState) -> dict:
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
