"""Component 5 — SQL Generator: prompt assembly + LLM call (or offline retrieval baseline)."""
from __future__ import annotations

import json
import re
import time

from ..config import SUPPORTED_DIALECTS
from ..llm.providers import ProviderError, effective_model, get_provider
from ..schema_manager import SchemaManager
from ..schemas import Example, GeneratorRequest, GeneratorResult

DIALECT_HINTS = {
    "sqlite": "SQLite: dates are 'YYYY-MM-DD' text; use date(), strftime('%Y-%m', col), julianday() for day differences, "
              "|| for concatenation. There is no DATE_TRUNC, INTERVAL or ILIKE.",
    "postgres": "PostgreSQL: use DATE_TRUNC, EXTRACT, INTERVAL arithmetic, ILIKE, and '::' casts.",
    "mysql": "MySQL: use DATE_FORMAT, DATE_SUB/INTERVAL, YEAR()/MONTH(), CONCAT().",
}

SYSTEM_TMPL = """You are QueryMind, an expert {dialect_name} data analyst. Convert the user's question into ONE read-only SQL query.

Hard rules:
1. Output a single SELECT statement (a leading WITH ... SELECT is fine). Never write INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, PRAGMA or ATTACH.
2. Use ONLY the tables and columns in the schema below. Never invent columns. Never select columns that are not listed.
3. Prefer explicit column lists over SELECT *. Qualify columns when joining and use short table aliases.
4. Follow the business rules exactly; they define what "revenue", "last quarter", etc. mean.
5. {dialect_hint}
6. Return ONLY a JSON object, no markdown fences: {{"sql": "<the query>", "explanation": "<one or two plain-English sentences describing what the query does>"}}"""


def build_prompt(req: GeneratorRequest, schema: SchemaManager, business_rules: str) -> str:
    parts = ["### Schema\n" + schema.prompt_text(req.linker.resolved_tables)]
    if business_rules.strip():
        parts.append("### Business rules\n" + business_rules.strip())
    notes = []
    if req.linker.resolved_tables:
        notes.append("Likely relevant tables: " + ", ".join(req.linker.resolved_tables))
    if req.linker.resolved_columns:
        notes.append("Likely relevant columns: " + ", ".join(req.linker.resolved_columns))
    for a in req.linker.ambiguities:
        pick = f" -> use {a.chosen} ({a.resolved_by})" if a.chosen else " -> choose using the business rules"
        notes.append(f'"{a.term}" could mean {" or ".join(a.candidates)}{pick}')
    if notes:
        parts.append("### Resolved entities\n" + "\n".join(f"- {n}" for n in notes))
    if req.examples:
        parts.append("### Similar solved questions\n" + "\n\n".join(
            f"Q: {e.question}\nSQL: {e.sql}" for e in req.examples))
    if req.previous_sql and req.error_feedback:
        parts.append(f"### Your previous attempt failed\nSQL: {req.previous_sql}\nProblem: {req.error_feedback}\n"
                     "Fix the problem and return a corrected query.")
    parts.append(f"### Question\n{req.question}")
    return "\n\n".join(parts)


def parse_llm_output(raw: str) -> tuple[str, str]:
    text = raw.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and obj.get("sql"):
                return str(obj["sql"]).strip(), str(obj.get("explanation", "")).strip()
        except json.JSONDecodeError:
            pass
    fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    if fence:
        return fence.group(1).strip(), ""
    m = re.search(r"\b(select|with)\b.*", text, re.S | re.I)
    return (m.group(0).strip() if m else text), ""


