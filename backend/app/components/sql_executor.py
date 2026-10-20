"""Component 7 — SQL Executor: runs validated SQL on a read-only connection and measures latency."""
from __future__ import annotations

import datetime as dt
import decimal
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from ..db import set_deadline
from ..schemas import ExecutionResult


def jsonable(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    return v


class SQLExecutor:
    def __init__(self, engine: Engine):
        self.engine = engine

    def execute(self, sql: str, max_rows: int = 1000, timeout_s: float = 10) -> ExecutionResult:
        t0 = time.perf_counter()
        backend = self.engine.dialect.name
        try:
            set_deadline(timeout_s)
            with self.engine.connect() as conn:
                if backend == "postgresql":
                    conn.execute(text("SET TRANSACTION READ ONLY"))
                    conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_s * 1000)}"))
                elif backend == "mysql":
                    conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
                res = conn.execute(text(sql))
                cols = list(res.keys())
                fetched = res.fetchmany(max_rows + 1)
                conn.rollback()
            truncated = len(fetched) > max_rows
            rows = [[jsonable(v) for v in r] for r in fetched[:max_rows]]
            return ExecutionResult(rows=rows, columns=cols, row_count=len(rows), truncated=truncated,
                                   latency_ms=round((time.perf_counter() - t0) * 1000, 2))
        except (SQLAlchemyError, DBAPIError, Exception) as e:  # noqa: BLE001
            msg = str(getattr(e, "orig", None) or e)
            if "interrupted" in msg.lower():
                msg = f"Query exceeded the {timeout_s}s time limit and was cancelled."
            return ExecutionResult(error=msg.split("\n")[0][:400],
                                   latency_ms=round((time.perf_counter() - t0) * 1000, 2))
        finally:
            set_deadline(None)
