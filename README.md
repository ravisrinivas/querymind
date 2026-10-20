# QueryMind AI — Text-to-SQL Analytics Engine with Admin UI

Ask business questions in plain English; get a table, a one-line answer, and the SQL that produced it. Data engineers manage the schema, few-shot examples, guardrails and model from an admin UI.

**Domain:** e-commerce on **SQLite** (zero setup, deterministic seed). Chosen because "revenue" is genuinely ambiguous there (order totals vs line totals vs payments), it has a real many-to-many bridge (`order_items`), and it needs date arithmetic (delivery times, quarters, rolling windows). PostgreSQL/MySQL are supported through SQLAlchemy URLs but **have not been tested** (see Limitations).

```
NL question → Classifier → Schema Linker → Examples Retriever → SQL Generator → SQL Validator ─┐
                (blocks writes)  (synonyms, ambiguity)  (ChromaDB top-k)      (LLM + few-shot)   │ 1 retry w/ error
                                                                                                 ▼
                                            Result Formatter ← SQL Executor (read-only, timeout, LIMIT)
```

## Setup (5 minutes)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python data/seed_db.py                       # creates data/ecommerce.db
cp .env.example .env                         # then export ANTHROPIC_API_KEY (or OPENAI_API_KEY) — optional
uvicorn app.main:app --reload --port 8000    # API docs: http://localhost:8000/docs

# Frontend (new terminal)
cd frontend
npm install
cp .env.local.example .env.local
npm run dev                                  # http://localhost:3000
```

With **no API key** the app starts in *offline baseline* mode (nearest solved example + literal slot-filling). That is for testing the plumbing only — it will answer few novel questions correctly. Export `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` (or run Ollama) and pick the provider in **Admin → Model config**.

Run the tests and evaluation:
```bash
cd backend
python -m pytest tests -q                    # 84 tests
python eval/run_eval.py --provider anthropic # writes eval/results.json + EVALUATION_REPORT.md
python eval/run_eval.py --oracle --out /tmp --report /tmp/oracle.md   # harness self-check (should be 100%)
```

## What's where

| Deliverable | Location |
|---|---|
| Pipeline (8 components, typed I/O) | `backend/app/components/*`, orchestrated by `backend/app/pipeline.py`, contracts in `app/schemas.py` |
| DB, DDL, seed, data dictionary | `backend/data/schema.sql`, `seed_db.py`, `docs/DATA_DICTIONARY.md` |
| REST API | `/query`, `/admin/schema`, `/admin/examples`, `/admin/logs`, `/admin/guardrails`, `/admin/config` (+ `/components/*` to call each stage alone) |
| Frontend | `frontend/` — chat page + 5 admin panels |
| Few-shot library (34 pairs, all four types) | `backend/data/examples_seed.json` (loaded on first start; then managed in the UI) |
| 25-query test set + ground truth + 27 attack cases | `backend/eval/test_set.json` |
| Evaluation harness / report | `backend/eval/run_eval.py` → `backend/EVALUATION_REPORT.md` |

## Sample questions
- *What was total revenue by month in 2025?* (temporal; "revenue" → `orders.total_amount`)
- *How much revenue did each product category generate?* ("revenue" → `order_items.line_total`)
- *Average delivery time in days by carrier* (date arithmetic)
- *Top 5 customers by revenue last quarter* ("last quarter" is defined in Business rules → Q3 2025)
- *Delete all cancelled orders* → refused before reaching the model

## Safety model (defence in depth)
1. **Classifier** rejects modification intents and prompt-injection phrasing before any LLM call.
2. The **LLM prompt** demands a single SELECT and omits sensitive columns entirely.
3. The **Validator** parses the SQL (sqlglot): blocks DROP/DELETE/UPDATE/INSERT/TRUNCATE/ALTER and any non-SELECT root (PRAGMA, ATTACH, CREATE, REPLACE…) unless toggled on; rejects multiple statements; checks every table and column exists; rejects sensitive columns (including via `SELECT *` and aliases); enforces table scope; appends/clamps `LIMIT`. The executed SQL is regenerated from the validated AST.
4. The **Executor** connects with SQLite `mode=ro` + `PRAGMA query_only` and enforces a timeout. Even with every guardrail toggle on, writes fail unless the server sets `QUERYMIND_ALLOW_WRITES=1`.

## Bonus features implemented
Self-healing SQL (one retry with the DB error) · ambiguity clarification prompts · query explanation mode (LLM explanation + deterministic AST breakdown) · SQL dialect transpilation for display (`sqlglot.transpile`) · chart auto-generation (2-column numeric results) · voice input (Web Speech API). **Not implemented:** semantic caching.

## Known limitations (please read)
- **No LLM accuracy numbers are included.** I had no API access while building this, so `backend/EVALUATION_REPORT.md` is the *offline baseline* (0% execution accuracy — it can only reuse library queries and the test set is disjoint from the library). The harness itself is verified: an oracle run returns 100%. Run `python eval/run_eval.py --provider …` with your key to get real figures; the ≥ 50% execution-accuracy gate has **not** been demonstrated.
- The default embedder is a dependency-free hashing/IDF model so ChromaDB works offline. It is lexical, not semantic ("cheapest" doesn't match "expensive"). For production set `EMBEDDING_BACKEND=sbert` after `pip install sentence-transformers`.
- Only the SQLite path was tested. PostgreSQL/MySQL introspection, read-only transactions and timeouts are written but untested, and `seed_db.py` targets SQLite only.
- The UI was type-checked, built and smoke-tested over HTTP, but not exercised in a browser; expect some visual polish to be needed.
- The classifier is rule-based (100% on this test set, but regexes will miss unusual phrasing; the validator and read-only executor are the real safety net).
- Strict execution accuracy penalises harmless differences (extra columns); a lenient score is reported alongside.
- The ChromaDB index is rebuilt from SQLite on start and after each example edit — fine for hundreds of examples, not millions.
- No authentication on the admin API — put it behind your gateway before exposing it.
