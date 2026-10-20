"""QueryMind evaluation harness.

    python eval/run_eval.py                                   # offline retrieval baseline (no API key needed)
    ANTHROPIC_API_KEY=... python eval/run_eval.py --provider anthropic
    OPENAI_API_KEY=...    python eval/run_eval.py --provider openai --model gpt-4o
    python eval/run_eval.py --provider ollama --model llama3.1

Metrics (see assignment "Evaluation Harness Note"):
  * Execution accuracy  — generated SQL and ground-truth SQL are both executed; result sets are compared as
                          multisets of rows (row order ignored, floats rounded to 2 dp).
  * Lenient accuracy    — same, but extra columns in the generated result are tolerated (every ground-truth column
                          must appear with identical values). Reported separately; the strict number is the headline.
  * Exact match         — normalised SQL string equality, or sqlglot.diff() reporting no edits.
  * Guardrails          — destructive natural-language requests AND raw destructive SQL (pushed through the full
                          pipeline via a scripted "malicious LLM") must all be blocked, and DB row counts unchanged.
Outputs eval/results.json and EVALUATION_REPORT.md.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sqlglot  # noqa: E402
from sqlglot.diff import Keep, diff  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.components.sql_generator as gen_mod  # noqa: E402
from app.config import PROVIDER_DEFAULT_MODELS  # noqa: E402
from app.pipeline import QueryMindPipeline  # noqa: E402
from app.schemas import QueryRequest  # noqa: E402
from app.store import AdminStore  # noqa: E402

TEST_SET = ROOT / "eval" / "test_set.json"
TYPES = ["SELECT_SIMPLE", "SELECT_AGGREGATE", "SELECT_JOIN", "SELECT_TEMPORAL"]


# ───────────────────────── comparison helpers ─────────────────────────
def norm_val(v):
    return round(v, 2) if isinstance(v, float) else v


def norm_rows(rows) -> Counter:
    return Counter(tuple(norm_val(v) for v in r) for r in rows)


def run_sql(engine, sql: str):
    with engine.connect() as c:
        res = c.execute(text(sql))
        return list(res.keys()), [list(r) for r in res.fetchall()]


def lenient_match(gt_cols, gt_rows, g_cols, g_rows) -> bool:
    if len(gt_rows) != len(g_rows):
        return False
    g_vecs = [Counter(norm_val(r[i]) for r in g_rows) for i in range(len(g_cols))]
    for j in range(len(gt_cols)):
        want = Counter(norm_val(r[j]) for r in gt_rows)
        if not any(want == gv for gv in g_vecs):
            return False
    return True


def canonical(sql: str) -> str:
    return sqlglot.parse_one(sql, read="sqlite").sql(dialect="sqlite", normalize=True, pretty=False).lower()


def exact_match(gen_sql: str, gt_sql: str) -> bool:
    try:
        if canonical(gen_sql) == canonical(gt_sql):
            return True
        edits = diff(sqlglot.parse_one(gen_sql, read="sqlite"), sqlglot.parse_one(gt_sql, read="sqlite"))
        return all(isinstance(e, Keep) for e in edits)
    except Exception:  # noqa: BLE001
        return False


# ───────────────────────── scripted malicious LLM ─────────────────────────
class ScriptedProvider:
    """Always answers with a fixed SQL string — simulates a jailbroken / prompt-injected model."""
    name = "scripted"

    def __init__(self, sql: str):
        self.sql = sql

    def complete(self, system, user, *, model, temperature, max_tokens):
        return json.dumps({"sql": self.sql, "explanation": "scripted"})


class OracleProvider:
    """Sanity-check provider: reads the question out of the real prompt and answers with the ground-truth SQL.
    A correct harness must score ~100% on it."""
    name = "oracle"

    def __init__(self, gt: dict[str, str]):
        self.gt = gt

    def complete(self, system, user, *, model, temperature, max_tokens):
        q = user.rsplit("### Question\n", 1)[-1].strip()
        return json.dumps({"sql": self.gt.get(q, "SELECT 1 FROM nonexistent_table"), "explanation": "oracle"})


def table_counts(engine, tables) -> dict:
    with engine.connect() as c:
        return {t: c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() for t in tables}


# ───────────────────────── main ─────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=None, choices=list(PROVIDER_DEFAULT_MODELS))
    ap.add_argument("--model", default=None)
    ap.add_argument("--k", type=int, default=4, help="few-shot examples per question")
    ap.add_argument("--oracle", action="store_true", help="harness self-check: 'LLM' returns ground-truth SQL")
    ap.add_argument("--out", default=str(ROOT / "eval"))
    ap.add_argument("--report", default=str(ROOT / "EVALUATION_REPORT.md"))
    args = ap.parse_args()

    data = json.loads(TEST_SET.read_text())
    pipe = QueryMindPipeline(store=AdminStore(":memory:"))        # isolated store: eval never pollutes real logs
    settings = {"temperature": 0.0, "k_examples": args.k, "self_heal": True, "clarify_ambiguities": False}
    if args.provider:
        settings["provider"] = args.provider
        settings["model"] = args.model or PROVIDER_DEFAULT_MODELS[args.provider]
    elif args.model:
        settings["model"] = args.model
    pipe.store.update_settings("model", settings)
    if args.oracle:
        gen_mod.get_provider = lambda cfg: OracleProvider({t["question"]: t["sql"] for t in data["tests"]})
        pipe.store.update_settings("model", {"provider": "anthropic", "model": "oracle"})
    cfg = pipe.store.get_settings("model")
    print(f"Provider={cfg['provider']} model={cfg['model']} examples={pipe.store.count_examples()} "
          f"retriever={pipe.retriever.backend}\n")

    # ── 1. SQL accuracy ──
    rows_out = []
    for t in data["tests"]:
        resp = pipe.run(QueryRequest(question=t["question"]))
        gt_cols, gt_rows = run_sql(pipe.engine, t["sql"])
        rec = {"id": t["id"], "question": t["question"], "query_type": t["query_type"], "gt_sql": t["sql"],
               "status": resp.status, "generated_sql": resp.generated_sql, "executed_sql": resp.sql, "error": resp.error,
               "predicted_type": resp.query_type.value if resp.query_type else None, "total_ms": resp.total_ms,
               "retried": resp.retried, "self_healed": resp.self_healed,
               "exec_match": False, "lenient_match": False, "exact_match": False}
        if resp.status == "success" and resp.table:
            rec["exec_match"] = norm_rows(gt_rows) == norm_rows(resp.table.rows)
            rec["lenient_match"] = rec["exec_match"] or lenient_match(gt_cols, gt_rows, resp.table.columns, resp.table.rows)
        if resp.generated_sql:
            rec["exact_match"] = exact_match(resp.generated_sql, t["sql"])
        rows_out.append(rec)
        print(f"{'PASS' if rec['exec_match'] else 'FAIL'}  {t['id']}  [{t['query_type'][7:]:9s}] {t['question'][:70]}")

    n = len(rows_out)
    exec_acc = sum(r["exec_match"] for r in rows_out) / n
    lenient_acc = sum(r["lenient_match"] for r in rows_out) / n
    exact_rate = sum(r["exact_match"] for r in rows_out) / n
    cls_acc = sum(r["predicted_type"] == r["query_type"] for r in rows_out) / n
    by_type = {}
    for ty in TYPES:
        sub = [r for r in rows_out if r["query_type"] == ty]
        by_type[ty] = {"n": len(sub), "execution_accuracy": sum(r["exec_match"] for r in sub) / len(sub),
                       "lenient_accuracy": sum(r["lenient_match"] for r in sub) / len(sub),
                       "exact_match": sum(r["exact_match"] for r in sub) / len(sub),
                       "classifier_accuracy": sum(r["predicted_type"] == ty for r in sub) / len(sub)}
    lat = sorted(r["total_ms"] for r in rows_out)
    latency = {"p50_ms": statistics.median(lat), "p95_ms": lat[min(len(lat) - 1, int(0.95 * len(lat)))],
               "mean_ms": round(statistics.mean(lat), 1)}

    # ── 2. Guardrails (full pipeline) ──
    before = table_counts(pipe.engine, pipe.schema.tables)
    guard_rows = []
    for q in data["guardrail_nl_attempts"]:
        r = pipe.run(QueryRequest(question=q))
        guard_rows.append({"kind": "natural-language", "input": q, "status": r.status, "blocked": r.status in ("unsupported", "blocked") })
    real_get_provider = gen_mod.get_provider
    pipe.store.update_settings("model", {"provider": "anthropic"})        # force the (scripted) LLM path
    try:
        for bad in data["guardrail_sql_attempts"]:
            gen_mod.get_provider = lambda cfg, _b=bad: ScriptedProvider(_b)
            r = pipe.run(QueryRequest(question="Show me some data about the shop"))
            guard_rows.append({"kind": "malicious-SQL (via scripted LLM)", "input": bad, "status": r.status,
                               "blocked": r.status in ("blocked", "error") and r.sql is None})
    finally:
        gen_mod.get_provider = real_get_provider
        pipe.store.update_settings("model", {"provider": cfg["provider"]})
    after = table_counts(pipe.engine, pipe.schema.tables)
    db_unchanged = before == after
    guard_rate = sum(g["blocked"] for g in guard_rows) / len(guard_rows)

    results = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": cfg["provider"], "model": cfg["model"], "k_examples": args.k,
        "n_examples_in_library": pipe.store.count_examples(), "retriever": pipe.retriever.backend,
        "embedder": pipe.retriever.embedder.name,
        "metrics": {"execution_accuracy": exec_acc, "lenient_accuracy": lenient_acc, "exact_match_rate": exact_rate,
                    "classifier_accuracy": cls_acc, "guardrails_compliance": guard_rate, "db_unchanged": db_unchanged},
        "by_type": by_type, "latency": latency, "queries": rows_out, "guardrail_cases": guard_rows,
    }
    Path(args.out, "results.json").write_text(json.dumps(results, indent=1, default=str))
    Path(args.report).write_text(render_report(results))

    print(f"\nExecution accuracy : {exec_acc:6.1%}   (lenient {lenient_acc:.1%})")
    print(f"Exact match        : {exact_rate:6.1%}")
    print(f"Classifier         : {cls_acc:6.1%}")
    print(f"Guardrails         : {guard_rate:6.1%}  ({sum(g['blocked'] for g in guard_rows)}/{len(guard_rows)}), DB unchanged={db_unchanged}")
    print(f"\nReport -> {args.report}")
    return 0


def pct(x: float) -> str:
    return f"{x:.0%}"


def render_report(r: dict) -> str:
    m = r["metrics"]
    offline = r["provider"] == "offline"
    auto_score = 30 * m["execution_accuracy"] + 15 * m["exact_match_rate"] + 15 * m["guardrails_compliance"]
    L = [f"# QueryMind — Evaluation Report", "",
         f"*Run at {r['run_at']} · provider `{r['provider']}` · model `{r['model']}` · "
         f"{r['n_examples_in_library']} few-shot examples (k={r['k_examples']}, {r['retriever']}, embedder `{r['embedder']}`)*", ""]
    if offline:
        L += ["> **Read this first.** This run used the **offline retrieval baseline** (nearest few-shot example plus "
              "literal slot-filling). It exists so the harness and pipeline can be verified without an API key; it is "
              "*not* an LLM result and is a floor, not an estimate of production accuracy. Re-run with "
              "`--provider anthropic|openai|ollama` and replace this report with those numbers.", ""]
    L += ["## Headline metrics (25-query test set)", "",
          "| Metric | Result | Rubric weight |", "|---|---|---|",
          f"| Execution accuracy (strict, row-multiset match) | **{pct(m['execution_accuracy'])}** | 30% |",
          f"| Execution accuracy (lenient: extra columns tolerated) | {pct(m['lenient_accuracy'])} | informational |",
          f"| Exact match (sqlglot-normalised / diff) | **{pct(m['exact_match_rate'])}** | 15% |",
          f"| Guardrails compliance ({sum(g['blocked'] for g in r['guardrail_cases'])}/{len(r['guardrail_cases'])} attacks blocked, DB unchanged: {m['db_unchanged']}) | **{pct(m['guardrails_compliance'])}** | 15% |",
          f"| Query-type classifier accuracy | {pct(m['classifier_accuracy'])} | informational |",
          f"| Latency end-to-end p50 / p95 | {r['latency']['p50_ms']:.0f} ms / {r['latency']['p95_ms']:.0f} ms | — |", "",
          f"Automatically measurable score: **{auto_score:.1f} / 60** (Admin UI, modularity and documentation are assessed separately). "
          f"Passing gate: execution accuracy ≥ 50% → **{'met' if m['execution_accuracy'] >= 0.5 else 'NOT met'}**.", "",
          "## Per-query-type breakdown", "",
          "| Query type | n | Execution acc. | Lenient acc. | Exact match | Classifier correct |", "|---|---|---|---|---|---|"]
    for ty, b in r["by_type"].items():
        L.append(f"| {ty} | {b['n']} | {pct(b['execution_accuracy'])} | {pct(b['lenient_accuracy'])} | "
                 f"{pct(b['exact_match'])} | {pct(b['classifier_accuracy'])} |")
    L += ["", "## Per-query results", "", "| ID | Type | Question | Status | Exec | Exact |", "|---|---|---|---|---|---|"]
    for q in r["queries"]:
        L.append(f"| {q['id']} | {q['query_type'][7:]} | {q['question']} | {q['status']} | "
                 f"{'✅' if q['exec_match'] else ('➖' if q['lenient_match'] else '❌')} | {'✅' if q['exact_match'] else '❌'} |")
    L += ["", "✅ strict match · ➖ lenient-only (right values, extra/reordered columns) · ❌ mismatch", "",
          "## Failures (ground truth vs generated)", ""]
    fails = [q for q in r["queries"] if not q["exec_match"]]
    if not fails:
        L.append("None.")
    for q in fails:
        L += [f"**{q['id']}** — {q['question']}", "```sql", f"-- ground truth\n{q['gt_sql']}", f"-- generated ({q['status']})",
              f"{q['generated_sql'] or q['error']}", "```", ""]
    L += ["## Guardrail cases", "", "| Kind | Input | Outcome | Blocked |", "|---|---|---|---|"]
    for g in r["guardrail_cases"]:
        L.append(f"| {g['kind']} | `{g['input'][:70]}` | {g['status']} | {'✅' if g['blocked'] else '❌'} |")
    L += ["", "## Reproducing", "", "```bash", "cd backend", "python data/seed_db.py          # deterministic seed (42)",
          "python eval/run_eval.py --provider anthropic   # or openai / ollama / (omit for offline baseline)", "```", "",
          "Methodology: both SQL statements are executed on the same read-only database; rows are compared as "
          "multisets (order ignored, floats rounded to 2 dp). Ground-truth SQL uses the conventions in "
          "`DEFAULT_BUSINESS_RULES` (revenue excludes cancelled orders; today = 2025-12-31). Exact match compares "
          "sqlglot-normalised SQL or an empty `sqlglot.diff` — it is intentionally strict, so equivalent queries with "
          "different aliases count as execution matches but not exact matches."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
