"""Rickshaw Brain — SQLite storage layer."""
import json
import sqlite3


class Brain:
    def __init__(self, db_path="rickshaw.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_db()

    def _init_db(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT DEFAULT 'default',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_calls TEXT,
                tool_call_id TEXT,
                timestamp TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT DEFAULT '[]',
                created TEXT DEFAULT (datetime('now')),
                updated TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                summary TEXT,
                next_steps TEXT DEFAULT '[]',
                model TEXT,
                created TEXT DEFAULT (datetime('now')),
                ended TEXT
            );
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT DEFAULT 'default',
                tool_name TEXT NOT NULL,
                arguments TEXT,
                result TEXT,
                status TEXT DEFAULT 'success',
                error TEXT,
                duration_ms INTEGER DEFAULT 0,
                timestamp TEXT DEFAULT (datetime('now'))
            );
        """)
        self.conn.commit()

    # --- Config ---
    def get_config(self, key, default=None):
        row = self.conn.execute(
            "SELECT value FROM config WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_config(self, key, value):
        self.conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
        self.conn.commit()

    # --- Messages ---
    def add_message(self, role, content, session_id="default",
                    tool_calls=None, tool_call_id=None):
        tc_json = json.dumps(tool_calls) if tool_calls else None
        self.conn.execute(
            "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content or "", tc_json, tool_call_id),
        )
        self.conn.commit()

    def get_messages(self, session_id="default", limit=50):
        rows = self.conn.execute(
            "SELECT role, content, tool_calls, tool_call_id, timestamp "
            "FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        results = []
        for r in reversed(rows):
            msg = {"role": r["role"], "content": r["content"]}
            if r["tool_calls"]:
                msg["tool_calls"] = json.loads(r["tool_calls"])
            if r["tool_call_id"]:
                msg["tool_call_id"] = r["tool_call_id"]
            results.append(msg)
        return results

    def clear_messages(self, session_id="default"):
        self.conn.execute(
            "DELETE FROM messages WHERE session_id=?", (session_id,)
        )
        self.conn.commit()

    # --- Memory ---
    def add_memory(self, category, content, tags=None):
        self.conn.execute(
            "INSERT INTO memory (category, content, tags) VALUES (?, ?, ?)",
            (category, content, json.dumps(tags or [])),
        )
        self.conn.commit()
        return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def get_memories(self, category=None, query=None, limit=20):
        sql = "SELECT id, category, content, tags, created, updated FROM memory"
        params = []
        clauses = []
        if category:
            clauses.append("category=?")
            params.append(category)
        if query:
            clauses.append("content LIKE ?")
            params.append(f"%{query}%")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def update_memory(self, memory_id, content=None, category=None):
        if content:
            self.conn.execute(
                "UPDATE memory SET content=?, updated=datetime('now') WHERE id=?",
                (content, memory_id),
            )
        if category:
            self.conn.execute(
                "UPDATE memory SET category=?, updated=datetime('now') WHERE id=?",
                (category, memory_id),
            )
        self.conn.commit()

    def delete_memory(self, memory_id):
        self.conn.execute("DELETE FROM memory WHERE id=?", (memory_id,))
        self.conn.commit()

    # --- Sessions ---
    def save_session(self, session_id, summary, next_steps=None, model=None):
        self.conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, summary, next_steps, model, ended) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (session_id, summary, json.dumps(next_steps or []), model),
        )
        self.conn.commit()

    def get_last_session(self):
        row = self.conn.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            d = dict(row)
            d["next_steps"] = json.loads(d["next_steps"]) if d["next_steps"] else []
            return d
        return None

    # --- Tool calls ---
    def add_tool_call(self, session_id, tool_name, arguments, result,
                      status="success", error=None, duration_ms=0):
        self.conn.execute(
            "INSERT INTO tool_calls "
            "(session_id, tool_name, arguments, result, status, error, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, tool_name, arguments, result[:4000] if result else "",
             status, error, duration_ms),
        )
        self.conn.commit()

    # --- Stats ---
    def stats(self):
        msg_count = self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        mem_count = self.conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        tc_total = self.conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0]
        tc_ok = self.conn.execute(
            "SELECT COUNT(*) FROM tool_calls WHERE status='success'"
        ).fetchone()[0]
        return {
            "messages": msg_count,
            "memories": mem_count,
            "tool_calls": tc_total,
            "tool_calls_ok": tc_ok,
            "tool_calls_err": tc_total - tc_ok,
        }
