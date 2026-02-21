# src/game/ws.py
import json
import time
from fastapi import WebSocket, WebSocketDisconnect

from .constants import PHASE_CHAT, PHASE_VOTE, GAME_RULES
from .state import get_room, room_public_snapshot, room_connections, room_last_activity
from .engine import eligible_voter_ids, resolve_vote_and_eliminate, enter_vote_phase

async def ws_room(websocket: WebSocket, room_id: str, player_id: str, *, sink, broadcast, send_chat_message, shadow_ai):
    room = get_room(room_id)
    pid = (player_id or "").strip()

    if pid not in room.players:
        await websocket.accept()
        await websocket.send_json({"type": "error", "text": "Unknown playerId. Call /join first."})
        await websocket.close()
        return

    await websocket.accept()

    # register
    room_connections[room.room_id][pid] = websocket
    room.players[pid].connected = True
    room_last_activity[room.room_id] = time.time()

    # snapshot + history
    await websocket.send_json({"type": "room_snapshot", "data": room_public_snapshot(room)})
    history = sink.recent_messages(room.room_id, limit=50)
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

            if t == "send_chat":
                data = msg.get("data") or {}
                text = (data.get("text") or "").strip()
                player = room.players[pid]

                if room.phase != PHASE_CHAT:
                    await websocket.send_json({"type": "error", "text": "Chat is not enabled right now."})
                    continue
                if player.eliminated:
                    await websocket.send_json({"type": "error", "text": "You are eliminated and cannot chat."})
                    continue

                await send_chat_message(room.room_id, player.username, text)

                # shadows persist even if eliminated owners (handled inside on_room_message)
                history = sink.recent_messages(room.room_id, limit=50)
                await shadow_ai.on_room_message(
                    room_id=room.room_id,
                    human_sender_player_id=pid,
                    human_sender_username=player.username,
                    human_text=text,
                    room=room,
                    conversation_history=history,
                    game_rules=GAME_RULES,
                )
                continue

            if t == "cast_vote":
                data = msg.get("data") or {}
                voter = room.players[pid]

                if voter.eliminated:
                    await websocket.send_json({"type": "error", "text": "You are eliminated and cannot vote."})
                    continue
                if room.phase != PHASE_VOTE:
                    await websocket.send_json({"type": "error", "text": "Not in vote phase."})
                    continue

                target = (data.get("targetPlayerId") or "").strip()
                if target not in room.players or room.players[target].eliminated:
                    await websocket.send_json({"type": "error", "text": "Invalid vote target."})
                    continue

                eligible = eligible_voter_ids(room)
                room.votes_by_round[room.round][pid] = target

                submitted = len(room.votes_by_round[room.round])
                total = len(eligible)

                await broadcast(room.room_id, {"type": "vote_progress", "data": {"round": room.round, "submitted": submitted, "total": total}})

                if submitted >= total:
                    await resolve_vote_and_eliminate(room, broadcast)
                continue

            if t == "end_chat":
                # debug host skip
                if pid != room.host_player_id:
                    await websocket.send_json({"type": "error", "text": "Only host can end chat."})
                    continue
                if room.phase != PHASE_CHAT:
                    await websocket.send_json({"type": "error", "text": "Not in chat phase."})
                    continue
                await enter_vote_phase(room, broadcast)
                continue

            if t == "request_snapshot":
                await websocket.send_json({"type": "room_snapshot", "data": room_public_snapshot(room)})
                continue

            if t == "typing":
                data = msg.get("data") or {}
                await broadcast(room.room_id, {
                    "type": "typing",
                    "data": {"playerId": pid, "user": room.players[pid].username, "isTyping": bool(data.get("isTyping"))}
                })
                continue

            await websocket.send_json({"type": "error", "text": f"unknown type: {t}"})

    except WebSocketDisconnect:
        pass
    finally:
        room_connections[room.room_id].pop(pid, None)
        if pid in room.players:
            room.players[pid].connected = False
        room_last_activity[room.room_id] = time.time()

        if pid in room.players:
            await broadcast(room.room_id, {"type": "system", "text": f"{room.players[pid].username} left."})
            await broadcast(room.room_id, {"type": "room_snapshot", "data": room_public_snapshot(room)})
