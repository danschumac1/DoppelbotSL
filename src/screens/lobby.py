from __future__ import annotations
import streamlit as st
from uuid import uuid4

# Reuse DB + helpers from chat.py
# TODO: move some of these here 
from screens.chat import (
    _get_conn, _list_rooms, _ensure_room, _add_member,
    _get_number_of_players, _set_number_of_players, _member_count,
)

DEFAULT_PLAYERS = 2  # lobby default number of players 

def _init_lobby_state():
    st.session_state.setdefault("name", "")
    st.session_state.setdefault("room", "general")
    st.session_state.setdefault("client_id", str(uuid4()))

def lobby_main():
    _init_lobby_state()
    conn = _get_conn()

    # wrap ui in a container so we can clear it before switching to chat
    page = st.container()

    with page:
        st.title("🧑‍🤝‍🧑 Lobby")
        st.write("Set your display name, then join an existing lobby or create a new one.")

        with st.form("name_form", clear_on_submit=False):
            name = st.text_input("Display name", st.session_state.name, placeholder="e.g., Alex")
            submitted = st.form_submit_button("Save name")
            if submitted:
                st.session_state.name = name.strip()
                st.success("Name saved.")

        if not st.session_state.name.strip():
            st.info("Save a display name before joining/creating a lobby.")
            return

        st.divider()
        st.subheader("Join an existing lobby")

        rooms = _list_rooms(conn)
        if "general" not in rooms:
            _ensure_room(conn, "general")
            rooms = _list_rooms(conn)

        try:
            default_idx = rooms.index(st.session_state.room)
        except ValueError:
            default_idx = 0

        selected = st.selectbox("Lobbies", rooms, index=default_idx)

        want = _get_number_of_players(conn, selected) or DEFAULT_PLAYERS
        have = _member_count(conn, selected)
        st.caption(f"Players joined: {have}/{want}")

        if st.button("Join Lobby", type="primary", use_container_width=True):
            # Record membership first
            st.session_state.room = selected
            _add_member(conn, selected, st.session_state.client_id, st.session_state.name)

            # Clear lobby UI, set target screen, then rerun
            page.empty()
            st.session_state.current_screen = "CHAT"
            st.rerun()
            return

        st.divider()
        st.subheader("Or create a new lobby")

        col1, col2 = st.columns([2, 1])
        with col1:
            new_room = st.text_input("Lobby name", placeholder="e.g., lunch-table-3")
        with col2:
            players = st.number_input("Players", min_value=2, max_value=100, value=DEFAULT_PLAYERS, step=1)

        if st.button("Create Lobby", use_container_width=True):
            room = new_room.strip()
            if not room:
                st.error("Please enter a lobby name.")
            else:
                _ensure_room(conn, room)
                _set_number_of_players(conn, room, int(players))
                _add_member(conn, room, st.session_state.client_id, st.session_state.name)
                st.session_state.room = room

                # Clear lobby UI, set target screen, then rerun
                page.empty()
                st.session_state.current_screen = "CHAT"
                st.rerun()
                return
