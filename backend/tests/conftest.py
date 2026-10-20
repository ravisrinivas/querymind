import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.components.sql_generator as gen_mod  # noqa: E402
from app.pipeline import QueryMindPipeline  # noqa: E402
from app.store import AdminStore  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def test_set():
    return json.loads((ROOT / "eval" / "test_set.json").read_text())


@pytest.fixture(scope="session")
def examples_seed():
    return json.loads((ROOT / "data" / "examples_seed.json").read_text())


@pytest.fixture()
def pipe():
    return QueryMindPipeline(store=AdminStore(":memory:"))


class FakeLLM:
    """Scripted LLM: returns queued SQL strings in order (the last one repeats)."""
    name = "fake"

    def __init__(self, *sqls):
        self.sqls, self.calls, self.prompts = list(sqls), 0, []

    def complete(self, system, user, *, model, temperature, max_tokens):
        self.prompts.append(user)
        sql = self.sqls[min(self.calls, len(self.sqls) - 1)]
        self.calls += 1
        return json.dumps({"sql": sql, "explanation": "fake explanation"})


@pytest.fixture()
def use_llm(monkeypatch, pipe):
    """Route generation through a FakeLLM; returns a function to install it."""
    def install(*sqls):
        llm = FakeLLM(*sqls)
        monkeypatch.setattr(gen_mod, "get_provider", lambda cfg: llm)
        pipe.store.update_settings("model", {"provider": "anthropic"})
        return llm
    return install
