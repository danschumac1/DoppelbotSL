import streamlit as st

# USER DEFINED
from utils.enums import Screen

from screens.rules import rules_main
from screens.setup import setup_main
from screens.lobby import lobby_main
from screens.chat import chat_main
from screens.voting import voting_main
from screens.score import score_main

screen_handler = {
    "RULES": rules_main,
    "SETUP": setup_main,
    "LOBBY": lobby_main,
    "CHAT": chat_main,
    "VOTE": voting_main,
    "SCORE": score_main,
}

def main():
    st.sidebar.title("Navigation")

    # Initialize session state once (use string key)
    st.session_state.setdefault("current_screen", "RULES")
    st.session_state.setdefault("gs", None)
    st.session_state.setdefault("ps", None)


    # Convert Enum to string list for radio
    choices = [s.name for s in Screen]

    choice = st.sidebar.radio(
        "Go to:",
        choices,
        index=choices.index(st.session_state.current_screen),
        format_func=lambda s: s.title(),
    )

    # Route change
    if choice != st.session_state.current_screen:
        st.session_state.current_screen = choice
        st.rerun()

    # Render current screen
    screen_handler[st.session_state.current_screen]()

if __name__ == "__main__":
    main()