# ───────────────────────── offline retrieval + slot-filling baseline ─────────────────────────
def _adapt_example_sql(question: str, ex: Example, schema: SchemaManager) -> str:
    sql, q = ex.sql, question
    # 1. top-N / LIMIT
    m = (re.search(r"\b(?:top|first|bottom)\s+(\d+)\b", q, re.I)
         or re.search(r"\b(\d+)\s+(?:most|largest|biggest|cheapest|latest|newest|oldest|recent|best|worst|top|biggest)\b", q, re.I)
         or re.search(r"\bthe\s+(\d+)\s+\w+", q, re.I))
    if m and re.search(r"\bLIMIT\s+\d+", sql, re.I):
        sql = re.sub(r"\bLIMIT\s+\d+", f"LIMIT {m.group(1)}", sql, flags=re.I)
    # 2. direction flip (cheapest vs most expensive)
    if (re.search(r"\b(cheapest|lowest|least|smallest|bottom|worst)\b", q, re.I)
            and re.search(r"\b(expensive|highest|most|largest|biggest|top|best)\b", ex.question, re.I)):
        sql = re.sub(r"\bDESC\b", "ASC", sql, count=1)
    # 3. year shift
    q_years = sorted(set(re.findall(r"\b(20\d\d)\b", q)))
    ex_years = sorted(set(re.findall(r"\b(20\d\d)\b", sql)))
    if len(q_years) == 1 and ex_years:
        delta = int(q_years[0]) - int(ex_years[0])
        if delta:
            sql = re.sub(r"\b(20\d\d)\b", lambda mm: str(int(mm.group(1)) + delta), sql)
    # 4. "last N days"
    m = re.search(r"\blast\s+(\d+)\s+days?\b", q, re.I)
    if m:
        sql = re.sub(r"'-\d+ days'", f"'-{m.group(1)} days'", sql)
    # 5. entity ids ("order 42", "product 77")
    for ent in ("order", "product", "customer", "supplier"):
        m = re.search(rf"\b{ent}\s+#?(\d+)\b", q, re.I)
        if m:
            sql = re.sub(rf"\b({ent}_id\s*=\s*)\d+", rf"\g<1>{m.group(1)}", sql)
    # 6. categorical literal swap using sample values from the live schema
    samples = {}
    for t in schema.get_schema():
        for c in t["columns"]:
            for v in c["sample_values"]:
                samples.setdefault(str(v), []).append((t["name"], c["name"]))
    for lit in set(re.findall(r"'([^'%]+)'", sql)):
        for (tn, cn) in samples.get(lit, []):
            siblings = [str(v) for t in schema.get_schema() if t["name"] == tn for c in t["columns"]
                        if c["name"] == cn for v in c["sample_values"]]
            repl = [v for v in siblings if v != lit and re.search(rf"\b{re.escape(v.lower())}\b", q.lower())]
            if repl:
                sql = sql.replace(f"'{lit}'", f"'{max(repl, key=len)}'")
                break
    return sql


def offline_generate(req: GeneratorRequest, schema: SchemaManager) -> tuple[str, str]:
    if not req.examples:
        raise ProviderError("Offline baseline needs at least one few-shot example; add some in the Examples Manager.")
    idx = 1 if (req.error_feedback and len(req.examples) > 1) else 0
    ex = req.examples[idx]
    sql = _adapt_example_sql(req.question, ex, schema)
    return sql, (f"Offline baseline: adapted the closest solved example ({ex.question!r}, similarity {ex.score}). "
                 "Connect an LLM in Model Config for real generation.")


class SQLGenerator:
    def __init__(self, schema: SchemaManager):
        self.schema = schema

    def generate(self, req: GeneratorRequest, cfg: dict) -> GeneratorResult:
        t0 = time.perf_counter()
        provider = get_provider(cfg)
        model = effective_model(cfg)
        if provider is None:
            sql, expl = offline_generate(req, self.schema)
            return GeneratorResult(sql=sql, explanation=expl, raw_response=sql, provider="offline", model=model,
                                   latency_ms=round((time.perf_counter() - t0) * 1000, 1))
        dialect = cfg.get("dialect", "sqlite")
        system = SYSTEM_TMPL.format(dialect_name=SUPPORTED_DIALECTS.get(dialect, dialect),
                                    dialect_hint=DIALECT_HINTS.get(dialect, ""))
        user = build_prompt(req, self.schema, cfg.get("business_rules", ""))
        raw = provider.complete(system, user, model=model, temperature=float(cfg.get("temperature", 0.0)),
                                max_tokens=int(cfg.get("max_tokens", 1024)))
        sql, expl = parse_llm_output(raw)
        return GeneratorResult(sql=sql, explanation=expl, raw_response=raw, provider=provider.name, model=model,
                               latency_ms=round((time.perf_counter() - t0) * 1000, 1))
