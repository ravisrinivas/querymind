import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import QueryRequest

GOOD = "SELECT status, COUNT(*) AS n FROM orders GROUP BY status"


def run(pipe, q, **kw):
    return pipe.run(QueryRequest(question=q, **kw))


def test_happy_path_with_llm(pipe, use_llm):
    llm = use_llm(GOOD)
    r = run(pipe, "How many orders per status?")
    assert r.status == "success" and r.row_count == 5 and r.sql.endswith("LIMIT 500")
    assert r.table.columns == ["status", "n"] and r.nl_summary and r.explanation == "fake explanation"
    assert [t.stage for t in r.trace][:4] == ["schema_link", "classify", "retrieve_examples", "generate"]
    assert llm.calls == 1


def test_unsupported_never_reaches_llm(pipe, use_llm):
    llm = use_llm(GOOD)
    r = run(pipe, "Delete all cancelled orders")
    assert r.status == "unsupported" and llm.calls == 0 and "read-only" in r.error


def test_validation_failure_retries_once_with_feedback(pipe, use_llm):
    llm = use_llm("SELECT bogus FROM orders", GOOD)
    r = run(pipe, "orders per status")
    assert r.status == "success" and r.retried and llm.calls == 2
    assert "UNKNOWN_COLUMN" in llm.prompts[1] and "previous attempt failed" in llm.prompts[1]


def test_llm_emitting_destructive_sql_is_blocked_and_db_untouched(pipe, use_llm):
    llm = use_llm("DROP TABLE orders")
    r = run(pipe, "show me orders")
    assert r.status == "blocked" and r.sql is None and llm.calls == 2
    assert pipe.executor.execute("SELECT COUNT(*) FROM orders").rows == [[5000]]


def test_sensitive_select_star_blocked(pipe, use_llm):
    use_llm("SELECT * FROM customers")
    assert run(pipe, "all customer details").status == "blocked"


def test_execution_error_self_heals(pipe, use_llm):
    # valid per validator (julianday of text is fine) but fails at runtime: unknown function
    llm = use_llm("SELECT NOSUCHFUNC(order_id) FROM orders", GOOD)
    r = run(pipe, "orders per status")
    assert r.status == "success" and r.self_healed and llm.calls == 2


def test_self_heal_can_be_disabled(pipe, use_llm):
    pipe.store.update_settings("model", {"self_heal": False})
    use_llm("SELECT NOSUCHFUNC(order_id) FROM orders", GOOD)
    r = run(pipe, "orders per status")
    assert r.status == "error" and "Database error" in r.error


def test_clarification_flow(pipe, use_llm):
    llm = use_llm("SELECT SUM(amount) AS revenue FROM payments")
    r = run(pipe, "What was total revenue in 2024?", clarify=True)
    assert r.status == "needs_clarification" and llm.calls == 0
    assert set(r.ambiguities[0].candidates) >= {"orders.total_amount", "payments.amount"}
    r2 = run(pipe, "What was total revenue in 2024?", clarify=True, clarifications={"revenue": "payments.amount"})
    assert r2.status == "success"
    assert "payments.amount" in llm.prompts[0]


def test_row_cap_and_dialect_transpile(pipe, use_llm):
    pipe.store.update_settings("guardrails", {"max_rows": 7})
    pipe.store.update_settings("model", {"output_dialect": "postgres"})
    use_llm("SELECT order_id, strftime('%Y', order_date) AS y FROM orders")
    r = run(pipe, "list orders")
    assert r.row_count == 7 and "LIMIT 7" in r.sql
    assert r.sql_dialect_output and "LIMIT 7" in r.sql_dialect_output


def test_explain_mode(pipe, use_llm):
    use_llm(GOOD)
    r = run(pipe, "orders per status", explain=True)
    assert "Breakdown:" in r.explanation and "grouped by" in r.explanation


def test_provider_error_is_reported_not_raised(pipe):
    pipe.store.update_settings("model", {"provider": "anthropic"})   # no API key in test env
    import os
    os.environ.pop("ANTHROPIC_API_KEY", None)
    r = run(pipe, "orders per status")
    assert r.status == "error" and "ANTHROPIC_API_KEY" in r.error


