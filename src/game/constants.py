# src/game/constants.py
MIN_PLAYERS = 3
MAX_PLAYERS = 5
TOTAL_ROUNDS = 3
VOTE_SECONDS = 200
CHAT_SECONDS = 120

PHASE_LOBBY = "LOBBY"
PHASE_CHAT  = "CHAT"
PHASE_VOTE  = "VOTE"
PHASE_SCORE = "SCORE"

GAME_RULES = (
    f"DoppelbotSL is a social-deduction chat game. {MIN_PLAYERS}-{MAX_PLAYERS} players join a room. "
    "One player is secretly assigned to act as the AI. "
    f"The game runs for {TOTAL_ROUNDS} rounds. Each round has a {CHAT_SECONDS}-second chat phase "
    f"followed by a {VOTE_SECONDS}-second vote phase. "
    "During the chat phase all non-eliminated players send messages. "
    "During the vote phase players vote to eliminate who they believe is the AI. "
    "The player with the most votes is eliminated each round. "
    "The AI wins if it survives all rounds without being eliminated. "
    "Human players win if they successfully vote out the AI."
)
