"""Schema Manager: live DB introspection merged with admin-curated metadata (descriptions, synonyms, sensitivity)."""
from __future__ import annotations

import json
import threading
from collections import deque
from typing import Optional

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .config import DEMO_SYNONYMS_PATH
from .store import AdminStore

SAMPLE_VALUE_LIMIT = 12


class SchemaManager:
    def __init__(self, engine: Engine, store: AdminStore):
        self.engine = engine
        self.store = store
        self._lock = threading.RLock()
        self._raw: dict[str, dict] = {}
        self._samples: dict[tuple[str, str], list] = {}
        self._row_counts: dict[str, int] = {}
        self.seed_demo_metadata()
        self.refresh()

    # ───────────── introspection ─────────────
    def refresh(self) -> None:
        insp = inspect(self.engine)
        raw: dict[str, dict] = {}
        for t in sorted(insp.get_table_names()):
            pk = set(insp.get_pk_constraint(t).get("constrained_columns") or [])
            fks = {}
            for fk in insp.get_foreign_keys(t):
                for c, rc in zip(fk["constrained_columns"], fk["referred_columns"]):
                    fks[c] = f"{fk['referred_table']}.{rc}"
            raw[t] = {"columns": [{"name": c["name"], "type": str(c["type"]).upper(), "pk": c["name"] in pk,
                                   "nullable": bool(c.get("nullable", True)), "fk": fks.get(c["name"])}
                                  for c in insp.get_columns(t)]}
        samples, counts = {}, {}
        with self.engine.connect() as conn:
            for t, info in raw.items():
                counts[t] = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0
                for c in info["columns"]:
                    if "CHAR" in c["type"] or "TEXT" in c["type"]:
                        vals = [r[0] for r in conn.execute(
                            text(f'SELECT DISTINCT "{c["name"]}" FROM "{t}" WHERE "{c["name"]}" IS NOT NULL '
                                 f'LIMIT {SAMPLE_VALUE_LIMIT + 1}'))]
                        if 0 < len(vals) <= SAMPLE_VALUE_LIMIT:
                            samples[(t, c["name"])] = sorted(vals)
        with self._lock:
            self._raw, self._samples, self._row_counts = raw, samples, counts

    def seed_demo_metadata(self) -> None:
        """Load bundled demo descriptions/synonyms the first time the admin store is empty."""
        if self.store.all_column_meta() or self.store.all_table_meta() or not DEMO_SYNONYMS_PATH.exists():
            return
        data = json.loads(DEMO_SYNONYMS_PATH.read_text())
        for t, m in data.get("tables", {}).items():
            self.store.upsert_table_meta(t, m.get("description"), m.get("synonyms"))
        for key, m in data.get("columns", {}).items():
            t, c = key.split(".", 1)
            self.store.upsert_column_meta(t, c, m.get("description"), m.get("sensitive", False), m.get("synonyms"))

    # ───────────── accessors ─────────────
    @property
    def tables(self) -> list[str]:
        return list(self._raw)

    def columns_of(self, table: str) -> list[str]:
        return [c["name"] for c in self._raw.get(table, {}).get("columns", [])]

    def get_schema(self) -> list[dict]:
        cmeta, tmeta = self.store.all_column_meta(), self.store.all_table_meta()
        out = []
        for t, info in self._raw.items():
            tm = tmeta.get(t, {"description": "", "synonyms": []})
            out.append({
                "name": t, "description": tm["description"], "synonyms": tm["synonyms"],
                "row_count": self._row_counts.get(t, 0),
                "columns": [{
                    **c, "description": cmeta.get((t, c["name"]), {}).get("description", ""),
                    "is_sensitive": cmeta.get((t, c["name"]), {}).get("is_sensitive", False),
                    "synonyms": cmeta.get((t, c["name"]), {}).get("synonyms", []),
                    "sample_values": self._samples.get((t, c["name"]), []),
                } for c in info["columns"]],
            })
        return out

    def schema_dict(self) -> dict[str, dict[str, str]]:
        """{table: {column: type}} (lower-cased) for validator/qualification — includes sensitive columns."""
        return {t.lower(): {c["name"].lower(): c["type"] for c in info["columns"]} for t, info in self._raw.items()}

    def sensitive_columns(self) -> set[tuple[str, str]]:
        return {(t.lower(), c.lower()) for (t, c), m in self.store.all_column_meta().items() if m["is_sensitive"]}

    def fk_graph(self) -> dict[str, set[str]]:
        g: dict[str, set[str]] = {t: set() for t in self._raw}
        for t, info in self._raw.items():
            for c in info["columns"]:
                if c["fk"]:
                    ref = c["fk"].split(".")[0]
                    if ref != t:
                        g[t].add(ref); g.setdefault(ref, set()).add(t)
        return g

    def distances_from(self, sources: list[str]) -> dict[str, int]:
        """Multi-source BFS distance (in FK hops) from `sources` to every table."""
        g, dist = self.fk_graph(), {}
        dq = deque()
        for s in sources:
            if s in g:
                dist[s] = 0; dq.append(s)
        while dq:
            cur = dq.popleft()
            for n in g[cur]:
                if n not in dist:
                    dist[n] = dist[cur] + 1; dq.append(n)
        return dist

    # ───────────── prompt rendering ─────────────
    def prompt_text(self, focus_tables: Optional[list[str]] = None, max_tables_full: int = 14) -> str:
        """Schema text for the LLM. Sensitive columns are never included. Large schemas are pruned to the
        focus tables plus their FK neighbours."""
        schema = self.get_schema()
        if focus_tables and len(schema) > max_tables_full:
            keep = set(focus_tables)
            for t in list(keep):
                keep |= self.fk_graph().get(t, set())
            schema = [t for t in schema if t["name"] in keep]
        lines = []
        for t in schema:
            lines.append(f"TABLE {t['name']}" + (f"  -- {t['description']}" if t["description"] else ""))
            for c in t["columns"]:
                if c["is_sensitive"]:
                    continue
                bits = [c["type"]]
                if c["pk"]:
                    bits.append("PRIMARY KEY")
                if c["fk"]:
                    bits.append(f"REFERENCES {c['fk']}")
                note = c["description"]
                if c["sample_values"]:
                    note += (" " if note else "") + "Values: " + ", ".join(f"'{v}'" for v in c["sample_values"])
                lines.append(f"  {c['name']} {' '.join(bits)}" + (f"  -- {note}" if note else ""))
            lines.append("")
        return "\n".join(lines).strip()

    # ───────────── updates ─────────────
    def update_column(self, table: str, column: str, **kw) -> None:
        if column not in self.columns_of(table):
            raise KeyError(f"{table}.{column} not found")
        self.store.upsert_column_meta(table, column, **kw)

    def update_table(self, table: str, **kw) -> None:
        if table not in self._raw:
            raise KeyError(f"table {table} not found")
        self.store.upsert_table_meta(table, **kw)
