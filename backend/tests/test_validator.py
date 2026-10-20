import json
from pathlib import Path

import pytest

from app.config import DEFAULT_SETTINGS

G = DEFAULT_SETTINGS["guardrails"]
ATTEMPTS = json.loads((Path(__file__).parent.parent / "eval" / "test_set.json").read_text())["guardrail_sql_attempts"]


@pytest.mark.parametrize("sql", ATTEMPTS)
def test_every_destructive_or_unsafe_sql_is_rejected(pipe, sql):
    r = pipe.validator.validate(sql, G)
    assert not r.valid and r.errors


@pytest.mark.parametrize("op,sql", [
    ("delete", "DELETE FROM orders WHERE order_id = 1"),
    ("update", "UPDATE products SET unit_price = 1 WHERE product_id = 1"),
    ("insert", "INSERT INTO categories (name) VALUES ('x')"),
    ("drop", "DROP TABLE reviews"),
    ("truncate", "TRUNCATE TABLE reviews"),
    ("alter", "ALTER TABLE orders ADD COLUMN x INT"),
])
def test_admin_toggle_allows_only_that_operation(pipe, op, sql):
    assert not pipe.validator.validate(sql, G).valid
    assert pipe.validator.validate(sql, {**G, f"allow_{op}": True}).valid
    other = "allow_drop" if op != "drop" else "allow_delete"
    assert not pipe.validator.validate(sql, {**G, other: True}).valid


def test_literals_containing_keywords_are_fine(pipe):
    r = pipe.validator.validate("SELECT comment FROM reviews WHERE comment LIKE '%delete%'", G)
    assert r.valid, r.errors


def test_limit_appended_and_clamped(pipe):
    assert pipe.validator.validate("SELECT name FROM products", {**G, "default_limit": 25}).sanitized_sql.endswith("LIMIT 25")
    r = pipe.validator.validate("SELECT name FROM products LIMIT 99999", {**G, "max_rows": 100})
    assert r.sanitized_sql.endswith("LIMIT 100") and any("reduced" in w for w in r.warnings)
    assert pipe.validator.validate("SELECT name FROM products LIMIT 5", G).sanitized_sql.endswith("LIMIT 5")


def test_unknown_table_and_column(pipe):
    t = pipe.validator.validate("SELECT * FROM ghosts", G)
    assert t.errors[0].code == "UNKNOWN_TABLE" and "Available tables" in t.errors[0].message
    c = pipe.validator.validate("SELECT o.nonexistent FROM orders o", G)
    assert c.errors[0].code == "UNKNOWN_COLUMN" and "total_amount" in c.errors[0].message


def test_sensitive_column_blocked_including_star_and_alias(pipe):
    for sql in ["SELECT email FROM customers", "SELECT * FROM customers", "SELECT c.email FROM customers AS c",
                "SELECT x.email FROM (SELECT email FROM customers) x"]:
        r = pipe.validator.validate(sql, G)
        assert not r.valid and r.errors[0].code == "SENSITIVE_COLUMN", sql
    assert pipe.validator.validate("SELECT customer_id, first_name FROM customers", G).valid


def test_scope_allow_list_and_prefix(pipe):
    g = {**G, "allowed_tables": ["orders", "customers"]}
    assert pipe.validator.validate("SELECT order_id FROM orders", g).valid
    r = pipe.validator.validate("SELECT product_id FROM products", g)
    assert r.errors[0].code == "SCOPE"
    assert not pipe.validator.validate("SELECT 1 FROM main.orders JOIN other.x ON 1=1", G).valid
    assert pipe.validator.validate("SELECT order_id FROM orders", {**G, "allowed_table_prefixes": ["order"]}).valid


def test_ctes_and_unions_pass(pipe):
    sql = "WITH t AS (SELECT customer_id, SUM(total_amount) AS s FROM orders GROUP BY customer_id) SELECT * FROM t ORDER BY s DESC"
    assert pipe.validator.validate(sql, G).valid
    assert pipe.validator.validate("SELECT country FROM customers UNION SELECT country FROM suppliers", G).valid


def test_syntax_error(pipe):
    r = pipe.validator.validate("SELEC name FROM", G)
    assert not r.valid


def test_all_library_and_ground_truth_sql_validate_and_roundtrip(pipe, examples_seed, test_set):
    """Sanitised (regenerated) SQL must return the same rows as the original — validator must never change meaning."""
    from sqlalchemy import text
    def rows(sql):
        with pipe.engine.connect() as c:
            return sorted(map(repr, c.execute(text(sql)).fetchall()))
    for item in examples_seed + test_set["tests"]:
        r = pipe.validator.validate(item["sql"], {**G, "max_rows": 100000, "default_limit": 100000})
        assert r.valid, (item["question"], r.errors)
        assert rows(r.sanitized_sql) == rows(item["sql"]), item["question"]
