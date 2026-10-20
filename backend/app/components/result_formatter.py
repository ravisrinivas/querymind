"""Component 8 — Result Formatter: table payload + 1-2 sentence natural-language summary."""
from __future__ import annotations

import re

from ..llm.providers import ProviderError, effective_model, get_provider
from ..schemas import ExecutionResult, FormatterResult, TableData


def humanize(col: str) -> str:
    return re.sub(r"\s+", " ", col.replace("_", " ")).strip().lower()


def fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def template_summary(question: str, res: ExecutionResult) -> str:
    if res.row_count == 0:
        return "No rows matched this question."
    cols, rows = res.columns, res.rows
    if res.row_count == 1 and len(cols) == 1:
        return f"The {humanize(cols[0])} is {fmt(rows[0][0])}."
    if res.row_count == 1:
        return "Result: " + ", ".join(f"{humanize(c)} {fmt(v)}" for c, v in zip(cols, rows[0])) + "."
    first = ", ".join(f"{humanize(c)} {fmt(v)}" for c, v in zip(cols, rows[0]))
    tail = " (results were capped; refine the question to narrow them)" if res.truncated else ""
    return f"Found {res.row_count:,} rows{tail}. The first row has {first}."


class ResultFormatter:
    def format(self, question: str, res: ExecutionResult, cfg: dict | None = None) -> FormatterResult:
        table = TableData(columns=res.columns, rows=res.rows)
        summary = template_summary(question, res)
        provider = get_provider(cfg) if cfg else None
        if provider is not None and res.row_count > 0:
            sample = "\n".join(" | ".join(fmt(v) for v in r) for r in res.rows[:15])
            prompt = (f"Question: {question}\nResult columns: {', '.join(res.columns)}\nRows (first 15 of "
                      f"{res.row_count}):\n{sample}\n\nWrite a 1-2 sentence plain-English answer that states the key "
                      "finding with its numbers. Do not mention SQL or tables.")
            try:
                out = provider.complete("You summarise query results for business users. Be concise and factual.",
                                        prompt, model=effective_model(cfg), temperature=0.0, max_tokens=200)
                if out.strip():
                    summary = out.strip()
            except ProviderError:
                pass  # fall back to the template summary
        return FormatterResult(table=table, nl_summary=summary)
