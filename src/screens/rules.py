# screens/rules.py
import sys
sys.path.append("./src")
import streamlit as st
from enum import Enum
from utils.enums import Screen

EMO = {"spark": "🌟", "brain": "🧠", "loop": "🔁", "target": "🎯", "warn": "⚠️"}

SECTIONS = [
    {"kind": "title",
     "title": f"{EMO['spark']} WELCOME TO... WHO'S REAL? {EMO['spark']}",
     "body": ("You're a high school student hanging out with your friends during lunch.\n\n"
              "Today, you're all playing a social deduction game — but there's a twist...")},
    {"kind": "error", "title": "Some of your friends have been secretly replaced by AI."},
    {"kind": "warning", "title": "Your job? Figure out who's real and who's not before it's too late."},
    {"kind": "section", "title": f"{EMO['brain']} THE BASICS",
     "bullets": ["There are 3 human players (including you).",
                 "3 other players are AI pretending to be humans.",
                 "Chat, observe, and vote to eliminate the AIs."]},
    {"kind": "section", "title": f"{EMO['loop']} GAME FLOW",
     "bullets": ["An icebreaker question kicks off each round.",
                 "Everyone chats, responds, and tries to blend in.",
                 "At the end of the round, you vote someone out.",
                 "The game lasts 3 rounds. Win or lose, that’s it."]},
    {"kind": "section", "title": f"{EMO['target']} HOW TO WIN",
     "bullets": ["HUMANS win by identifying and voting out all the AIs.",
                 "AIs win if they outnumber the humans by the end."]},
    {"kind": "section", "title": f"{EMO['warn']} REMEMBER",
     "bullets": ["Always stay in character — you're a student, not a machine.",
                 "No swearing or weird behavior.",
                 "Don’t break the fourth wall or say things like 'as an AI.'",
                 "You only know your own identity.",
                 "Convince others that *you* are real, and stay sharp."]},
]

def _render_section(i: int):
    data = SECTIONS[i]
    if data["kind"] == "title":
        st.title(data["title"])
        st.markdown(data["body"])
    elif data["kind"] == "error":
        st.error(data["title"])
    elif data["kind"] == "warning":
        st.warning(data["title"])
    else:
        st.header(data["title"])
        for b in data.get("bullets", []):
            st.markdown(f"- {b}")

def rules_main():
    st.session_state.setdefault("intro_idx", 0)

    i = st.session_state.intro_idx
    st.markdown("---")
    _render_section(i)

    st.write("")
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("◀ Prev", disabled=(i == 0), use_container_width=True):
            st.session_state.intro_idx = max(0, i - 1)
            st.rerun()
    with c2:
        if st.button("Next ▶", use_container_width=True):
            if i < len(SECTIONS) - 1:
                st.session_state.intro_idx = i + 1
                st.rerun()
            else:
                st.session_state.intro_idx = 0
                st.session_state.current_screen = "SETUP"   # <— use the SAME key
                st.rerun()
    with c3:
        if st.button("Skip to Setup", use_container_width=True):
            st.session_state.intro_idx = 0
            st.session_state.current_screen = "SETUP"       # <— same here
            st.rerun()