#set document(title: "DoppelbotSL Documentation", author: "DoppelbotSL Team")
#set page(
  paper: "us-letter",
  margin: (x: 1.2in, y: 1in),
  numbering: "1",
  number-align: center,
)
#set text(font: "New Computer Modern", size: 11pt)
#set heading(numbering: "1.1")
#set par(justify: true, leading: 0.65em)

#show heading.where(level: 1): it => {
  v(1.5em)
  text(size: 16pt, weight: "bold", it)
  v(0.5em)
}

#show heading.where(level: 2): it => {
  v(1em)
  text(size: 13pt, weight: "bold", it)
  v(0.3em)
}

#show heading.where(level: 3): it => {
  v(0.8em)
  text(size: 11.5pt, weight: "bold", it)
  v(0.2em)
}

#show raw.where(block: true): it => {
  block(
    fill: rgb("#1e1e2e"),
    radius: 4pt,
    inset: 10pt,
    width: 100%,
    text(fill: rgb("#cdd6f4"), font: "Courier New", size: 9.5pt, it)
  )
}

#show raw.where(block: false): it => {
  box(
    fill: rgb("#313244"),
    radius: 3pt,
    inset: (x: 4pt, y: 2pt),
    text(fill: rgb("#cdd6f4"), font: "Courier New", size: 9pt, it)
  )
}

// Title page
#align(center)[
  #v(2in)
  #text(size: 28pt, weight: "bold")[DoppelbotSL]
  #v(0.4em)
  #text(size: 15pt, fill: rgb("#888888"))[Technical Documentation]
  #v(1.5in)
  #text(size: 11pt, fill: rgb("#aaaaaa"))[
    A multiplayer social-deduction chat game built for research. \
    Human players and AI bots share a chat room. Players must \
    identify and vote out the AI participants before the rounds run out.
  ]
]

#pagebreak()

#outline(title: "Table of Contents", depth: 2, indent: 1.5em)

#pagebreak()

= Overview

DoppelbotSL is a browser-based social deduction game designed for research into human-AI interaction. A group of human players joins a shared chat room, and the server quietly adds one AI bot for every human participant. All players, human and bot alike, receive randomly generated code names so nobody can tell who is who. Players chat freely, then vote to eliminate whoever they think is a bot. The team that outlasts the other wins.

The project is split into a Python backend built on FastAPI and a plain HTML/JS/CSS frontend. There is no JavaScript framework on the client side, which keeps things simple and easy to audit. The backend stores all chat messages and player registration data in a local SQLite database so researchers can examine the conversation logs afterward.

== Design Goals

The game was built with a few priorities in mind:

- *Anonymity by default.* Real player names are never shown in chat. Every participant gets a randomly generated two-word code name like `CrimsonBadger` or `LunarFox`. This prevents social cues from leaking into the experiment.

- *Pluggable AI.* The `src/ai/shadows.py` file is a single, clearly marked hook where a researcher can drop in a real language model. The rest of the game does not care what the AI does internally.

- *Persistent data.* Every message and every player registration is written to SQLite so research teams can reconstruct full session logs without relying on in-memory state.

- *Minimal dependencies.* The backend runs on FastAPI and Uvicorn with very few additional libraries. The frontend has no build step.

== Tech Stack

#table(
  columns: (auto, 1fr),
  stroke: 0.5pt + rgb("#555555"),
  inset: 8pt,
  fill: (_, row) => if row == 0 { rgb("#313244") } else { none },
  table.header([*Layer*], [*Technology*]),
  [Backend], [Python 3.11+, FastAPI, WebSockets],
  [Frontend], [Vanilla JavaScript, HTML5, CSS3],
  [Database], [SQLite with WAL mode, background thread writer],
  [AI Interface], [OpenAI GPT-4o-mini via `src/ai/shadows.py`, with built-in content moderation],
  [Server], [Uvicorn (ASGI)],
)

#pagebreak()

= Project Structure

