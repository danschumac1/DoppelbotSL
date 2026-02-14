# src/game/util.py
import random
import time
from typing import Set

def norm_room(room_id: str) -> str:
    return (room_id or "").strip().upper()

def now_ts() -> int:
    return int(time.time())

_ADJ = [
    "Orbit", "Pebble", "Crimson", "Velvet", "Neon", "Silver", "Lunar", "Echo",
    "Mango", "Arctic", "Cinder", "Kite", "Nova", "Coral", "Quartz", "Aqua",
]
_NOUN = [
    "Fox", "Comet", "Otter", "Wisp", "Raven", "Tiger", "Koala", "Falcon",
    "Panda", "Lynx", "Cobra", "Finch", "Gecko", "Dolphin", "Badger", "Hawk",
]

def generate_username(taken: Set[str]) -> str:
    for _ in range(200):
        name = f"{random.choice(_ADJ)}{random.choice(_NOUN)}"
        if name not in taken:
            return name
    # fallback
    base = "Player"
    i = 1
    name = base
    while name in taken:
        i += 1
        name = f"{base}{i}"
    return name
