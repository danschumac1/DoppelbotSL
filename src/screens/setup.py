from __future__ import annotations
from typing import List
import streamlit as st

from utils.enums import Screen
from utils.states import GameState, PlayerState
from utils.AI import AIPlayer

# ---- Replace these with your own pools if desired ----
CODE_NAMES: List[str] = [
    "Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot",
    "Golf", "Hotel", "India", "Juliett", "Kilo", "Lima",
    "Mike", "November", "Oscar", "Papa", "Quebec", "Romeo",
    "Sierra", "Tango", "Uniform", "Victor", "Whiskey",
    "X-ray", "Yankee", "Zulu"
]

COLORS: List[str] = [
    "Red", "Blue", "Green", "Yellow", "Purple", "Orange",
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
    st.session_state.setdefault("gs", None)
    st.session_state.setdefault("ps", None)


def setup_main() -> None:
    _init_state()

    gs = st.session_state.gs
    ps = st.session_state.ps

    # Pull any previously-entered messages from PlayerState (if they exist)
    existing_msgs: List[str] = list(getattr(ps, "copied_text_msgs", []) or [])

    st.title("Player Setup")
    st.caption("Paste at least three texts; add more if you like.")

    # --- Message count controls OUTSIDE the form so UI can re-render immediately ---
    st.session_state.setdefault("msg_count", max(3, len(existing_msgs) or 0))

    # Let user pick a count (3–20). Putting this OUTSIDE the form makes it live-update fields.
    st.session_state.msg_count = st.number_input(
        "How many texts do you want to paste?",
        min_value=3, max_value=20, step=1,
        value=int(st.session_state.msg_count),
        key="msg_count_selector",
    )

    # --- The form for name/initial + the dynamic message inputs ---
    with st.form("player_setup", clear_on_submit=False):
        col1, col2 = st.columns(2)

        with col1:
            first = st.text_input(
                "First name",
                value=getattr(ps, "first_name", "")
            ).strip()

            last_initial = st.text_input(
                "Last initial (A–Z)",
                max_chars=1,
                value=getattr(ps, "last_initial", "")
            ).upper().strip()

        with col2:
            # Render exactly msg_count inputs, prefilled from existing / previous widget state
            input_msgs: List[str] = []
            for i in range(int(st.session_state.msg_count)):
                default_val = existing_msgs[i] if i < len(existing_msgs) else ""
                msg = st.text_input(
                    f"Text message #{i+1}",
                    value=default_val,
                    key=f"text_msg_{i+1}"
                ).strip()
                input_msgs.append(msg)

        submitted = st.form_submit_button("Join chat ▶", type="primary")

    if not submitted:
        with st.expander("Current players in this app session"):
            if not st.session_state.players:
                st.caption("No one yet — submit the form to join.")
            else:
                for p in st.session_state.players:
                    count = len(getattr(p, "copied_text_msgs", []) or [])
                    st.markdown(f"- **{p.first_name} {p.last_initial}.** as `{p.code_name}` · {p.color_name} · {count} texts")
        return

    # ---- Validation ----
    problems = []
    if not first:
        problems.append("First name is required.")
    if not (len(last_initial) == 1 and last_initial.isalpha()):
        problems.append("Last initial must be a single letter (A–Z).")

    cleaned_msgs = [m for m in input_msgs if m]
    if len(cleaned_msgs) < 3:
        problems.append("Please paste at least three non-empty text messages.")

    if problems:
        for p in problems:
            st.error(p)
        return

    # ---- Assign identity ----
    code_name = _next("code", CODE_NAMES)
    color = _next("color", COLORS)

    ps = PlayerState(
        first_name=first,
        last_initial=last_initial,
        code_name=code_name,
        copied_text_msgs=cleaned_msgs,
        is_human=True,
        color_name=color,
    )

    ai_player = AIPlayer(persona=ps.to_persona())
    ps.ai_doppleganger = ai_player
    st.session_state.ps = ps
    st.session_state.players.append(ps)

    if st.session_state.gs is None:
        st.session_state.gs = GameState()
    gs = st.session_state.gs
    gs.number_of_human_players = max(int(getattr(gs, "number_of_human_players", 1) or 1), 1)
    if not getattr(gs, "icebreakers", None):
        gs.icebreakers = [
            "What’s a hobby you picked up recently?",
            "What food could you eat every day?",
            "What’s your favorite class and why?",
        ]

    st.success(f"Welcome, {ps.first_name} ({ps.code_name}, {ps.color_name})! Heading to chat…")
    st.session_state.current_screen = "CHAT"
    st.rerun()
