# DoppelbotSL

A multiplayer social-deduction chat game built for research. Human players and AI bots share a chat room — players must identify and vote out the AI participants before the rounds run out.

---

## How the Game Works

1. **Register** — Each player enters a display name, participant ID, age, and gives consent before joining.
2. **Lobby** — Players join a room and wait for the host to start. Each player is assigned a random code name (e.g. *CrimsonBadger*) that hides their real identity in chat.
3. **Game start** — The server secretly adds one AI bot per human player. A room of 4 humans becomes 8 participants: 4 humans + 4 AIs, all with indistinguishable code names.
4. **Chat phase** (120 s) — All non-eliminated participants can send messages. AI bots respond automatically.
5. **Vote phase** (200 s) — Players vote to eliminate who they think is an AI. The participant with the most votes is eliminated.
6. **Repeat** — Chat and vote alternate until the elimination count equals the number of original human players (e.g. 4 humans → 4 eliminations, then game ends).
7. **Score screen** — The game reveals which participants were AI, who survived, and who won.

**Humans win** if all AI players are eliminated before the game ends.
**AI wins** if any AI survives to the final reveal.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, FastAPI, WebSockets |
| Frontend | Vanilla JS, HTML, CSS (no framework) |
| Database | SQLite (WAL mode, background thread writer) |
| AI hooks | `src/ai/shadows.py` — stub ready for LLM integration |
| Server | Uvicorn |

---

## Project Structure

```
DoppelbotSL/
├── frontend/
│   ├── index.html          # Single-page app
│   ├── app.js              # All client-side logic
│   └── style.css
├── resources/
│   └── requirements.txt    # Python dependencies
└── src/
    ├── backend_server.py   # FastAPI app entry point
    ├── ai/
    │   └── shadows.py      # AI bot hooks (implement here)
    ├── backend/
    │   └── persistence.py  # SQLite Sink (messages + players table)
    └── game/
        ├── api.py          # REST endpoints (rooms, join, start)
        ├── constants.py    # Timers, player limits, round count
        ├── engine.py       # Phase transitions and vote resolution
        ├── state.py        # RoomState and Player dataclasses
        ├── util.py         # Code-name generator, helpers
        └── ws.py           # WebSocket handler
```

---

## Setup

### Requirements

- Python 3.11+
- A virtual environment (recommended)

### Install

```bash
cd DoppelbotSL
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r resources/requirements.txt
```

### Run

```bash
uvicorn src.backend_server:app --reload --app-dir src
```

Then open [http://localhost:8000](http://localhost:8000) in a browser.

> The frontend is served automatically from the `frontend/` directory via FastAPI's `StaticFiles` mount.

---

## Configuration

Edit `src/game/constants.py` to adjust game parameters:

```python
MIN_PLAYERS   = 3      # Minimum humans to start
MAX_PLAYERS   = 5      # Maximum humans per room
TOTAL_ROUNDS  = 3      # Round limit (safety cutoff)
CHAT_SECONDS  = 120    # Chat phase duration
VOTE_SECONDS  = 200    # Vote phase duration
```

---

## API Reference

### REST

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/rooms` | List all active rooms |
| `POST` | `/api/rooms` | Create a room (`{"id": "ROOM1"}`) |
| `POST` | `/api/rooms/{id}/join` | Join a room, returns player credentials |
| `POST` | `/api/rooms/{id}/start` | Host starts the game |
| `GET` | `/api/rooms/{id}/history` | Fetch recent chat messages |

**Join payload:**
```json
{
  "displayName": "Alice",
  "participantId": "P001",
  "age": 22
}
```

### WebSocket

Connect at `ws://localhost:8000/ws/{room_id}/{player_id}`

**Send:**

| Event | Payload | Description |
|---|---|---|
| `send_chat` | `{"text": "Hello"}` | Send a chat message |
| `cast_vote` | `{"targetPlayerId": "..."}` | Vote to eliminate a player |
| `end_chat` | — | Host skips to vote phase |
| `request_snapshot` | — | Re-fetch room state |

**Receive:**

| Event | Description |
|---|---|
| `room_snapshot` | Full room state (players, phase, timers) |
| `phase_changed` | Phase transition notification |
| `chat_message` | A new chat message |
| `elimination` | A player was eliminated |
| `vote_progress` | Running vote tally |
| `game_over` | Game ended — includes AI reveal and scores |

---

## Research Data

Every join is persisted to SQLite (`src/backend/game.db`):

| Field | Source |
|---|---|
| `player_id` | Server-generated UUID |
| `room_id` | Room the player joined |
| `username` | Auto-generated code name |
| `display_name` | From registration form |
| `participant_id` | From registration form |
| `age` | From registration form |
| `joined_at` | Unix timestamp |

Chat messages are stored in a separate `messages` table with `room_id`, `user` (code name), `text`, and `ts`.

---

## Implementing AI Logic (for Dan)

All AI behavior lives in `src/ai/shadows.py`. The key hook is `on_room_message`, called every time a human sends a chat message during the CHAT phase.

```python
async def on_room_message(self, room_id, human_sender_player_id,
                           human_sender_username, human_text,
                           room, conversation_history, game_rules):
    # Dan's variables:
    # human_text          -> the message just sent by a human
    # conversation_history -> list of {"user", "text", "ts"} dicts
    # game_rules           -> string describing the full game loop
    #
    # Pick an alive AI player and respond:
    #   alive_ais = [p for p in room.players.values() if p.is_ai and not p.eliminated]
    #   ai_player = random.choice(alive_ais)
    #   await self._send_chat(room_id, ai_player.username, reply)
```

The placeholder currently echoes a message from a randomly selected alive AI. Replace the placeholder with a real LLM call to make the bots convincing.

> AI players are real participants in `room.players` with `is_ai=True`. They appear in chat and in the vote list. Their identity is hidden from the frontend — clients cannot distinguish them from human players.

---

## Game State Machine

```
LOBBY → CHAT → VOTE → CHAT → VOTE → ... → SCORE
                 ↑_____________|
                 (repeats each round)
```

The game ends (moves to SCORE) when:
- The number of surviving players equals the original human count, **or**
- The round limit (`TOTAL_ROUNDS`) is reached
