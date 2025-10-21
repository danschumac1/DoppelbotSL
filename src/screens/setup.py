from __future__ import annotations
from typing import List
import streamlit as st

from utils.enums import Screen
from utils.states import GameState, PlayerState

# If your project exposes these types, import them
# from utils.types import GameState, PlayerState
# from utils.enums import Screen as ScreenEnum
# from utils.logging import MasterLogger

# Optional import: your AI bot
# try:
#     from utils.chatbot.ai_v5 import AIPlayer  # type: ignore
#     _AI_AVAILABLE = True
# except Exception:
#     _AI_AVAILABLE = False

# ---- Replace these with your own pools if desired ----
CODE_NAMES: List[str] = [
    "Falcon", "Nebula", "Quasar", "Echo", "Raven", "Orchid", "Zephyr", "Ember",
]
COLORS: List[str] = [
    "Crimson", "Sapphire", "Emerald", "Amber", "Violet", "Teal", "Indigo", "Silver",
]
# ------------------------------------------------------


def _next(pool_key: str, items: List[str]) -> str:
    """Round-robin assigner stored in session_state; no files needed."""
    idx_key = f"_idx_{pool_key}"
    st.session_state.setdefault(idx_key, 0)
    val = items[st.session_state[idx_key] % len(items)]
    st.session_state[idx_key] += 1
    return val


def _init_state():
    st.session_state.setdefault("players", [])  # list[PlayerState]
    # Expect the router to have created st.session_state.gs / ps / screen,
    # but don't crash if not:
    st.session_state.setdefault("gs", None)
    st.session_state.setdefault("ps", None)


def setup_main() -> None:
    """Render the setup screen and mutate st.session_state in-place."""
    _init_state()

    gs = st.session_state.gs
    ps = st.session_state.ps

    st.title("Player Setup")
    st.caption("Quick profile to join the lobby. No files, no waiting — jump straight to chat.")

    with st.form("player_setup", clear_on_submit=False, border=True):
        col1, col2 = st.columns(2)
        with col1:
            lobby = st.number_input(
                "Lobby #",
                min_value=1, max_value=10000,
                value=int(getattr(ps, "lobby_id", 1) or 1),
                step=1,
                help="Used locally to rotate icebreakers; not persisted."
            )
            # want_ai = st.toggle(
            #     "Add my AI doppelgänger",
            #     value=True,
            # )
        with col2:
            first = st.text_input("First name", value=getattr(ps, "first_name", "")).strip()
            last_initial = st.text_input("Last initial (A–Z)", max_chars=1,
                                         value=getattr(ps, "last_initial", "")).upper().strip()

        submitted = st.form_submit_button("Join chat ▶", type="primary")

    if not submitted:
        # Optional: small roster preview (current process only)
        with st.expander("Current players in this app session"):
            if not st.session_state.players:
                st.caption("No one yet — submit the form to join.")
            else:
                for p in st.session_state.players:
                    st.markdown(f"- **{p.first_name} {p.last_initial}.** as `{p.code_name}` · {p.color_name}")
        return

    # ---- Validation ----
    problems = []
    if not first:
        problems.append("First name is required.")
    if not (len(last_initial) == 1 and last_initial.isalpha()):
        problems.append("Last initial must be a single letter (A–Z).")
    if problems:
        for p in problems:
            st.error(p)
        return

    # ---- Assign identity (round-robin, no files) ----
    code_name = _next("code", CODE_NAMES)
    color = _next("color", COLORS)

    # ---- Build PlayerState ----
    ps = PlayerState(
        lobby_id=int(lobby),
        first_name=first,
        last_initial=last_initial,
        code_name=code_name,
        is_human=True,
        color_name=color,
    )
    st.session_state.ps = ps

    # Roster (local to this server process)
    st.session_state.players.append(ps)

    # Optionally attach AI buddy

    # ---- Minimal GameState mutation; keep it resilient ----
    if st.session_state.gs is None:
        st.session_state.gs = GameState()
    gs = st.session_state.gs

    n = int(getattr(gs, "number_of_human_players", 1) or 1)
    gs.number_of_human_players = max(n, 1)

    if not getattr(gs, "icebreakers", None):
        gs.icebreakers = [
            "What’s a hobby you picked up recently?",
            "What food could you eat every day?",
            "What’s your favorite class and why?",
        ]

    st.success(f"Welcome, {ps.first_name} ({ps.code_name}, {ps.color_name})! Heading to chat…")

    # Route to CHAT by mutating session state only
    st.session_state.current_screen = "CHAT"
    st.rerun()
