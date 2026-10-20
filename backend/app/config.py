"""Static configuration + default runtime settings (runtime settings are editable via the Admin UI)."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "ecommerce.db"
ADMIN_DB_PATH = Path(os.getenv("QUERYMIND_ADMIN_DB", DATA_DIR / "admin.db"))
EXAMPLES_SEED_PATH = DATA_DIR / "examples_seed.json"
DEMO_SYNONYMS_PATH = DATA_DIR / "demo_metadata.json"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
ALLOW_WRITES = os.getenv("QUERYMIND_ALLOW_WRITES", "0") == "1"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

SUPPORTED_DIALECTS = {"sqlite": "SQLite", "postgres": "PostgreSQL", "mysql": "MySQL"}


def default_provider() -> str:
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "offline"


DEFAULT_BUSINESS_RULES = """\
- Today's date is 2025-12-31. "This year" = 2025, "last year" = 2024, "last quarter" = Q3 2025 (2025-07-01 to 2025-09-30), "last month" = November 2025.
- Dates are stored as 'YYYY-MM-DD' text. Filter with half-open ranges (>= start AND < next_start) and group with strftime().
- "Revenue" / "sales": always exclude orders with status = 'cancelled'.
  * Use SUM(orders.total_amount) for order-, customer-, country-, segment- or time-level revenue.
  * Use SUM(order_items.line_total) when grouping or filtering by product or category.
  * Use payments.amount only when the question is about payments, money collected or refunds (captured = collected).
- "Orders" means every row in orders unless a status is named. "Customers who ordered" excludes nobody by status.
- Alias tables with short names (o, c, oi, p) and always qualify columns in joins."""

DEFAULT_SETTINGS = {
    "guardrails": {
        "allow_insert": False, "allow_update": False, "allow_delete": False,
        "allow_drop": False, "allow_truncate": False, "allow_alter": False,
        "max_rows": 1000,
        "default_limit": 500,
        "allowed_tables": [],            # empty = all tables
        "allowed_table_prefixes": [],    # e.g. ["sales_"]; empty = no prefix restriction
        "query_timeout_s": 10,
    },
    "model": {
        "provider": default_provider(),  # anthropic | openai | ollama | offline
        "model": "claude-sonnet-4-20250514",
        "temperature": 0.0,
        "max_tokens": 1024,
        "dialect": "sqlite",
        "output_dialect": "",            # bonus: transpile displayed SQL (e.g. "postgres"); empty = off
        "base_url": "",                  # ollama / OpenAI-compatible endpoint override
        "k_examples": 4,
        "self_heal": True,               # retry once when execution fails
        "clarify_ambiguities": False,    # ask the user before generating SQL when columns are ambiguous
        "business_rules": DEFAULT_BUSINESS_RULES,
    },
}

PROVIDER_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "ollama": "llama3.1",
    "offline": "retrieval-baseline",
}
