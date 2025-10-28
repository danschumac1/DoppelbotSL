from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

@dataclass
class PlayerState:
    # lobby_id: str
    first_name: str
    last_initial: str
    code_name: str
    copied_text_msgs: List[str]
    is_human: bool 
    color_name: str     
    starttime: str = "" # Start time of the game
    voted: bool = False # Flag to indicate if the player has voted
    still_in_game: bool = True # Flag to indicate if the player is still in the game

    ai_doppleganger: Optional["AIPlayer"] = None # type: ignore
    # written_to_file: bool = False # Flag to indicate if the player has been written to a file
    # timekeeper: bool = False # Flag to indicate if the player is a timekeeper

    def to_persona(self) -> dict:
        return {
            "first_name": self.first_name,
            "last_initial": self.last_initial,
            "code_name": self.code_name,
            "text_samples": "\n".join(self.copied_text_msgs),
        }

@dataclass
class GameState:
    round_number:  int = 0
    players: List[PlayerState] = field(default_factory=list)
    players_voted_off: List[PlayerState] = field(default_factory=list)
    last_vote_outcome: str = ""     # The outcome of the last vote
    chat_log: str = ""              # Chat log content
    voting_log: str = ""            # Voting log content
    vote_records: dict = field(default_factory=dict)  # Records of votes
    chat_complete: bool = False      # Flag to indicate if the chat is complete
    voting_complete: bool = False    # Flag to indicate if the voting is complete
    round_complete: bool = False