```
DoppelbotSL/
├── frontend/
│   ├── index.html          # Single-page app shell
│   ├── app.js              # All client-side game logic
│   └── style.css           # Styles
├── resources/
│   └── requirements.txt    # Python dependencies
└── src/
    ├── backend_server.py   # FastAPI entry point and app setup
    ├── ai/
    │   └── shadows.py      # AI bot manager (plug your LLM in here)
    ├── backend/
    │   └── persistence.py  # SQLite writer (Sink class)
    └── game/
        ├── api.py          # REST endpoints
        ├── constants.py    # Game parameters and phase names
        ├── engine.py       # Phase transitions and vote resolution
        ├── state.py        # Player and RoomState dataclasses
        ├── util.py         # Code-name generator and helpers
        └── ws.py           # WebSocket connection handler
```

Each folder has a focused responsibility. The `game/` package contains all the core game logic. The `ai/` package is isolated so a researcher can swap in a new language model without touching anything else. The `backend/` package handles data persistence.

#pagebreak()

= Setup and Installation

== Requirements

- Python 3.11 or newer
- A terminal and a browser

== Install

```bash
cd DoppelbotSL

# Create a virtual environment
python -m venv .venv

# Activate it (Windows)
.venv\Scripts\activate

# Activate it (macOS / Linux)
source .venv/bin/activate

# Install dependencies
pip install -r resources/requirements.txt
```

== Configure the API Key

Before running the server you need an OpenAI API key. Copy the example file and fill it in:

```bash
cp .env.example .env
# then open .env and replace sk-... with your actual key
```

The `.env` file is gitignored and will never be committed.

== Run the Server

```bash
uvicorn src.backend_server:app --reload --app-dir src
```

Then open `http://localhost:8000` in a browser. The frontend is served automatically by FastAPI's static file mount. There is no separate build step for the client.

== Configuration

All tunable game parameters live in `src/game/constants.py`:

```python
MIN_PLAYERS   = 3      # Minimum humans needed to start
MAX_PLAYERS   = 5      # Maximum humans per room
TOTAL_ROUNDS  = 3      # Round limit (safety cutoff)
CHAT_SECONDS  = 120    # Chat phase duration in seconds
VOTE_SECONDS  = 200    # Vote phase duration in seconds
```

Edit these values and restart the server to change how the game plays.

#pagebreak()

= How the Game Works

== Player Flow

#set enum(numbering: "1.")

+ *Register.* When a player first opens the site, they fill out a short form with a display name, an optional researcher-assigned participant ID, their age, and a consent checkbox. This data is stored in SQLite and never shown to other players.

+ *Lobby.* After registering, the player picks or creates a room. The first person to join a room becomes the host. Everyone else who joins sees the lobby and waits for the host to press Start.

+ *Game Start.* When the host starts the game, the server adds one AI bot for every human in the room. A room of 4 humans becomes 8 participants: 4 humans and 4 bots, all with unique randomly generated code names. There is no visual difference between humans and bots on the client side.

+ *Chat Phase (120 seconds).* All non-eliminated participants can send messages. When a human sends a message, the server forwards it to all connected clients and then calls the AI hook so bots can respond.

+ *Vote Phase (200 seconds).* Each non-eliminated human votes to eliminate one participant. Eliminated players cannot vote. Voting ends when all eligible voters have submitted, or when the timer runs out. The participant with the most votes is eliminated. Ties are broken randomly.

+ *Repeat.* The chat and vote phases alternate. Each pair of phases counts as one round.

+ *Score Screen.* The game ends when the number of surviving players equals the original number of humans (meaning the correct number of eliminations happened) or when the round limit is reached. The score screen reveals which participants were bots, who survived, and who won.

== Win Conditions

- *Humans win* if all AI bots are eliminated before the game ends.
- *AI wins* if any bot survives to the final reveal.

== State Machine

The room moves through phases in this order:

```
LOBBY -> CHAT -> VOTE -> CHAT -> VOTE -> ... -> SCORE
                  ^_____________|
                  (repeats each round)
```

The transition from VOTE back to CHAT happens automatically after `resolve_vote_and_eliminate` runs, as long as the game has not ended. The SCORE phase is a terminal state; the room stays there until all clients navigate away.

#pagebreak()

= Backend Architecture

== Entry Point: `backend_server.py`

The FastAPI application is created in `backend_server.py`. On startup it initializes two shared resources:

