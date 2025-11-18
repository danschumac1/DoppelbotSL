import sqlite3, threading, queue, time, os
from pathlib import Path

_DB = Path(__file__).with_name("game.db")

_SCHEMA = """ 
PRAGMA journal_mode=WAL
CREATE TABLE IF NOT EXISTS messages (
 id INTERGER PRIMARY KEY AUTOINCREMENT,
 room_id TEXT NOT NULL,
 user_id TEXT NOT NULL,
 text TEXT NOT NULL,
 ts INTERGER NOT NULL
 );
 CREATE INDEX IF NOT EXISTS idx_messages_toom_ts ON messages(room_id, ts);
 """

class Sink: 
    def __init__(self, path=_DB):
        self.path = str(path)
        self.q = queue.SimpleQueue()
        self.stop = threading.Event()
        self.t = threading.Thread(target=self._loop, daemon=True)
    
    def _init(self):
        con = sqlite3.connect(self.path)
        con.executescript(_SCHEMA); con.commit(); con.close;

    #Prevents blocking WebSocket threads
    def emit_message(self, room_id: str, user_id, text: str, ts: int):
        self.q.put(("message", room_id, user_id, text, ts))
    
    # Getting recent chats for a room so when a user joins they can see prior messages
    def recent_message(self, room_id: str, limit: int = 50):
        con = sqlite3.connect(self.path)
        cur = con.execute("SELECT user_id, text, ts FROM messages WHERE room_id=? ORDER BY ts DESC LIMIT ?", (room_id, limit))
        rows = cur.fetchall(); con.close()
        return[{"user": r[0], "text": r[1], "ts": r[2]} for r in reversed(rows)]
    
    # Pulls items from queue to put them into SQLite DB
    def _loop(self):
        con = sqlite3.connect(self.path)

        try:
            while not self.stop.is_set():
                try:
                    item = self.q.get(timeout=0.25)
                except Exception:
                    continue #loops if there is no items
            
            kind, room, user, text, ts = item

            #Inserts new chat message
            if kind == "message":
                con.execute(
                    "INSERT INTO messages(room_id, user_id, text, ts) VALUES(?,?,?,?)"
                    (room, user, text, ts)
                )
            con.commit()
        
        finally:
            con.close()
    
    def shutdown(self):
        self.stop.set()
        
