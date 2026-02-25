import sqlite3
import threading
import queue
from pathlib import Path

_DB = Path(__file__).with_name("game.db")

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  text TEXT NOT NULL,
  ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_room_ts ON messages(room_id, ts);

CREATE TABLE IF NOT EXISTS players (
  player_id   TEXT PRIMARY KEY,
  room_id     TEXT NOT NULL,
  username    TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  participant_id TEXT NOT NULL DEFAULT '',
  age         INTEGER NOT NULL DEFAULT 0,
  joined_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_players_room ON players(room_id);
"""

class Sink:
    """
    Background writer for SQLite to avoid blocking the event loop.
    Use emit_message() for writes, recent_messages() for reads.
    """
    def __init__(self, path=_DB):
        self.path = str(path)
        self.q = queue.Queue()
        self.stop = threading.Event()
        self._init_db()
        self.t = threading.Thread(target=self._loop, daemon=True)
        self.t.start()

    def _init_db(self):
        con = sqlite3.connect(self.path)
        con.executescript(_SCHEMA)
        con.commit()
        con.close()

    def emit_message(self, room_id: str, user_id: str, text: str, ts: int):
        self.q.put(("message", room_id, user_id, text, ts))

    def emit_player(self, player_id: str, room_id: str, username: str,
                    display_name: str, participant_id: str, age: int, joined_at: int):
        self.q.put(("player", player_id, room_id, username, display_name, participant_id, age, joined_at))

    def recent_messages(self, room_id: str, limit: int = 50):
        con = sqlite3.connect(self.path)
        cur = con.execute(
            "SELECT user_id, text, ts FROM messages WHERE room_id=? ORDER BY ts DESC LIMIT ?",
            (room_id, limit),
        )
        rows = cur.fetchall()
        con.close()
        return [{"user": r[0], "text": r[1], "ts": r[2]} for r in reversed(rows)]

    def _loop(self):
        con = sqlite3.connect(self.path)
        try:
            while not self.stop.is_set():
                try:
                    item = self.q.get(timeout=0.25)
                except queue.Empty:
                    continue

                kind = item[0]
                if kind == "message":
                    _, room, user, text, ts = item
                    con.execute(
                        "INSERT INTO messages(room_id,user_id,text,ts) VALUES(?,?,?,?)",
                        (room, user, text, ts),
                    )
                    con.commit()
                elif kind == "player":
                    _, player_id, room_id, username, display_name, participant_id, age, joined_at = item
                    con.execute(
                        """INSERT OR REPLACE INTO players
                           (player_id,room_id,username,display_name,participant_id,age,joined_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (player_id, room_id, username, display_name, participant_id, age, joined_at),
                    )
                    con.commit()
        finally:
            con.close()

    def shutdown(self):
        self.stop.set()
        self.t.join(timeout=2)