- *`Sink`*: The SQLite background writer. Started immediately so that player registrations and messages are never lost.
- *`ShadowAIManager`*: The AI bot manager. Holds references to any AI agents currently in a game and calls back into the server's `send_chat` function when a bot needs to send a message.

Both of these are stored on `app.state` so they can be accessed from any route handler or WebSocket handler without resorting to global variables.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.sink = Sink()
    app.state.shadow_ai = ShadowAIManager(send_chat)
    yield
    app.state.sink.shutdown()
```

The `broadcast` function in this file iterates over all WebSocket connections for a given room and sends a JSON payload to each one. If a send fails, the connection is removed and the player is marked as disconnected.

== In-Memory State

All active game state lives in three module-level dictionaries in `src/game/state.py`:

```python
rooms: Dict[str, RoomState] = {}
room_connections: Dict[str, Dict[str, object]] = defaultdict(dict)
room_last_activity: Dict[str, float] = defaultdict(lambda: time.time())
```

`rooms` maps a room ID to its `RoomState`. `room_connections` maps a room ID to a dictionary of player IDs and their WebSocket objects. `room_last_activity` tracks the last time anything happened in a room, which is useful for cleanup.

*Note:* because state lives in memory, restarting the server clears all active games. The SQLite database retains registration and message history across restarts.

#pagebreak()

= Data Models

== Player

Defined in `src/game/state.py`.

#table(
  columns: (auto, auto, 1fr),
  stroke: 0.5pt + rgb("#555555"),
  inset: 8pt,
  fill: (_, row) => if row == 0 { rgb("#313244") } else { none },
  table.header([*Field*], [*Type*], [*Description*]),
  [`player_id`], [`str`], [UUID generated at join time. Used as the primary key for this player.],
  [`username`], [`str`], [Randomly generated code name shown in chat, e.g. `CrimsonBadger`.],
  [`display_name`], [`str`], [Real name entered at registration. Stored in SQLite, never shown in chat.],
  [`participant_id`], [`str`], [Researcher-assigned ID, optional. Stored for research use only.],
  [`age`], [`int`], [Age entered at registration. Stored for research use only.],
  [`is_ai`], [`bool`], [True if this slot is controlled by the AI manager. Server-only; never sent to clients.],
  [`connected`], [`bool`], [Whether the player's WebSocket is currently open.],
  [`eliminated`], [`bool`], [Whether this player has been voted out.],
)

== RoomState

Defined in `src/game/state.py`.

#table(
  columns: (auto, auto, 1fr),
  stroke: 0.5pt + rgb("#555555"),
  inset: 8pt,
  fill: (_, row) => if row == 0 { rgb("#313244") } else { none },
  table.header([*Field*], [*Type*], [*Description*]),
  [`room_id`], [`str`], [Normalized room identifier (uppercased).],
  [`host_player_id`], [`str?`], [Player ID of the first person to join. Only the host can start the game.],
  [`phase`], [`str`], [Current game phase: `LOBBY`, `CHAT`, `VOTE`, or `SCORE`.],
  [`round`], [`int`], [Current round number. Starts at 1 when the game begins.],
  [`players`], [`Dict[str, Player]`], [All players in the room, keyed by `player_id`. Includes bots.],
  [`chat_ends_at`], [`int?`], [Unix timestamp when the chat phase will end. Null outside of chat phases.],
  [`vote_ends_at`], [`int?`], [Unix timestamp when the vote phase will end. Null outside of vote phases.],
  [`phase_task_id`], [`int`], [Incremented each time the phase changes, used to cancel stale timer tasks.],
  [`votes_by_round`], [`Dict[int, Dict[str, str]]`], [Maps round number to a dict of voter ID to target ID.],
  [`ai_player_id`], [`str?`], [Server-only field tracking one AI player. Not exposed in snapshots.],
)

== Public Snapshot

When the server sends room state to clients, it calls `room_public_snapshot(room)` which strips all server-only fields (`is_ai`, `display_name`, `participant_id`, `age`, `ai_player_id`) before sending. Clients only see:

```json
{
  "roomId": "ROOM1",
  "phase": "CHAT",
  "round": 1,
  "hostPlayerId": "uuid...",
  "players": [
    {
      "playerId": "uuid...",
      "username": "CrimsonBadger",
      "connected": true,
      "isHost": true,
      "eliminated": false
    }
  ],
  "minPlayers": 3,
  "maxPlayers": 5,
  "totalRounds": 3,
  "chatEndsAt": 1720000000
}
```

#pagebreak()

= REST API

All REST endpoints are registered by the `register_api` function in `src/game/api.py`.

== List Rooms

```
GET /api/rooms
```

Returns a list of all rooms that currently exist in memory, sorted by most recent activity.

*Response:*
```json
[
  {
    "id": "ROOM1",
    "users": 4,
    "lastActivity": 12,
    "phase": "CHAT",
    "round": 1
  }
]
```

`lastActivity` is the number of seconds since something happened in the room.

== Create a Room

```
POST /api/rooms
Content-Type: application/json

