# src/backend/ai/shadows.py
import asyncio
import random
from dataclasses import dataclass
from typing import Dict, Optional, Callable, Set

from game.util import generate_username

@dataclass
class ShadowAI:
    owner_player_id: str
    username: str  # unique code name shown in chat, different from owner's

class ShadowAIManager:
    """
    Manages one AI shadow per human player.
    Each shadow gets its own unique code name (not derived from the owner's).
    Calls back into server via `send_chat(room_id, username, text)`.
    """
    def __init__(self, send_chat: Callable[[str, str, str], "asyncio.Future"]):
        self._send_chat = send_chat
        self._agents_by_owner: Dict[str, ShadowAI] = {}
        self._shadow_names: Set[str] = set()  # tracks all names used by shadows

    def reset_for_room(self):
        self._agents_by_owner.clear()
        self._shadow_names.clear()

    def ensure_shadow(self, owner_player_id: str, owner_username: str, human_taken: Set[str] = None) -> ShadowAI:
        if owner_player_id in self._agents_by_owner:
            return self._agents_by_owner[owner_player_id]

        # Generate a code name that doesn't collide with any human or other shadow
        taken = self._shadow_names | (human_taken or set())
        shadow_username = generate_username(taken)
        self._shadow_names.add(shadow_username)

        agent = ShadowAI(
            owner_player_id=owner_player_id,
            username=shadow_username,
        )
        self._agents_by_owner[owner_player_id] = agent
        return agent

    def get_shadow(self, owner_player_id: str) -> Optional[ShadowAI]:
        return self._agents_by_owner.get(owner_player_id)

    async def on_human_message(
        self,
        room_id: str,
        owner_player_id: str,
        owner_username: str,
        human_text: str,
        conversation_history: list,  # [{"user": str, "text": str, "ts": int}, ...]
        game_rules: str,
    ):
        """
        Placeholder AI logic:
        - prints "AI LOGIC HERE"
        - sends a short mocked reply from that human's AI copy
        """
        agent = self.ensure_shadow(owner_player_id, owner_username)

        print("AI LOGIC HERE")
        # Dan's variables:
        # human_text          -> the specific message this player just sent
        # conversation_history -> full chat log for the room (chronological)
        # game_rules           -> string description of the game rules

        # Simulate thinking delay
        await asyncio.sleep(0.35 + random.random() * 0.65)

        reply = f"(placeholder) I saw: {human_text}"
        await self._send_chat(room_id, agent.username, reply)

    async def on_room_message(
        self,
        room_id: str,
        human_sender_player_id: str,
        human_sender_username: str,
        human_text: str,
        room,
        conversation_history: list,  # [{"user": str, "text": str, "ts": int}, ...]
        game_rules: str,
    ):
        print("AI LOGIC HERE")
        # Dan's variables:
        # human_text          -> the specific message that was just sent
        # conversation_history -> full chat log for the room (chronological)
        # game_rules           -> string description of the game rules

        # Example: pick 1 random shadow (could be eliminated owner) to respond
        # to keep chat from exploding.
        import random, asyncio

        human_taken = {p.username for p in room.players.values()}
        candidates = []
        for pid, p in room.players.items():
            if pid == human_sender_player_id:
                continue
            # include eliminated too
            agent = self.ensure_shadow(pid, p.username, human_taken)
            candidates.append(agent)

        if not candidates:
            return

        agent = random.choice(candidates)

        await asyncio.sleep(0.35 + random.random() * 0.65)
        await self._send_chat(room_id, agent.username, f"(placeholder) reacting to: {human_text}")
