"""Admin store: column/table metadata, few-shot examples, query logs and settings (SQLite, thread-safe)."""
from __future__ import annotations

import copy
import csv
import io
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import ADMIN_DB_PATH, DEFAULT_SETTINGS

_DDL = """
CREATE TABLE IF NOT EXISTS column_meta (
    table_name TEXT NOT NULL, column_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', is_sensitive INTEGER NOT NULL DEFAULT 0,
    synonyms TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (table_name, column_name)
);
CREATE TABLE IF NOT EXISTS table_meta (
    table_name TEXT PRIMARY KEY, description TEXT NOT NULL DEFAULT '', synonyms TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, sql TEXT NOT NULL,
    query_type TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS query_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, question TEXT NOT NULL, query_type TEXT,
    generated_sql TEXT, final_sql TEXT, status TEXT NOT NULL, error TEXT, latency_ms REAL, total_ms REAL,
    row_count INTEGER, provider TEXT, model TEXT, retried INTEGER DEFAULT 0, self_healed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AdminStore:
    def __init__(self, path: Path | str = ADMIN_DB_PATH):
        self.path = str(path)
        self._lock = threading.RLock()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_DDL)
            self._conn.commit()

    # ── helpers ──
    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    def _exec(self, sql: str, params: tuple = (), rowcount: bool = False) -> int:
        """Returns lastrowid for INSERTs, or the affected-row count when rowcount=True (UPDATE/DELETE)."""
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.rowcount if rowcount else cur.lastrowid

    # ── settings ──
    def get_settings(self, section: str) -> dict:
        merged = copy.deepcopy(DEFAULT_SETTINGS[section])
        row = self._one("SELECT value FROM settings WHERE key=?", (section,))
        if row:
            merged.update(json.loads(row["value"]))
        return merged

    def update_settings(self, section: str, values: dict) -> dict:
        current = self.get_settings(section)
        unknown = set(values) - set(DEFAULT_SETTINGS[section])
        if unknown:
            raise ValueError(f"Unknown {section} setting(s): {sorted(unknown)}")
        current.update(values)
        self._exec("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (section, json.dumps(current)))
        return current

    # ── column / table metadata ──
    def all_column_meta(self) -> dict[tuple[str, str], dict]:
        out = {}
        for r in self._all("SELECT * FROM column_meta"):
            out[(r["table_name"], r["column_name"])] = {
                "description": r["description"], "is_sensitive": bool(r["is_sensitive"]),
                "synonyms": json.loads(r["synonyms"])}
        return out

    def all_table_meta(self) -> dict[str, dict]:
        return {r["table_name"]: {"description": r["description"], "synonyms": json.loads(r["synonyms"])}
                for r in self._all("SELECT * FROM table_meta")}

    def upsert_column_meta(self, table: str, column: str, description: Optional[str] = None,
                           is_sensitive: Optional[bool] = None, synonyms: Optional[list[str]] = None) -> None:
        cur = self.all_column_meta().get((table, column), {"description": "", "is_sensitive": False, "synonyms": []})
        if description is not None:
            cur["description"] = description
        if is_sensitive is not None:
            cur["is_sensitive"] = is_sensitive
        if synonyms is not None:
            cur["synonyms"] = [s.strip() for s in synonyms if s.strip()]
        self._exec(
            "INSERT INTO column_meta(table_name,column_name,description,is_sensitive,synonyms) VALUES(?,?,?,?,?) "
            "ON CONFLICT(table_name,column_name) DO UPDATE SET description=excluded.description, "
            "is_sensitive=excluded.is_sensitive, synonyms=excluded.synonyms",
            (table, column, cur["description"], int(cur["is_sensitive"]), json.dumps(cur["synonyms"])))

    def upsert_table_meta(self, table: str, description: Optional[str] = None,
                          synonyms: Optional[list[str]] = None) -> None:
        cur = self.all_table_meta().get(table, {"description": "", "synonyms": []})
        if description is not None:
            cur["description"] = description
        if synonyms is not None:
            cur["synonyms"] = [s.strip() for s in synonyms if s.strip()]
        self._exec(
            "INSERT INTO table_meta(table_name,description,synonyms) VALUES(?,?,?) "
            "ON CONFLICT(table_name) DO UPDATE SET description=excluded.description, synonyms=excluded.synonyms",
            (table, cur["description"], json.dumps(cur["synonyms"])))

    # ── examples ──
    def list_examples(self, query_type: Optional[str] = None) -> list[dict]:
        if query_type:
            return self._all("SELECT * FROM examples WHERE query_type=? ORDER BY id", (query_type,))
        return self._all("SELECT * FROM examples ORDER BY id")

    def get_example(self, example_id: int) -> Optional[dict]:
        return self._one("SELECT * FROM examples WHERE id=?", (example_id,))

    def add_example(self, question: str, sql: str, query_type: Optional[str]) -> int:
        now = _now()
        return self._exec("INSERT INTO examples(question,sql,query_type,created_at,updated_at) VALUES(?,?,?,?,?)",
                          (question.strip(), sql.strip(), query_type, now, now))

    def update_example(self, example_id: int, question: str, sql: str, query_type: Optional[str]) -> bool:
        return bool(self._exec("UPDATE examples SET question=?, sql=?, query_type=?, updated_at=? WHERE id=?",
                               (question.strip(), sql.strip(), query_type, _now(), example_id), rowcount=True))

    def delete_example(self, example_id: int) -> bool:
        return bool(self._exec("DELETE FROM examples WHERE id=?", (example_id,), rowcount=True))

    def count_examples(self) -> int:
        return self._one("SELECT COUNT(*) AS n FROM examples")["n"]

    # ── logs ──
    def add_log(self, **f: Any) -> int:
        return self._exec(
            "INSERT INTO query_logs(ts,question,query_type,generated_sql,final_sql,status,error,latency_ms,total_ms,"
            "row_count,provider,model,retried,self_healed) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_now(), f.get("question", ""), f.get("query_type"), f.get("generated_sql"), f.get("final_sql"),
             f.get("status", "error"), f.get("error"), f.get("latency_ms"), f.get("total_ms"), f.get("row_count", 0),
             f.get("provider"), f.get("model"), int(bool(f.get("retried"))), int(bool(f.get("self_healed")))))

    def query_logs(self, status: Optional[str] = None, search: Optional[str] = None, query_type: Optional[str] = None,
                   limit: int = 100, offset: int = 0) -> dict:
        where, params = [], []
        if status:
            where.append("status=?"); params.append(status)
        if query_type:
            where.append("query_type=?"); params.append(query_type)
        if search:
            where.append("(question LIKE ? OR final_sql LIKE ? OR generated_sql LIKE ?)")
            params += [f"%{search}%"] * 3
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = self._one(f"SELECT COUNT(*) AS n FROM query_logs {clause}", tuple(params))["n"]
        rows = self._all(f"SELECT * FROM query_logs {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                         tuple(params) + (limit, offset))
        return {"total": total, "items": rows}

    def logs_csv(self, **filters: Any) -> str:
        rows = self.query_logs(limit=100000, **filters)["items"]
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return buf.getvalue()

    def log_stats(self) -> dict:
        return self._one(
            "SELECT COUNT(*) AS total, SUM(status='success') AS success, SUM(status='error') AS error, "
            "SUM(status='blocked') AS blocked, SUM(status='unsupported') AS unsupported, "
            "ROUND(AVG(latency_ms),1) AS avg_latency_ms FROM query_logs") or {}