{ "id": "ROOM1" }
```

Creates a room if it does not already exist. Room IDs are normalized to uppercase, so `room1` and `ROOM1` are the same room.

*Response:*
```json
{ "id": "ROOM1" }
```

== Join a Room

```
POST /api/rooms/{room_id}/join
Content-Type: application/json

{
  "displayName": "Alice",
  "participantId": "P001",
  "age": 22
}
```

Adds the player to the room. The server generates a UUID for the player and picks a random code name. The first player to join becomes the host.

*Validation:*
- `displayName` is required. An empty value returns 400.
- `displayName` must be unique within the room (case-insensitive). If a human player with that name already exists, the request is rejected with 400. This prevents the same person from joining twice.
- The room must not already be at capacity (`MAX_PLAYERS`).

*Response:*
```json
{
  "roomId": "ROOM1",
  "playerId": "uuid...",
  "username": "LunarFox",
  "displayName": "Alice",
  "isHost": true,
  "snapshot": { ... }
}
```

The `snapshot` field contains the full public room state so the client can render the lobby immediately.

== Start the Game

```
POST /api/rooms/{room_id}/start
Content-Type: application/json

{ "playerId": "uuid..." }
```

Only the host can call this. Requires at least `MIN_PLAYERS` human players and no more than `MAX_PLAYERS`. Fails if the game has already started.

On success, the server:
1. Removes any leftover AI players from a previous game.
2. Resets all human players (clears `eliminated` flag).
3. Adds one AI bot per human, each with a unique code name.
4. Calls `enter_chat_phase` to start the first round.

*Response:*
```json
{ "ok": true, "snapshot": { ... } }
```

== Get Chat History

```
GET /api/rooms/{room_id}/history?limit=50
```

Returns the most recent messages from SQLite for the given room.

*Response:*
```json
{
  "roomId": "ROOM1",
  "messages": [
    { "user": "LunarFox", "text": "Hello!", "ts": 1720000000 }
  ]
}
```

#pagebreak()

= WebSocket API

Connect with:
```
ws://localhost:8000/ws/{room_id}/{player_id}
```

The player must have already joined via `POST /api/rooms/{id}/join` before connecting. If the `player_id` is not recognized, the server sends an error and closes the connection.

On a successful connection, the server immediately sends:
- A `room_snapshot` message with the current room state.
- A `history` message with recent chat messages.
- A `system` message to all clients announcing the player joined.

== Messages You Send

=== send_chat

Send a chat message during the CHAT phase.

```json
{
  "type": "send_chat",
  "data": { "text": "Hello everyone" }
}
```

Will be rejected if the room is not in CHAT phase or if the sending player is eliminated. Empty messages are silently ignored without triggering the AI hook.

=== cast_vote

Cast a vote during the VOTE phase.

```json
{
  "type": "cast_vote",
  "data": { "targetPlayerId": "uuid..." }
}
```

Eliminated players cannot vote. Players cannot vote for themselves. If all eligible voters have submitted their votes before the timer expires, vote resolution happens immediately rather than waiting for the timer.

=== end_chat

Host-only shortcut to skip the rest of the chat phase and move to voting.

```json
{ "type": "end_chat" }
```

=== request_snapshot

Ask the server to resend the current room state. Useful if the client suspects it is out of sync.

```json
{ "type": "request_snapshot" }
```

=== typing

Broadcast a typing indicator to other clients.

```json
{
  "type": "typing",
  "data": { "isTyping": true }
}
```

== Messages You Receive

=== room_snapshot

Full public room state. Sent on connection, after each phase change, and after any player joins or leaves.

```json
{
  "type": "room_snapshot",
  "data": { ... }
}
```

=== phase_changed

Sent whenever the game moves to a new phase.

```json
{
  "type": "phase_changed",
  "data": { "phase": "VOTE", "round": 1 }
}
```

=== chat_message

A new chat message arrived.

```json
{
  "type": "chat_message",
  "data": { "user": "CrimsonBadger", "text": "Anyone else suspicious?", "ts": 1720000000 }
}
```

=== elimination

A player was eliminated at the end of a vote phase.

```json
{
  "type": "elimination",
  "data": {
    "round": 1,
    "eliminatedPlayerId": "uuid...",
    "eliminatedUsername": "LunarFox"
  }
}
```

If nobody received any votes (for example, nobody voted), `eliminatedPlayerId` and `eliminatedUsername` will be `null`.

=== vote_progress

Sent after each vote is cast, showing how many votes have been submitted so far.

```json
{
  "type": "vote_progress",
  "data": { "round": 1, "submitted": 2, "total": 4 }
}
```

=== game_over

Sent when the game reaches the SCORE phase. Reveals which players were bots and who won.

```json
{
  "type": "game_over",
  "data": {
    "aiUsernames": ["LunarFox", "OrbitRaven"],
    "aiWon": false,
    "winner": "humans",
    "remaining": [
      { "username": "CrimsonBadger", "isAi": false }
    ],
    "eliminated": [
      { "username": "LunarFox", "isAi": true },
      { "username": "OrbitRaven", "isAi": true }
    ]
  }
}
```

=== system

An informational message not tied to any player action, like a player joining or leaving.

```json
{ "type": "system", "text": "CrimsonBadger joined." }
```

=== error

Sent when a client message is rejected.

```json
{ "type": "error", "text": "Chat is not enabled right now." }
```

#pagebreak()

= Game Engine

`src/game/engine.py` handles all phase transitions and vote resolution.

== Phase Functions

=== `enter_chat_phase(room, broadcast)`

Transitions the room to CHAT, sets the `chat_ends_at` timestamp, increments `phase_task_id`, and schedules a timer that will call `enter_vote_phase` after `CHAT_SECONDS`. The `phase_task_id` mechanism ensures that if a phase changes early (for example, the host skips to voting), the stale timer task checks the ID and does nothing when it eventually fires.

=== `enter_vote_phase(room, broadcast)`

Transitions the room to VOTE, sets `vote_ends_at`, and clears the vote tally for the new round. Schedules a timer to call `resolve_vote_and_eliminate` after `VOTE_SECONDS`.

=== `resolve_vote_and_eliminate(room, broadcast)`

Called either when the vote timer expires or when all eligible voters have submitted their votes. Steps:

1. Increments `phase_task_id` to cancel the pending timer if still running.
2. Tallies votes from `room.votes_by_round[round]`.
3. Picks the player with the most votes. Ties are broken by random selection.
4. Marks that player as `eliminated = True`.
5. Broadcasts an `elimination` event.
6. Checks the end condition: if the number of surviving players is at or below the original human count, or if the round limit has been reached, transitions to SCORE and broadcasts `game_over`.
7. Otherwise, increments the round counter and calls `enter_chat_phase` to start the next round.

== Helper Functions

=== `eligible_players(room)`

Returns all players who are not eliminated. Used to determine the survivor list.

=== `eligible_voter_ids(room)`

Returns the set of player IDs for non-eliminated, non-AI players. Only humans vote. This count is used to determine when all votes are in.

=== `compute_top_voted(votes)`

Given a `{voter_id: target_id}` dict, returns the `target_id` with the most votes. Randomly picks from tied targets.

#pagebreak()

= AI Integration

== How AI Players Work

When the host starts a game, the server adds one `Player` object per human with `is_ai=True`. These bot players are indistinguishable from human players on the client side. They appear in the player list, can have votes cast against them, and send messages through the same broadcast path as humans.

The `ShadowAIManager` in `src/ai/shadows.py` is responsible for generating bot responses. Every time a human sends a non-empty chat message during the CHAT phase, `ws.py` fires `shadow_ai.on_room_message(...)` as a background task using `asyncio.create_task`. This means the AI response never blocks the player's WebSocket connection while the model is thinking.

== Current Implementation

The bot uses OpenAI's `gpt-4o-mini` model. The API key is loaded from the `.env` file at startup. On each human message:

1. A random check against `RESPONSE_CHANCE` decides whether any bot responds at all (default 65%).
2. If responding, one alive AI player is chosen at random.
3. The last `HISTORY_WINDOW` messages are formatted as a plain transcript and passed to the model along with a system prompt.
4. The coroutine sleeps for a random duration between `REPLY_DELAY[0]` and `REPLY_DELAY[1]` seconds to simulate a human typing.
5. After the sleep, if the room has moved out of CHAT phase (e.g. the timer expired), the response is discarded.
6. The model's reply is run through OpenAI's moderation API. If it is flagged, it is dropped and logged. Otherwise it is sent.

== Tuning Knobs

All adjustable parameters are at the top of `src/ai/shadows.py`:

```python
MODEL           = "gpt-4o-mini"   # swap to "gpt-4o" for a smarter bot
RESPONSE_CHANCE = 0.65            # probability any given human message gets a reply
REPLY_DELAY     = (1.5, 4.0)      # seconds of fake "typing" delay (min, max)
MAX_TOKENS      = 80              # keep replies short and chat-like
HISTORY_WINDOW  = 20              # how many recent messages to include as context
```

Changing these values takes effect after restarting the server.

== Content Moderation

Two layers of content filtering are active at all times:

- *System prompt rules.* The model is instructed to never use profanity, slurs, or offensive language, and to avoid violence, sexual content, drugs, self-harm, or any topic inappropriate for a research setting. If the conversation moves toward any of those topics, the bot is told to redirect with a neutral comment about the game.

- *OpenAI moderation API.* Every generated reply is passed through `client.moderations.create(input=reply)` before it is sent. If any moderation category is flagged, the message is silently dropped and a line is printed to the server console:

```
[ShadowAI] Moderation blocked reply from CrimsonBadger: 'the flagged text'
```

This two-layer approach means even a cleverly crafted prompt from a human player that tricks the model into producing problematic output will still be caught before it reaches the chat.

== Key Variables

#table(
  columns: (auto, 1fr),
  stroke: 0.5pt + rgb("#555555"),
  inset: 8pt,
  fill: (_, row) => if row == 0 { rgb("#313244") } else { none },
  table.header([*Variable*], [*Description*]),
  [`human_text`], [The exact text the human player just typed.],
  [`conversation_history`], [A chronological list of `{"user", "text", "ts"}` dicts for the whole room.],
  [`game_rules`], [A plain-English string describing the game's rules, suitable for use in a prompt.],
  [`room.players`], [All `Player` objects in the room, including bots. Filter with `p.is_ai` and `p.eliminated`.],
)

== Resetting Between Games

`ShadowAIManager.reset_for_room()` is called each time the host starts a new game. This clears any state the manager holds from a previous game. If you add per-game memory to the manager, make sure to clear it here.

#pagebreak()

= Persistence

`src/backend/persistence.py` contains a `Sink` class that writes to SQLite on a background thread so database writes never block the async event loop.

== Database Location

The database file is created at `src/backend/game.db` relative to the `persistence.py` file.

== Schema

=== messages table

#table(
  columns: (auto, auto, 1fr),
  stroke: 0.5pt + rgb("#555555"),
  inset: 8pt,
  fill: (_, row) => if row == 0 { rgb("#313244") } else { none },
  table.header([*Column*], [*Type*], [*Description*]),
  [`id`], [`INTEGER`], [Auto-incrementing primary key.],
  [`room_id`], [`TEXT`], [The room this message belongs to.],
  [`user_id`], [`TEXT`], [The code name of the sender (e.g. `CrimsonBadger`).],
  [`text`], [`TEXT`], [Message content.],
  [`ts`], [`INTEGER`], [Unix timestamp.],
)

=== players table

#table(
  columns: (auto, auto, 1fr),
  stroke: 0.5pt + rgb("#555555"),
  inset: 8pt,
  fill: (_, row) => if row == 0 { rgb("#313244") } else { none },
  table.header([*Column*], [*Type*], [*Description*]),
  [`player_id`], [`TEXT`], [UUID primary key, generated at join time.],
  [`room_id`], [`TEXT`], [Room the player joined.],
  [`username`], [`TEXT`], [Auto-generated code name.],
  [`display_name`], [`TEXT`], [Real name from registration form.],
  [`participant_id`], [`TEXT`], [Researcher-assigned ID, if provided.],
  [`age`], [`INTEGER`], [Age from registration form.],
  [`joined_at`], [`INTEGER`], [Unix timestamp of when the player joined.],
)

== How Writes Work

The `Sink` class uses a `queue.Queue` and a daemon thread. Calling `emit_message()` or `emit_player()` puts a tuple onto the queue and returns immediately. The background thread pops items off the queue and commits them to SQLite. This means writes are slightly delayed but the async event loop is never blocked.

If the server is shut down cleanly, `Sink.shutdown()` signals the thread to stop and waits up to two seconds for it to finish. Any messages still in the queue at that point may be lost, so do not cut power mid-game if data integrity matters.

== Reading Messages

`Sink.recent_messages(room_id, limit)` performs a synchronous SQLite read. This is called from async handlers but is fast enough for the current use case since it is just a simple indexed query. If the server handles very high volume, consider moving this to an async driver.

#pagebreak()

= Frontend

The frontend is a single-page app served directly by FastAPI's `StaticFiles` mount at the root path. There is no build step and no framework.

== Screens

The app has three screens that swap in and out by toggling CSS classes:

- *Rules screen* (`#screenRules`): Shown first. Explains the game and has a button to start playing.
- *App screen* (`#screenApp`): The main game view with the chat log, player list, room selection, and vote overlay.
- *About screen* (`#screenAbout`): A short description of the project.

