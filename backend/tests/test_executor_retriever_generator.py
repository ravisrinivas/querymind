import json

import pytest

from app.components.sql_generator import build_prompt, parse_llm_output
from app.schemas import ClassifierResult, Example, GeneratorRequest, LinkerResult, QueryType


# ───── executor ─────
def test_executor_returns_rows_columns_latency(pipe):
    r = pipe.executor.execute("SELECT COUNT(*) AS n FROM orders")
    assert r.columns == ["n"] and r.rows == [[5000]] and r.row_count == 1 and r.latency_ms > 0 and not r.error


def test_executor_is_read_only_even_if_validator_is_bypassed(pipe):
    for sql in ["DELETE FROM orders", "DROP TABLE orders", "UPDATE products SET unit_price = 0",
                "INSERT INTO categories(name) VALUES ('x')"]:
        assert pipe.executor.execute(sql).error, sql
    assert pipe.executor.execute("SELECT COUNT(*) FROM orders").rows == [[5000]]


def test_executor_truncates_and_times_out(pipe):
    r = pipe.executor.execute("SELECT * FROM orders", max_rows=10)
    assert r.row_count == 10 and r.truncated
    slow = pipe.executor.execute("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT COUNT(*) FROM c", timeout_s=1)
    assert "time limit" in slow.error


def test_executor_reports_sql_errors(pipe):
    assert pipe.executor.execute("SELECT nope FROM orders").error


# ───── retriever ─────
def test_retriever_returns_k_sorted_by_score(pipe):
    ex = pipe.retriever.retrieve("how many customers per country", k=4).examples
    assert len(ex) == 4 and ex[0].score >= ex[-1].score
    assert "country" in ex[0].question.lower()
    assert 3 <= len(pipe.retriever.retrieve("anything", k=5).examples) <= 5


def test_retriever_reflects_add_and_delete(pipe):
    new_id = pipe.store.add_example("What is the gizmo flux capacity?", "SELECT 1", "SELECT_SIMPLE")
    pipe.retriever.reindex()
    assert pipe.retriever.retrieve("gizmo flux capacity", k=1).examples[0].id == new_id
    pipe.store.delete_example(new_id)
    pipe.retriever.reindex()
    assert all(e.id != new_id for e in pipe.retriever.retrieve("gizmo flux capacity", k=5).examples)


def test_retriever_numpy_fallback(pipe):
    from app.components.examples_retriever import ExamplesRetriever
    r = ExamplesRetriever(pipe.store, use_chroma=False)
    assert r.backend == "numpy" and r.retrieve("customers per country", k=2).examples


def test_empty_library(pipe):
    for e in pipe.store.list_examples():
        pipe.store.delete_example(e["id"])
    pipe.retriever.reindex()
    assert pipe.retriever.retrieve("x").examples == []


# ───── generator ─────
@pytest.mark.parametrize("raw,sql", [
    ('{"sql": "SELECT 1", "explanation": "one"}', "SELECT 1"),
    ('```json\n{"sql": "SELECT 2", "explanation": "x"}\n```', "SELECT 2"),
    ("Here you go:\n```sql\nSELECT 3\n```", "SELECT 3"),
    ("SELECT 4 FROM orders", "SELECT 4 FROM orders"),
])
def test_parse_llm_output(raw, sql):
    assert parse_llm_output(raw)[0] == sql


def test_prompt_contains_schema_rules_examples_and_hides_sensitive(pipe):
    link = pipe.linker.link("revenue by customer")
    req = GeneratorRequest(question="revenue by customer", classifier=ClassifierResult(query_type=QueryType.SELECT_AGGREGATE),
                           linker=link, examples=[Example(question="q1", sql="SELECT 1")],
                           previous_sql="SELECT bad", error_feedback="[UNKNOWN_COLUMN] bad")
    prompt = build_prompt(req, pipe.schema, "- revenue excludes cancelled")
    assert "TABLE orders" in prompt and "Business rules" in prompt and "Q: q1" in prompt
    assert "previous attempt failed" in prompt and "revenue" in prompt
    assert "email" not in prompt
    assert "Values: 'Consumer'" in prompt          # categorical sample values help the LLM
