"""Deterministic plain-English breakdown of a SELECT statement (bonus: Query Explanation Mode)."""
from __future__ import annotations

import sqlglot
from sqlglot import exp


def describe_sql(sql: str, dialect: str = "sqlite") -> str:
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:  # noqa: BLE001
        return ""
    if not isinstance(tree, exp.Query):
        return ""
    sel = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if sel is None:
        return ""
    parts: list[str] = []
    tables = []
    for t in sel.find_all(exp.Table):
        if t.name not in tables:
            tables.append(t.name)
    joins = sel.args.get("joins") or []
    if joins:
        parts.append(f"Combines {', '.join(tables)} by joining them on their keys")
    elif tables:
        parts.append(f"Reads from the {tables[0]} table")
    outs = []
    for e in sel.expressions:
        if isinstance(e, exp.Star):
            outs.append("all columns")
        elif e.find(exp.AggFunc):
            agg = e.find(exp.AggFunc)
            name = type(agg).__name__.replace("Func", "").lower()
            nice = {"sum": "the total of", "avg": "the average of", "count": "the number of", "min": "the minimum of",
                    "max": "the maximum of"}.get(name, name + " of")
            arg = agg.this.sql(dialect=dialect) if agg.this is not None else "rows"
            outs.append(f"{nice} {'rows' if arg == '*' else arg}")
        else:
            outs.append(e.alias_or_name or e.sql(dialect=dialect))
    if outs:
        parts.append("returns " + ", ".join(outs[:6]) + ("…" if len(outs) > 6 else ""))
    where = sel.args.get("where")
    if where:
        parts.append("keeps only rows where " + where.this.sql(dialect=dialect))
    group = sel.args.get("group")
    if group:
        parts.append("grouped by " + ", ".join(g.sql(dialect=dialect) for g in group.expressions))
    having = sel.args.get("having")
    if having:
        parts.append("keeps groups where " + having.this.sql(dialect=dialect))
    order = sel.args.get("order")
    if order:
        parts.append("sorted by " + ", ".join(o.sql(dialect=dialect) for o in order.expressions))
    limit = tree.args.get("limit") or sel.args.get("limit")
    if limit is not None and limit.args.get("expression") is not None:
        parts.append(f"limited to {limit.args['expression'].sql(dialect=dialect)} rows")
    return "; ".join(parts) + "." if parts else ""