== Overlays

Several modal dialogs appear on top of the current screen:

- *Registration overlay*: Shown on first load. Collects display name, participant ID, age, and consent.
- *Room Select overlay*: Lets players pick an existing room or create a new one.
- *Vote overlay*: Shows during VOTE phase. Lists all non-eliminated players the current player can vote for.
- *Score overlay*: Shown when `game_over` is received. Reveals the AI identities and the winner.

== WebSocket Events

`app.js` opens one WebSocket connection per game session. Incoming messages are dispatched by `type`:

- `room_snapshot` updates the player list and timers.
- `chat_message` appends a message to the chat log.
- `phase_changed` switches the UI between chat and vote modes.
- `elimination` shows who was voted out.
- `vote_progress` updates the vote counter in the vote overlay.
- `game_over` closes the vote overlay and shows the score screen.
- `system` appends a system notice to the chat log.

== Session Persistence

When a player successfully joins a room, `app.js` writes their session to `localStorage` under the key `doppelbot_session`:

```json
{
  "roomId": "ROOM1",
  "playerId": "uuid...",
  "username": "CrimsonBadger",
  "isHost": false,
  "registrationData": { "displayName": "Alice", "participantId": "P001", "age": 22 }
}
```

On page load, the app checks for a saved session. If one exists, it skips the registration form and room select overlay entirely and reconnects the existing WebSocket using the saved `playerId`. This prevents a page refresh from creating a duplicate join, which would be blocked by the server anyway since the display name is already taken in that room.

