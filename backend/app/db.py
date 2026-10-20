"""Database engine factory. SQLite is opened read-only (URI mode=ro) and additionally set to query_only."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url

from .config import ALLOW_WRITES, DATABASE_URL

_local = threading.local()          # per-thread query deadline used by the SQLite progress handler


def set_deadline(seconds: float | None) -> None:
    _local.deadline = (time.monotonic() + seconds) if seconds else None


def make_engine(url: str = DATABASE_URL, read_only: bool = not ALLOW_WRITES) -> Engine:
    u = make_url(url)
    if u.get_backend_name() == "sqlite":
        path = Path(u.database or "").resolve()
        if not path.exists():
            raise FileNotFoundError(f"SQLite database not found at {path}. Run: python data/seed_db.py")
        uri = f"sqlite:///file:{path}?mode={'ro' if read_only else 'rw'}&uri=true"
        engine = create_engine(uri, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_conn, _):  # noqa: ANN001
            if read_only:
                dbapi_conn.execute("PRAGMA query_only = ON")

            def _progress():
                d = getattr(_local, "deadline", None)
                return 1 if d and time.monotonic() > d else 0
            dbapi_conn.set_progress_handler(_progress, 20000)
        return engine
    return create_engine(url, pool_pre_ping=True)