def test_every_request_is_logged(pipe, use_llm):
    use_llm(GOOD)
    run(pipe, "orders per status"); run(pipe, "drop table orders")
    logs = pipe.store.query_logs()
    assert logs["total"] == 2 and {l["status"] for l in logs["items"]} == {"success", "unsupported"}
    ok = pipe.store.query_logs(status="success")["items"][0]
    assert ok["final_sql"] and ok["row_count"] == 5 and ok["latency_ms"] > 0


# ───────────── API ─────────────
@pytest.fixture()
def client(pipe):
    with TestClient(create_app(pipe)) as c:
        yield c


def test_api_examples_crud_persists_and_reindexes(client):
    n0 = len(client.get("/admin/examples").json()["items"])
    r = client.post("/admin/examples", json={"question": "How many gizmos?", "sql": "SELECT 1", "query_type": "SELECT_SIMPLE"})
    assert r.status_code == 201
    ex_id = r.json()["id"]
    assert client.post("/admin/examples/search", json={"query": "gizmos", "k": 1}).json()["items"][0]["id"] == ex_id
    assert client.put(f"/admin/examples/{ex_id}", json={"question": "How many widgets?", "sql": "SELECT 2"}).json()["sql"] == "SELECT 2"
    assert len(client.get("/admin/examples", params={"query_type": "SELECT_SIMPLE"}).json()["items"]) >= 1
    assert client.delete(f"/admin/examples/{ex_id}").status_code == 200
    assert client.delete(f"/admin/examples/{ex_id}").status_code == 404
    assert len(client.get("/admin/examples").json()["items"]) == n0


def test_api_guardrail_toggle_changes_behaviour(client):
    assert client.post("/components/validate", json={"sql": "DELETE FROM orders"}).json()["valid"] is False
    client.put("/admin/guardrails", json={"allow_delete": True})
    assert client.get("/admin/guardrails").json()["settings"]["allow_delete"] is True
    assert client.post("/components/validate", json={"sql": "DELETE FROM orders"}).json()["valid"] is True
    # ...but the execute endpoint's connection is read-only, so nothing is deleted
    assert client.post("/components/execute", json={"sql": "DELETE FROM orders"}).json()["error"]
    assert client.post("/components/execute", json={"sql": "SELECT COUNT(*) FROM orders"}).json()["rows"] == [[5000]]
    assert client.put("/admin/guardrails", json={"max_rows": 0}).status_code == 422
    assert client.put("/admin/guardrails", json={"allow_delete": "yes"}).status_code == 422
    assert client.put("/admin/guardrails", json={"bogus": 1}).status_code == 422


def test_api_schema_metadata_roundtrip(client):
    t = {x["name"]: x for x in client.get("/admin/schema").json()["tables"]}
    assert len(t) == 9 and any(c["is_sensitive"] for c in t["customers"]["columns"])
    client.put("/admin/schema/orders/status", json={"description": "custom desc", "is_sensitive": True, "synonyms": ["state"]})
    col = next(c for c in {x["name"]: x for x in client.get("/admin/schema").json()["tables"]}["orders"]["columns"] if c["name"] == "status")
    assert col["description"] == "custom desc" and col["is_sensitive"] and col["synonyms"] == ["state"]
    assert client.post("/components/validate", json={"sql": "SELECT status FROM orders"}).json()["valid"] is False
    assert client.put("/admin/schema/orders/nope", json={"description": "x"}).status_code == 404


def test_api_config_and_logs(client):
    assert client.put("/admin/config", json={"temperature": 0.3, "dialect": "postgres"}).json()["settings"]["temperature"] == 0.3
    assert client.put("/admin/config", json={"provider": "nope"}).status_code == 422
    assert client.put("/admin/config", json={"temperature": 5}).status_code == 422
    client.put("/admin/config", json={"dialect": "sqlite"})
    client.post("/query", json={"question": "How many orders per status?"})
    client.post("/query", json={"question": "drop table orders"})
    logs = client.get("/admin/logs", params={"status": "unsupported"}).json()
    assert logs["total"] == 1
    csv_text = client.get("/admin/logs/export").text
    assert csv_text.splitlines()[0].startswith("id,ts,question") and "drop table orders" in csv_text
    assert client.get("/admin/logs/stats").json()["total"] == 2


def test_api_query_validation(client):
    assert client.post("/query", json={"question": ""}).status_code == 422