The session is cleared when the player clicks Disconnect or Play Again.

== Timers

Two countdown timers run on the client: one for the chat phase and one for the vote phase. They count down from the server-provided `chatEndsAt` and `voteEndsAt` timestamps rather than from a locally tracked duration, so they stay in sync even if a player refreshes the page.

== Code Name Generation

Code names are generated server-side in `src/game/util.py` by combining one adjective and one noun from fixed lists.

```python
_ADJ = ["Orbit", "Pebble", "Crimson", "Velvet", "Neon", "Silver", ...]
_NOUN = ["Fox", "Comet", "Otter", "Wisp", "Raven", "Tiger", ...]
```

The generator tries up to 200 random combinations before falling back to `Player2`, `Player3`, etc. All taken names (both human and AI) are checked before assigning a new one, so there are no duplicates within a room.

#pagebreak()

= Security Notes

A few things worth knowing if you plan to run this beyond a local research lab:

- *CORS is fully open.* `backend_server.py` adds `CORSMiddleware` with `allow_origins=["*"]`. This is fine for localhost experiments but should be locked down to specific origins in a production deployment.

- *No authentication.* The server trusts the `player_id` and `room_id` values sent by the client. There is no token or session verification beyond checking that the `player_id` exists in the room's player dict. A motivated actor could send arbitrary player IDs.

