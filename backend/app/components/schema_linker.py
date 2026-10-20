"""Component 3 — Schema Linker.

Maps words in the question onto tables/columns using (a) table & column names, (b) admin-curated synonyms from
the Schema Manager, and (c) FK-graph proximity to disambiguate columns that several tables could satisfy
(e.g. "revenue" → orders.total_amount | order_items.line_total | payments.amount).

Synonym convention: a trailing "*" marks the default pick for an ambiguous term ("revenue*").
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..llm.embeddings import lemma
from ..schema_manager import SchemaManager
from ..schemas import Ambiguity, LinkerResult


@dataclass
class _Target:
    kind: str                 # "table" | "column"
    table: str
    column: Optional[str] = None
    explicit: bool = True     # from admin synonyms (global) vs auto-derived from the column name
    unique_auto: bool = False  # auto term whose column name is unique across the schema
    default: bool = False

    @property
    def ref(self) -> str:
        return f"{self.table}.{self.column}" if self.column else self.table


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def norm_phrase(phrase: str) -> tuple[str, ...]:
    return tuple(lemma(w) for w in words(phrase.replace("_", " ")))


class SchemaLinker:
    def __init__(self, schema: SchemaManager):
        self.schema = schema

    # ───────────── lexicon ─────────────
    def _lexicon(self) -> dict[tuple[str, ...], list[_Target]]:
        lex: dict[tuple[str, ...], list[_Target]] = {}

        def add(phrase: str, tgt: _Target) -> None:
            key = norm_phrase(phrase)
            if key and tgt.ref not in {t.ref for t in lex.get(key, [])}:
                lex.setdefault(key, []).append(tgt)

        info = {t["name"]: t for t in self.schema.get_schema()}
        name_count: dict[str, int] = {}
        for t in info.values():
            for c in t["columns"]:
                name_count[c["name"]] = name_count.get(c["name"], 0) + 1
        for tname, t in info.items():
            add(tname, _Target("table", tname))
            for s in t["synonyms"]:
                add(s.rstrip("*"), _Target("table", tname))
            for c in t["columns"]:
                if c["is_sensitive"]:
                    continue                                  # sensitive columns never enter the lexicon
                cname = c["name"]
                if not (cname.endswith("_id") or cname == "id"):
                    add(cname, _Target("column", tname, cname, explicit=False, unique_auto=name_count[cname] == 1))
                for s in c["synonyms"]:
                    add(s.rstrip("*"), _Target("column", tname, cname, default=s.endswith("*")))
        # Categorical values that live in exactly one column ("Books", "paypal", "refunded") imply their table.
        owners: dict[str, set[str]] = {}
        for tname, t in info.items():
            for c in t["columns"]:
                if not c["is_sensitive"]:
                    for v in c["sample_values"]:
                        owners.setdefault(str(v), set()).add(tname)
        for value, tables in owners.items():
            if len(tables) == 1 and len(norm_phrase(value)) >= 1:
                add(value, _Target("table", next(iter(tables))))
        return lex

    # ───────────── main entry ─────────────
    def link(self, question: str, clarifications: Optional[dict[str, str]] = None) -> LinkerResult:
        clarifications = {k.lower(): v for k, v in (clarifications or {}).items()}
        raw = words(question)
        toks = [lemma(w) for w in raw]
        lex = self._lexicon()
        consumed = [False] * len(toks)
        hits: list[tuple[int, str, list[_Target]]] = []       # (position, surface phrase, targets)

        for key in sorted(lex, key=lambda k: -len(k)):
            n = len(key)
            for i in range(len(toks) - n + 1):
                if tuple(toks[i:i + n]) == key and not any(consumed[i:i + n]):
                    for j in range(i, i + n):
                        consumed[j] = True
                    hits.append((i, " ".join(raw[i:i + n]), lex[key]))
        hits.sort(key=lambda h: h[0])

        mentioned: list[str] = []
        for _, _, targets in hits:
            for t in targets:
                if t.kind == "table" and t.table not in mentioned:
                    mentioned.append(t.table)

        resolved_cols: list[str] = []
        ambiguous: list[tuple[str, list[_Target]]] = []
        for _, surface, targets in hits:
            cols = [t for t in targets if t.kind == "column"]
            # auto-derived names that exist in several tables only count when their table is mentioned
            cols = [t for t in cols if t.explicit or t.unique_auto or t.table in mentioned]
            if not cols:
                continue
            if len(cols) == 1:
                if cols[0].ref not in resolved_cols:
                    resolved_cols.append(cols[0].ref)
            else:
                ambiguous.append((surface, cols))

        context_tables = list(dict.fromkeys(mentioned + [r.split(".")[0] for r in resolved_cols]))
        ambiguities: list[Ambiguity] = []
        for surface, cols in ambiguous:
            refs = [c.ref for c in cols]
            amb = Ambiguity(term=surface, candidates=refs)
            forced = clarifications.get(surface.lower())
            if forced in refs:
                amb.chosen, amb.resolved_by = forced, "user"
            else:
                inside = [c for c in cols if c.table in context_tables]
                if len(inside) == 1:
                    amb.chosen, amb.resolved_by = inside[0].ref, "context"
                elif context_tables:
                    dist = self.schema.distances_from(context_tables)
                    best = min(dist.get(c.table, 99) for c in cols)
                    nearest = [c for c in cols if dist.get(c.table, 99) == best]
                    if len(nearest) == 1:
                        amb.chosen, amb.resolved_by = nearest[0].ref, "context"
                if amb.chosen is None:
                    defaults = [c for c in cols if c.default]
                    if len(defaults) >= 1:
                        amb.chosen, amb.resolved_by = defaults[0].ref, "default"
            if amb.chosen and amb.chosen not in resolved_cols:
                resolved_cols.append(amb.chosen)
            ambiguities.append(amb)

        resolved_tables = list(dict.fromkeys(mentioned + [r.split(".")[0] for r in resolved_cols]))
        return LinkerResult(resolved_tables=resolved_tables, resolved_columns=resolved_cols, ambiguities=ambiguities)
