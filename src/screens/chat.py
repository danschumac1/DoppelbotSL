# chat.py
"""
Streamlit Chat Room — simple multi-user chat with rooms (SQLite backend)

Use:
  from screens.chat import chat_main
  ...
  if st.session_state.current_screen == "CHAT":  # or Screen.CHAT
      chat_main()

Notes
- Stores messages in SQLite (path via CHAT_DB_PATH env var; default: chat.db).
- Uses st.session_state for UI state. No returns.
- If PlayerState is present, default room is "lobby-{lobby_id}" and default name is code_name (or First L.).
"""

from __future__ import annotations
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import List, Tuple, Optional
from uuid import uuid4

import streamlit as st

# Optional project types (not required for basic chat to run)
try:
    from utils.states import GameState, PlayerState  # noqa: F401
except Exception:
    PlayerState = object  # type: ignore
    GameState = object    # type: ignore

DB_PATH = os.environ.get("CHAT_DB_PATH", "chat.db")
ADMIN_CLEAR_CODE = os.environ.get("CHAT_ADMIN_CODE", "")  # optional passphrase for clearing rooms
default_number_of_players = 3 # temp for now before reading from input 

# ----------------------------- DB helpers ----------------------------- #
@st.cache_resource(show_spinner=False)
def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)

    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=2000;")

    # for tracking messages 
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room TEXT NOT NULL,
            author TEXT NOT NULL,
            text TEXT NOT NULL,
            ts   REAL NOT NULL
        )
        """
    )

    # for tracking different rooms 
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rooms (
            room TEXT PRIMARY KEY,
            created_ts REAL NOT NULL,
            close_ts   REAL,
            number_of_players INTEGER
        )
        """
    )

    # for tracking room members for each room 
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS room_members (
            room TEXT NOT NULL,
            member_id TEXT NOT NULL,
            name TEXT NOT NULL,
            joined_ts REAL NOT NULL,
            PRIMARY KEY (room, member_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_room_members_room ON room_members(room)")

    # If rooms existed without close_ts, add it
    cols = {row[1] for row in conn.execute("PRAGMA table_info(rooms)").fetchall()}
    if "close_ts" not in cols:
        conn.execute("ALTER TABLE rooms ADD COLUMN close_ts REAL")

    # Helpful index for paging
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_room_ts ON messages(room, ts)")

    # reset lobbies upon restart
    _reset_all_lobbies(conn)



    conn.commit()

    _ensure_seed_data(conn)

    return conn


def _reset_all_lobbies(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM room_members")
    conn.execute("UPDATE rooms SET close_ts = NULL")
    conn.execute("DELETE FROM messages")  # optional: also clear chat logs
    conn.commit()

def _ensure_seed_data(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO rooms (room, created_ts, close_ts, number_of_players) VALUES (?, ?, NULL, ?)",
        ("general", time.time(), default_number_of_players),
    )
    conn.commit()


def _list_rooms(conn: sqlite3.Connection) -> List[str]:
    cur = conn.execute("SELECT room FROM rooms ORDER BY room ASC")
    return [r[0] for r in cur.fetchall()]


def _ensure_room(conn: sqlite3.Connection, room: str) -> None:
    room = room.strip()
    if not room:
        return
    conn.execute("INSERT OR IGNORE INTO rooms (room, created_ts, number_of_players) VALUES (?, ?, ?)", (room, time.time(), default_number_of_players))
    conn.commit()


def _add_message(conn: sqlite3.Connection, room: str, author: str, text: str) -> None:
    conn.execute(
        "INSERT INTO messages (room, author, text, ts) VALUES (?, ?, ?, ?)",
        (room, author, text, time.time()),
    )
    conn.commit()


def _get_messages(
    conn: sqlite3.Connection,
    room: str,
    limit: int = 100,
    before_ts: Optional[float] = None,
) -> List[Tuple[int, str, str, str, float]]:
    q = "SELECT id, room, author, text, ts FROM messages WHERE room=?"
    params: List[object] = [room]
    if before_ts is not None:
        q += " AND ts < ?"
        params.append(before_ts)
    q += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    # Return newest-last for display
    return list(reversed(rows))


def _clear_room(conn: sqlite3.Connection, room: str) -> None:
    conn.execute("DELETE FROM messages WHERE room=?", (room,))
    conn.commit()

def _get_room_close_at(conn: sqlite3.Connection, room: str) -> Optional[float]:
    row = conn.execute("SELECT close_ts FROM rooms WHERE room=?", (room,)).fetchone()
    return float(row[0]) if row and row[0] is not None else None

def _set_room_close_at(conn: sqlite3.Connection, room: str, ts: Optional[float]) -> None:
    _ensure_room(conn, room)  # idempotent
    conn.execute("UPDATE rooms SET close_ts=? WHERE room=?", (ts, room))
    conn.commit()

def _get_number_of_players(conn: sqlite3.Connection, room: str) -> Optional[int]:
    row = conn.execute("SELECT number_of_players FROM rooms WHERE room=?", (room,)).fetchone()
    return int(row[0]) if row and row[0] is not None else None

def _set_number_of_players(conn: sqlite3.Connection, room: str, num_players: Optional[int]) -> None:
    _ensure_room(conn, room)  # idempotent
    conn.execute("UPDATE rooms SET number_of_players=? WHERE room=?", (num_players, room))
    conn.commit()

def _add_member(conn: sqlite3.Connection, room: str, member_id: str, name: str) -> None:
    # Idempotent: one record per (room, member_id)
    conn.execute(
        "INSERT OR IGNORE INTO room_members (room, member_id, name, joined_ts) VALUES (?, ?, ?, ?)",
        (room, member_id, name, time.time())
    )
    # If the same member changes display name later, keep it fresh (optional)
    conn.execute(
        "UPDATE room_members SET name=? WHERE room=? AND member_id=?",
        (name, room, member_id)
    )
    conn.commit()

def _member_count(conn: sqlite3.Connection, room: str) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM room_members WHERE room=?", (room,))
    return int(cur.fetchone()[0] or 0)

def _clear_members(conn: sqlite3.Connection, room: str) -> None:
    conn.execute("DELETE FROM room_members WHERE room=?", (room,))
    conn.commit()



# ----------------------------- UI helpers ----------------------------- #

def _ts_to_str(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %I:%M:%S %p")


def _init_chat_state():
    # name / room defaults can derive from PlayerState if available
    ps = st.session_state.get("ps", None)
    default_name = ""
    if ps:
        # Prefer code_name, else "First L."
        code = getattr(ps, "code_name", "") or ""
        if code:
            default_name = code
        else:
            first = getattr(ps, "first_name", "") or ""
            last_i = getattr(ps, "last_initial", "") or ""
            default_name = f"{first} {last_i}.".strip()

    default_room = "general"
    if ps and getattr(ps, "lobby_id", None):
        default_room = f"lobby-{ps.lobby_id}"

    st.session_state.setdefault("name", default_name)
    st.session_state.setdefault("room", default_room)
    st.session_state.setdefault("number_of_players", default_number_of_players)
    st.session_state.setdefault("live_refresh", True)
    st.session_state.setdefault("last_loaded_before_ts", None)  # for pagination
    st.session_state.setdefault("client_id", str(uuid4()))  # unique per browser tab/session


# ----------------------------- Screen entry ----------------------------- #

def chat_main() -> None:
    """Render the chat screen and mutate st.session_state in-place."""
    _init_chat_state()
    conn = _get_conn()

    # Page header (keep minimal; page config should be set by top-level app)
    st.header("💬 Chat")


    # Sidebar: identity & rooms
    with st.sidebar:
        st.subheader("You")
        st.session_state.name = st.text_input("Display name", st.session_state.name, placeholder="e.g., Dan")
        if not st.session_state.name.strip():
            st.info("Pick a display name to start chatting.")

        st.markdown("---")
        st.subheader("Lobby")

        # Seed a default room if needed
        rooms = _list_rooms(conn)
        if "general" not in rooms:
            _ensure_room(conn, "general")
            rooms = _list_rooms(conn)

        # Also ensure the derived lobby room exists
        if st.session_state.room and st.session_state.room not in rooms:
            _ensure_room(conn, st.session_state.room)
            rooms = _list_rooms(conn)

        # Join existing room
        col_a, col_b = st.columns([2, 1])
        with col_a:
            # Protect index lookup
            try:
                default_idx = rooms.index(st.session_state.room)
            except ValueError:
                default_idx = 0
            selected = st.selectbox("Join a lobby", rooms, index=default_idx)
      
        with col_b:
            if st.button("Join", use_container_width=True):
                st.session_state.room = selected
                st.session_state.last_loaded_before_ts = None
                # record that a client has joined a room 
                if st.session_state.name.strip():
                    _add_member(conn, selected, st.session_state.client_id, st.session_state.name.strip())
                st.rerun()


        # Create room
        new_room = st.text_input("Create new lobby", placeholder="e.g., research-lab")
        new_room_players = st.number_input("Number of players", min_value=2, max_value=100, value=default_number_of_players, step=1)

        if st.button("Create", use_container_width=True) and new_room.strip():
            room_name = new_room.strip()
            _ensure_room(conn, room_name)
            _set_number_of_players(conn, room_name, int(new_room_players))
            # Add the current user as a member of the new room
            if st.session_state.name.strip():
                _add_member(conn, room_name, st.session_state.client_id, st.session_state.name.strip())
            st.session_state["room"] = room_name
            st.session_state["last_loaded_before_ts"] = None
            st.session_state["number_of_players"] = int(new_room_players)
            st.rerun()




        st.markdown("---")
        st.subheader("Refresh")
        st.session_state.live_refresh = st.toggle(
            "Live refresh every 2s",
            value=st.session_state.live_refresh,
            help="Auto-rerun to fetch new messages in this session."
        )
        st.caption("Tip: Keep the tab focused for best auto-refresh behavior.")

        st.markdown("---")
        st.subheader("Moderation")
        with st.popover("Clear this room…"):
            code = st.text_input("Admin code (optional)", type="password")
            if st.button("⚠️ Delete all messages in room", type="secondary"):
                if ADMIN_CLEAR_CODE and code != ADMIN_CLEAR_CODE:
                    st.error("Incorrect admin code.")
                else:
                    _clear_room(conn, st.session_state.room)
                    st.session_state.last_loaded_before_ts = None
                    st.success("Room cleared.")
                    st.rerun()




    # Main chat area
    room = st.session_state.room
    name = st.session_state.name.strip()

    # Count unique members who have ever joined this room
    num_players_required = _get_number_of_players(conn, room) or default_number_of_players
    joined_count = _member_count(conn, room)

    st.write(f"**Room:** `{room}`")
    st.caption(f"Joined: {joined_count}/{num_players_required}")


    # define timer state 
    CHAT_TIMER_DURATION = int(os.getenv("CHAT_TIMER_DURATION", "60"))
    close_at = _get_room_close_at(conn, room)

    if close_at is None and joined_count >= num_players_required:
        _set_room_close_at(conn, room, time.time() + CHAT_TIMER_DURATION)
        close_at = _get_room_close_at(conn, room)

    # Compute flags AFTER any possible start
    remaining = max(0, int((close_at - time.time()))) if close_at else None
    timer_active = close_at is not None
    timer_expired = timer_active and remaining <= 0

    # Single source of truth for disabling input
    input_disabled_reason = None
    if not name:
        input_disabled_reason = "Set your display name in the sidebar to chat."
    elif close_at is None:
        input_disabled_reason = f"Waiting for players to join… {joined_count}/{num_players_required}"
    elif timer_expired:
        input_disabled_reason = "Chat is closed."


    # Pagination: load recent messages (default 100), with ability to load older
    msgs = _get_messages(
        conn,
        room=room,
        limit=100,
        before_ts=st.session_state.last_loaded_before_ts
    )

    # Display messages using chat UI
    chat_container = st.container(height=520, border=True)
    with chat_container:
        if not msgs:
            st.info("No messages yet. Say hi! 👋")
        else:
            for _id, _room, author, text, ts in msgs:
                with st.chat_message("user", avatar="👤"):
                    st.markdown(f"**{author}**  ·  {_ts_to_str(ts)}")
                    st.write(text)

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Load older messages", use_container_width=True, disabled=(len(msgs) < 100)):
            # Next page: load older than oldest currently shown
            if msgs:
                st.session_state.last_loaded_before_ts = msgs[0][-1]
            st.rerun()
    with col2:
        if st.button("Scroll to bottom", use_container_width=True):
            st.rerun()

    # --- Chat input with inline timer on the right ---

    col_input, col_timer = st.columns([8, 1])

    with col_input:
        if input_disabled_reason:
            st.chat_input(input_disabled_reason, disabled=True)
        else:
            user_text = st.chat_input(f"Message #{room} as {name}")
            if user_text and user_text.strip():
                # Hard gate in case timer expired between render and send
                close_at_now = _get_room_close_at(conn, room)
                if close_at_now is not None and time.time() >= close_at_now:
                    st.warning("⏰ Message not sent — the chat just closed.")
                else:
                    _add_message(conn, room=room, author=name, text=user_text.strip())
                    st.session_state.last_loaded_before_ts = None
                    st.rerun()

    with col_timer:
        if timer_active and not timer_expired:
            mm, ss = divmod(remaining, 60)
            st.markdown(
                f"<div style='text-align:center; font-size:16px; margin-top:8px;'>"
                f"⏳ <b>{mm:02d}:{ss:02d}</b></div>",
                unsafe_allow_html=True
            )
        elif timer_expired:
            st.markdown(
                "<div style='text-align:center; font-size:16px; margin-top:8px; color:red;'>🔒</div>",
                unsafe_allow_html=True
            )



    # Live refresh loop (basic)
    if st.session_state.live_refresh:
        time.sleep(1)
        st.rerun()