- *AI identity is hidden, not cryptographically protected.* The `is_ai` flag is filtered out of public snapshots, but the raw in-memory state is not encrypted. If a player can run JavaScript in the browser console they cannot see `is_ai`, but server-side inspection would reveal it.

- *SQLite with WAL mode.* WAL (write-ahead logging) improves read concurrency, but the database is a single file on disk. Back it up if the research data matters.

- *AI content moderation.* Bot replies pass through OpenAI's moderation API before being sent. Flagged messages are silently dropped and logged to the server console. The system prompt also instructs the model to stay on topic and avoid inappropriate content. Neither layer is a substitute for researcher supervision during live sessions.

#pagebreak()

= Quick Reference

== Phase Constants

#table(
  columns: (auto, auto),
  stroke: 0.5pt + rgb("#555555"),
  inset: 8pt,
  fill: (_, row) => if row == 0 { rgb("#313244") } else { none },
  table.header([*Constant*], [*Value*]),
  [`PHASE_LOBBY`], [`"LOBBY"`],
  [`PHASE_CHAT`], [`"CHAT"`],
  [`PHASE_VOTE`], [`"VOTE"`],
  [`PHASE_SCORE`], [`"SCORE"`],
)

== Default Game Parameters

#table(
  columns: (auto, auto, 1fr),
  stroke: 0.5pt + rgb("#555555"),
  inset: 8pt,
  fill: (_, row) => if row == 0 { rgb("#313244") } else { none },
  table.header([*Constant*], [*Default*], [*Description*]),
  [`MIN_PLAYERS`], [`3`], [Minimum humans required to start.],
  [`MAX_PLAYERS`], [`5`], [Maximum humans allowed in a room.],
  [`TOTAL_ROUNDS`], [`3`], [Maximum number of vote rounds before game ends.],
  [`CHAT_SECONDS`], [`120`], [Duration of each chat phase.],
  [`VOTE_SECONDS`], [`200`], [Duration of each vote phase.],
)

