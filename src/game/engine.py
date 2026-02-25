# src/game/engine.py
import asyncio
import random
from collections import defaultdict
from typing import Dict, Optional, Set, Callable, Awaitable, List

from .constants import (
    PHASE_CHAT, PHASE_VOTE, PHASE_SCORE,
    CHAT_SECONDS, VOTE_SECONDS, TOTAL_ROUNDS
)
from .state import RoomState, Player, room_public_snapshot
from .util import now_ts

BroadcastFn = Callable[[str, dict], Awaitable[None]]

def eligible_players(room: RoomState) -> List[Player]:
    return [p for p in room.players.values() if not p.eliminated]

def eligible_voter_ids(room: RoomState) -> Set[str]:
    return {p.player_id for p in room.players.values() if not p.eliminated}

def compute_top_voted(votes: Dict[str, str]) -> Optional[str]:
    if not votes:
        return None
    counts: Dict[str, int] = defaultdict(int)
    for _, target in votes.items():
        counts[target] += 1
    maxv = max(counts.values())
    tied = [tid for tid, c in counts.items() if c == maxv]
    return random.choice(tied)

async def enter_chat_phase(room: RoomState, broadcast: BroadcastFn):
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
            await enter_vote_phase(room, broadcast)

    asyncio.create_task(timer())

async def enter_vote_phase(room: RoomState, broadcast: BroadcastFn):
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
            await resolve_vote_and_eliminate(room, broadcast)

    asyncio.create_task(timer())

async def resolve_vote_and_eliminate(room: RoomState, broadcast: BroadcastFn):
    room.phase_task_id += 1
    room.vote_ends_at = None

    r = room.round
    votes = room.votes_by_round.get(r, {})
    top = compute_top_voted(votes)

    eliminated_username = None
    eliminated_player_id = None

    if top and top in room.players and not room.players[top].eliminated:
        room.players[top].eliminated = True
        eliminated_username = room.players[top].username
        eliminated_player_id = top

    await broadcast(room.room_id, {
        "type": "elimination",
        "data": {"round": r, "eliminatedPlayerId": eliminated_player_id, "eliminatedUsername": eliminated_username}
    })

    alive = eligible_players(room)
    if r >= TOTAL_ROUNDS or len(alive) <= 1:
        room.phase = PHASE_SCORE
        room.chat_ends_at = None
        room.vote_ends_at = None

        await broadcast(room.room_id, {"type": "phase_changed", "data": {"phase": room.phase, "round": room.round}})
        await broadcast(room.room_id, {"type": "room_snapshot", "data": room_public_snapshot(room)})
        ai_player = room.players.get(room.ai_player_id) if room.ai_player_id else None
        ai_username = ai_player.username if ai_player else None
        ai_won = bool(ai_player and not ai_player.eliminated)

        await broadcast(room.room_id, {
            "type": "game_over",
            "data": {
                "aiUsername": ai_username,
                "aiWon": ai_won,
                "winner": "ai" if ai_won else "humans",
                "remaining": [
                    {"username": p.username, "isAi": p.is_ai}
                    for p in alive
                ],
                "eliminated": [
                    {"username": p.username, "isAi": p.is_ai}
                    for p in room.players.values() if p.eliminated
                ],
            }
        })
        return

    room.round += 1
    await enter_chat_phase(room, broadcast)
