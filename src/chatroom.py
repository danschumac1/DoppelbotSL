"""
Streamlit Chat Room — simple multi-user chat with rooms (SQLite backend)

How to run locally:
  1) pip install streamlit==1.*
  2) Save this file as app.py
  3) streamlit run app.py

Features
- Multiple rooms (create/select)
- Pick a display name (stored per browser session)
- Real-time-ish updates with optional live refresh loop
- Shows timestamps and supports loading older messages
- Basic moderation: clear room (optional admin passphrase)

Notes
- This uses a local SQLite file (chat.db). If you deploy on Streamlit Community Cloud or a server,
  all users connected to that deployment will share the same chat database.
- For a production system, add authentication and rate limiting.
"""

from __future__ import annotations
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import List, Tuple

import streamlit as st

DB_PATH = os.environ.get("CHAT_DB_PATH", "chat.db")
ADMIN_CLEAR_CODE = os.environ.get("CHAT_ADMIN_CODE", "")  # optional passphrase for clearing rooms

# ----------------------------- DB helpers ----------------------------- #
@st.cache_resource(show_spinner=False)
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rooms (
            room TEXT PRIMARY KEY,
            created_ts REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def list_rooms(conn: sqlite3.Connection) -> List[str]:
    cur = conn.execute("SELECT room FROM rooms ORDER BY room ASC")
    return [r[0] for r in cur.fetchall()]


def ensure_room(conn: sqlite3.Connection, room: str) -> None:
    conn.execute("INSERT OR IGNORE INTO rooms (room, created_ts) VALUES (?, ?)", (room, time.time()))
    conn.commit()


def add_message(conn: sqlite3.Connection, room: str, author: str, text: str) -> None:
    conn.execute(
        "INSERT INTO messages (room, author, text, ts) VALUES (?, ?, ?, ?)",
        (room, author, text, time.time()),
    )
    conn.commit()


def get_messages(
    conn: sqlite3.Connection,
    room: str,
    limit: int = 100,
    before_ts: float | None = None,
) -> List[Tuple[int, str, str, str, float]]:
    q = "SELECT id, room, author, text, ts FROM messages WHERE room=?"
    params: List[object] = [room]
    if before_ts is not None:
        q += " AND ts < ?"
        params.append(before_ts)
    q += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    cur = conn.execute(q, params)
    rows = cur.fetchall()
    # Return newest-last for display
    return list(reversed(rows))


def clear_room(conn: sqlite3.Connection, room: str) -> None:
    conn.execute("DELETE FROM messages WHERE room=?", (room,))
    conn.commit()


# ----------------------------- UI helpers ----------------------------- #

def ts_to_str(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %I:%M:%S %p")


def init_state():
    st.session_state.setdefault("name", "")
    st.session_state.setdefault("room", "general")
    st.session_state.setdefault("live_refresh", True)
    st.session_state.setdefault("last_loaded_before_ts", None)  # for pagination


# ----------------------------- Page ----------------------------- #

st.set_page_config(page_title="Streamlit Chat Room", page_icon="💬", layout="centered")
init_state()
conn = get_conn()

st.title("💬 Streamlit Chat Room")

# Sidebar: identity & rooms
with st.sidebar:
    st.subheader("You")
    st.session_state.name = st.text_input("Display name", st.session_state.name, placeholder="e.g., Dan")
    if not st.session_state.name.strip():
        st.info("Pick a display name to start chatting.")

    st.markdown("---")
    st.subheader("Room")
    rooms = list_rooms(conn)
    if "general" not in rooms:
        ensure_room(conn, "general")
        rooms = list_rooms(conn)

    col_a, col_b = st.columns([2, 1])
    with col_a:
        selected = st.selectbox("Join a room", rooms, index=max(0, rooms.index(st.session_state.room) if st.session_state.room in rooms else 0))
    with col_b:
        if st.button("Join", use_container_width=True):
            st.session_state.room = selected
            st.session_state.last_loaded_before_ts = None
            st.rerun()

    new_room = st.text_input("Create new room", placeholder="e.g., research-lab")
    if st.button("Create", use_container_width=True) and new_room.strip():
        ensure_room(conn, new_room.strip())
        st.session_state.room = new_room.strip()
        st.session_state.last_loaded_before_ts = None
        st.rerun()

    st.markdown("---")
    st.subheader("Refresh")
    st.session_state.live_refresh = st.toggle("Live refresh every 2s", value=st.session_state.live_refresh, help="Auto-rerun to fetch new messages in this session.")

    st.caption("Tip: Keep the tab focused for best auto-refresh behavior.")

    st.markdown("---")
    st.subheader("Moderation")
    with st.popover("Clear this room…"):
        code = st.text_input("Admin code (optional)", type="password")
        if st.button("⚠️ Delete all messages in room", type="secondary"):
            if ADMIN_CLEAR_CODE and code != ADMIN_CLEAR_CODE:
                st.error("Incorrect admin code.")
            else:
                clear_room(conn, st.session_state.room)
                st.session_state.last_loaded_before_ts = None
                st.success("Room cleared.")
                st.rerun()

# Main chat area
room = st.session_state.room
name = st.session_state.name.strip()
st.write(f"**Room:** `{room}`")

# Pagination: load recent messages (default 100), with ability to load older
msgs = get_messages(conn, room=room, limit=100, before_ts=st.session_state.last_loaded_before_ts)

# Display messages using chat UI
chat_container = st.container(height=520, border=True)
with chat_container:
    if not msgs:
        st.info("No messages yet. Say hi! 👋")
    else:
        for _id, _room, author, text, ts in msgs:
            with st.chat_message("user", avatar="👤"):
                st.markdown(f"**{author}**  ·  {ts_to_str(ts)}")
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

# Chat input
if name:
    user_text = st.chat_input(f"Message #{room} as {name}")
    if user_text and user_text.strip():
        add_message(conn, room=room, author=name, text=user_text.strip())
        # After sending, immediately re-query last messages so it appears without waiting for timer
        st.session_state.last_loaded_before_ts = None
        st.rerun()
else:
    st.chat_input("Set your display name in the sidebar to chat.", disabled=True)

# Live refresh loop (basic)
if st.session_state.live_refresh:
    time.sleep(2)
    st.rerun()
