"""SQLite persistence. A deliberately small document-style store plus a dedicated, indexed event table.

SQLite is chosen over Postgres to avoid unnecessary infrastructure; the Store interface is narrow so
it can be swapped for Postgres without touching callers.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any, Iterable, Optional

from .config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL, created REAL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS docs(
  kind TEXT NOT NULL, id TEXT NOT NULL, owner TEXT, project_id TEXT, data TEXT NOT NULL,
  created REAL, updated REAL, PRIMARY KEY(kind, id));
CREATE INDEX IF NOT EXISTS docs_project ON docs(kind, project_id);
CREATE INDEX IF NOT EXISTS docs_owner ON docs(kind, owner);
CREATE TABLE IF NOT EXISTS events(
  simulation_id TEXT NOT NULL, seq INTEGER NOT NULL, id TEXT NOT NULL, round INTEGER, type TEXT, data TEXT NOT NULL,
  PRIMARY KEY(simulation_id, seq));
CREATE TABLE IF NOT EXISTS usage(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, project_id TEXT, task TEXT, model TEXT,
  prompt_tokens INTEGER, completion_tokens INTEGER, cost REAL);
"""


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Store:
    def __init__(self, path: Optional[str] = None):
        settings.ensure_dirs()
        self.path = str(path or settings.db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    # -- generic documents -------------------------------------------------
    def put(self, kind: str, id: str, data: dict, owner: str = None, project_id: str = None) -> dict:
        now = time.time()
        with self._lock:
            row = self._conn.execute("SELECT created FROM docs WHERE kind=? AND id=?", (kind, id)).fetchone()
            created = row["created"] if row else now
            self._conn.execute(
                "INSERT OR REPLACE INTO docs(kind,id,owner,project_id,data,created,updated) VALUES(?,?,?,?,?,?,?)",
                (kind, id, owner, project_id, json.dumps(data, ensure_ascii=False), created, now))
        return data

    def get(self, kind: str, id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT data,owner,project_id,created,updated FROM docs WHERE kind=? AND id=?", (kind, id)).fetchone()
        if not row:
            return None
        d = json.loads(row["data"])
        d.setdefault("id", id)
        d["_owner"], d["_project"], d["_created"], d["_updated"] = row["owner"], row["project_id"], row["created"], row["updated"]
        return d

    def list(self, kind: str, owner: str = None, project_id: str = None, limit: int = 500) -> list:
        q, args = "SELECT id,data,owner,project_id,created,updated FROM docs WHERE kind=?", [kind]
        if owner is not None:
            q += " AND owner=?"; args.append(owner)
        if project_id is not None:
            q += " AND project_id=?"; args.append(project_id)
        q += " ORDER BY updated DESC LIMIT ?"; args.append(limit)
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = json.loads(r["data"]); d.setdefault("id", r["id"])
            d["_owner"], d["_project"], d["_created"], d["_updated"] = r["owner"], r["project_id"], r["created"], r["updated"]
            out.append(d)
        return out

    def delete(self, kind: str, id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM docs WHERE kind=? AND id=?", (kind, id))

    def delete_project(self, project_id: str) -> None:
        with self._lock:
            sims = [r["id"] for r in self._conn.execute("SELECT id FROM docs WHERE kind='simulation' AND project_id=?", (project_id,))]
            for s in sims:
                self._conn.execute("DELETE FROM events WHERE simulation_id=?", (s,))
            self._conn.execute("DELETE FROM docs WHERE project_id=?", (project_id,))
            self._conn.execute("DELETE FROM docs WHERE kind='project' AND id=?", (project_id,))

    # -- events ------------------------------------------------------------
    def append_events(self, simulation_id: str, events: Iterable[dict]) -> None:
        rows = [(simulation_id, e["seq"], e["id"], e.get("round"), e.get("type"), json.dumps(e, ensure_ascii=False)) for e in events]
        with self._lock:
            self._conn.executemany("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)", rows)

    def read_events(self, simulation_id: str, after_seq: int = -1, limit: int = 100000) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM events WHERE simulation_id=? AND seq>? ORDER BY seq LIMIT ?", (simulation_id, after_seq, limit)).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def count_events(self, simulation_id: str) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) c FROM events WHERE simulation_id=?", (simulation_id,)).fetchone()["c"]

    # -- usage -------------------------------------------------------------
    def log_usage(self, project_id, task, model, pt, ct, cost) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO usage(ts,project_id,task,model,prompt_tokens,completion_tokens,cost) VALUES(?,?,?,?,?,?,?)",
                               (time.time(), project_id, task, model, pt, ct, cost))

    def usage_summary(self, project_id: str = None) -> dict:
        q = "SELECT task, model, SUM(prompt_tokens) pt, SUM(completion_tokens) ct, SUM(cost) cost, COUNT(*) calls FROM usage"
        args = []
        if project_id:
            q += " WHERE project_id=?"; args.append(project_id)
        q += " GROUP BY task, model"
        with self._lock:
            rows = [dict(r) for r in self._conn.execute(q, args).fetchall()]
        return {"by_task_model": rows,
                "total_tokens": sum((r["pt"] or 0) + (r["ct"] or 0) for r in rows),
                "total_cost_usd": round(sum(r["cost"] or 0 for r in rows), 6),
                "calls": sum(r["calls"] for r in rows)}

    # -- raw access for auth ----------------------------------------------
    def execute(self, sql: str, args: tuple = ()) -> list:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()


_store: Optional[Store] = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def reset_store_for_tests(path: str) -> Store:
    global _store
    _store = Store(path)
    return _store