== REST Endpoints Summary

#table(
  columns: (auto, auto, 1fr),
  stroke: 0.5pt + rgb("#555555"),
  inset: 8pt,
  fill: (_, row) => if row == 0 { rgb("#313244") } else { none },
  table.header([*Method*], [*Path*], [*Description*]),
  [`GET`], [`/api/rooms`], [List all active rooms.],
  [`POST`], [`/api/rooms`], [Create a room.],
  [`POST`], [`/api/rooms/{id}/join`], [Join a room. Returns player credentials.],
  [`POST`], [`/api/rooms/{id}/start`], [Host starts the game.],
  [`GET`], [`/api/rooms/{id}/history`], [Fetch recent chat messages.],
)

== WebSocket Message Types Summary

#table(
  columns: (auto, auto, 1fr),
  stroke: 0.5pt + rgb("#555555"),
  inset: 8pt,
  fill: (_, row) => if row == 0 { rgb("#313244") } else { none },
  table.header([*Direction*], [*Type*], [*Purpose*]),
  [Send], [`send_chat`], [Send a chat message.],
  [Send], [`cast_vote`], [Vote to eliminate a player.],
  [Send], [`end_chat`], [Host skips to vote phase.],
  [Send], [`request_snapshot`], [Re-fetch current room state.],
  [Send], [`typing`], [Broadcast typing indicator.],
  [Receive], [`room_snapshot`], [Full room state update.],
  [Receive], [`phase_changed`], [Phase transition notification.],
  [Receive], [`chat_message`], [New chat message.],
  [Receive], [`elimination`], [A player was eliminated.],
  [Receive], [`vote_progress`], [Running vote tally.],
  [Receive], [`game_over`], [Game ended with full reveal.],
  [Receive], [`system`], [Informational server message.],
  [Receive], [`error`], [Rejected client message.],
)
