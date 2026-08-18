"""Persistencia SQLite: operaciones cerradas, snapshots de equity y eventos.
Sobrevive a reinicios del proceso."""
import json
import os
import sqlite3
import threading
from typing import List, Optional

from .config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT, side TEXT, qty REAL,
    entry_price REAL, exit_price REAL,
    entry_ts INTEGER, exit_ts INTEGER,
    pnl REAL, fees REAL,
    strategy TEXT, entry_reason TEXT, exit_reason TEXT
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
    ts INTEGER PRIMARY KEY,
    equity REAL, cash REAL, open_positions INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER, type TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY, value TEXT
);
"""


class Database:
    def __init__(self, path: Optional[str] = None):
        self.path = path or settings.db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def insert_trade(self, t: dict):
        with self._lock:
            self._conn.execute(
                """INSERT INTO trades (symbol, side, qty, entry_price, exit_price,
                   entry_ts, exit_ts, pnl, fees, strategy, entry_reason, exit_reason)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (t["symbol"], t["side"], t["qty"], t["entry_price"], t["exit_price"],
                 t["entry_ts"], t["exit_ts"], t["pnl"], t["fees"],
                 t["strategy"], t["entry_reason"], t["exit_reason"]))
            self._conn.commit()

    def recent_trades(self, limit: int = 100) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM trades ORDER BY exit_ts DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def insert_equity(self, ts: int, equity: float, cash: float, open_positions: int):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO equity_snapshots (ts, equity, cash, open_positions) "
                "VALUES (?,?,?,?)", (ts, equity, cash, open_positions))
            self._conn.commit()

    def equity_history(self, since_ts: int = 0, limit: int = 5000) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, equity FROM equity_snapshots WHERE ts >= ? ORDER BY ts LIMIT ?",
                (since_ts, limit)).fetchall()
        return [dict(r) for r in rows]

    def insert_event(self, ts: int, type_: str, payload: dict):
        with self._lock:
            self._conn.execute("INSERT INTO events (ts, type, payload) VALUES (?,?,?)",
                               (ts, type_, json.dumps(payload)))
            self._conn.commit()

    def recent_events(self, limit: int = 100) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, type, payload FROM events ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        out = []
        for r in rows:
            try:
                payload = json.loads(r["payload"])
            except (TypeError, ValueError):
                payload = {}
            out.append({"ts": r["ts"], "type": r["type"], "payload": payload})
        return out

    def set_kv(self, key: str, value: dict):
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?,?)",
                               (key, json.dumps(value)))
            self._conn.commit()

    def get_kv(self, key: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def close(self):
        with self._lock:
            self._conn.close()
