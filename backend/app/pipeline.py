"""Pipeline orchestrator:
NL → Classifier → Schema Linker → Examples Retriever → SQL Generator → SQL Validator (+1 retry) → Executor
(+1 self-heal) → Result Formatter. Every request is logged for the Query Logs panel.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Optional

import sqlglot
from sqlalchemy.engine import Engine

from .components.examples_retriever import ExamplesRetriever
from .components.query_classifier import QueryClassifier
from .components.result_formatter import ResultFormatter
from .components.schema_linker import SchemaLinker
from .components.sql_executor import SQLExecutor
from .components.sql_generator import SQLGenerator
from .components.sql_validator import SQLValidator
from .config import EXAMPLES_SEED_PATH
from .db import make_engine
from .explain import describe_sql
from .llm.providers import ProviderError, effective_model
from .schema_manager import SchemaManager
from .schemas import (ClassifierResult, GeneratorRequest, GeneratorResult, QueryRequest, QueryResponse, QueryType,
                      StageTrace, ValidatorResult)
from .store import AdminStore


class QueryMindPipeline:
    def __init__(self, engine: Optional[Engine] = None, store: Optional[AdminStore] = None,
                 seed_examples: bool = True, use_chroma: bool = True):
        self.engine = engine or make_engine()
        self.store = store or AdminStore()
        if seed_examples and self.store.count_examples() == 0 and EXAMPLES_SEED_PATH.exists():
            for ex in json.loads(EXAMPLES_SEED_PATH.read_text()):
                self.store.add_example(ex["question"], ex["sql"], ex.get("query_type"))
        self.schema = SchemaManager(self.engine, self.store)
        self.linker = SchemaLinker(self.schema)
        self.classifier = QueryClassifier(self.linker)
        self.retriever = ExamplesRetriever(self.store, use_chroma=use_chroma)
        self.generator = SQLGenerator(self.schema)
        self.validator = SQLValidator(self.schema)
        self.executor = SQLExecutor(self.engine)
        self.formatter = ResultFormatter()

    # ───────────────────────── helpers ─────────────────────────
    @contextmanager
    def _stage(self, trace: list[StageTrace], name: str):
        t0 = time.perf_counter()
        detail: dict = {}
        try:
            yield detail
        finally:
            trace.append(StageTrace(stage=name, ms=round((time.perf_counter() - t0) * 1000, 1), detail=detail))

    def _finish(self, resp: QueryResponse, t_start: float, **log_extra) -> QueryResponse:
        resp.total_ms = round((time.perf_counter() - t_start) * 1000, 1)
        resp.query_id = self.store.add_log(
            question=resp.question, query_type=resp.query_type.value if resp.query_type else None,
            generated_sql=resp.generated_sql, final_sql=resp.sql, status=resp.status, error=resp.error,
            latency_ms=resp.latency_ms, total_ms=resp.total_ms, row_count=resp.row_count, provider=resp.provider,
            model=resp.model, retried=resp.retried, self_healed=resp.self_healed)
        return resp

    def _generate_and_validate(self, base: GeneratorRequest, cfg: dict, guard: dict, trace: list[StageTrace]):
        dialect = cfg["dialect"]
        with self._stage(trace, "generate") as d:
            gen = self.generator.generate(base, cfg)
            d.update(provider=gen.provider, model=gen.model, llm_ms=gen.latency_ms)
        with self._stage(trace, "validate") as d:
            val = self.validator.validate(gen.sql, guard, dialect)
            d.update(valid=val.valid, errors=[e.model_dump() for e in val.errors], warnings=val.warnings)
        retried = False
        if not val.valid:
            retried = True
            retry_req = base.model_copy(update={"previous_sql": gen.sql, "error_feedback": val.error_text})
            with self._stage(trace, "generate_retry") as d:
                gen = self.generator.generate(retry_req, cfg)
                d.update(feedback=val.error_text)
            with self._stage(trace, "validate_retry") as d:
                val = self.validator.validate(gen.sql, guard, dialect)
                d.update(valid=val.valid, errors=[e.model_dump() for e in val.errors])
        return gen, val, retried

    # ───────────────────────── main entry ─────────────────────────
    def run(self, req: QueryRequest) -> QueryResponse:
        t_start = time.perf_counter()
        trace: list[StageTrace] = []
        cfg, guard = self.store.get_settings("model"), self.store.get_settings("guardrails")
        resp = QueryResponse(status="error", question=req.question, provider=cfg["provider"],
                             model=effective_model(cfg))
        trace = resp.trace          # pydantic copies lists on init, so append to the response's own list
        try:
            # 1-2. link + classify (classifier runs first so destructive intents never reach the LLM)
            with self._stage(trace, "schema_link") as d:
                link = self.linker.link(req.question, req.clarifications)
                d.update(tables=link.resolved_tables, columns=link.resolved_columns,
                         ambiguities=[a.model_dump() for a in link.ambiguities])
            with self._stage(trace, "classify") as d:
                cls: ClassifierResult = self.classifier.classify(req.question, link)
                d.update(query_type=cls.query_type.value)
            resp.query_type, resp.ambiguities = cls.query_type, link.ambiguities
            if cls.query_type == QueryType.UNSUPPORTED:
                resp.status, resp.error = "unsupported", cls.reason
                return self._finish(resp, t_start)

            ask = cfg["clarify_ambiguities"] if req.clarify is None else req.clarify
            pending = [a for a in link.ambiguities if a.resolved_by in ("default", "none")]
            if ask and pending:
                resp.status = "needs_clarification"
                return self._finish(resp, t_start)

            # 3. examples
            with self._stage(trace, "retrieve_examples") as d:
                ex = self.retriever.retrieve(req.question, k=int(cfg["k_examples"]))
                resp.examples_used = ex.examples
                d.update(backend=self.retriever.backend, ids=[e.id for e in ex.examples])

            # 4-5. generate + validate (one retry on validation failure)
            base = GeneratorRequest(question=req.question, classifier=cls, linker=link, examples=ex.examples)
            gen, val, retried = self._generate_and_validate(base, cfg, guard, trace)
            resp.generated_sql, resp.explanation, resp.retried = gen.sql, gen.explanation, retried
            resp.provider, resp.model = gen.provider, gen.model
            if not val.valid:
                resp.status = "blocked" if val.is_guardrail_block else "error"
                resp.error = val.error_text
                return self._finish(resp, t_start)

            # 6. execute (self-heal once on database errors)
            sql = val.sanitized_sql
            with self._stage(trace, "execute") as d:
                exe = self.executor.execute(sql, int(guard["max_rows"]), float(guard["query_timeout_s"]))
                d.update(row_count=exe.row_count, latency_ms=exe.latency_ms, error=exe.error)
            if exe.error and cfg["self_heal"]:
                heal_req = base.model_copy(update={"previous_sql": sql, "error_feedback": f"Execution error: {exe.error}"})
                with self._stage(trace, "self_heal") as d:
                    gen2 = self.generator.generate(heal_req, cfg)
                    val2: ValidatorResult = self.validator.validate(gen2.sql, guard, cfg["dialect"])
                    d.update(valid=val2.valid)
                    if val2.valid:
                        exe2 = self.executor.execute(val2.sanitized_sql, int(guard["max_rows"]), float(guard["query_timeout_s"]))
                        if not exe2.error:
                            sql, exe, resp.self_healed = val2.sanitized_sql, exe2, True
                            resp.generated_sql, resp.explanation = gen2.sql, gen2.explanation
                            resp.retried = True
            resp.sql, resp.latency_ms = sql, exe.latency_ms
            if exe.error:
                resp.status, resp.error = "error", f"Database error: {exe.error}"
                return self._finish(resp, t_start)

            # 7. format
            with self._stage(trace, "format") as d:
                out = self.formatter.format(req.question, exe, cfg)
                d.update(rows=exe.row_count)
            resp.status, resp.table, resp.nl_summary = "success", out.table, out.nl_summary
            resp.row_count, resp.truncated = exe.row_count, exe.truncated
            breakdown = describe_sql(sql, cfg["dialect"])
            resp.explanation = resp.explanation or breakdown
            if req.explain and breakdown and resp.explanation != breakdown:
                resp.explanation = f"{resp.explanation}  Breakdown: {breakdown}"
            out_dialect = cfg.get("output_dialect") or ""
            if out_dialect and out_dialect != cfg["dialect"]:
                try:
                    resp.sql_dialect_output = sqlglot.transpile(sql, read=cfg["dialect"], write=out_dialect)[0]
                except Exception as e:  # noqa: BLE001
                    resp.sql_dialect_output = f"-- transpile to {out_dialect} failed: {e}"
            return self._finish(resp, t_start)

        except ProviderError as e:
            resp.status, resp.error = "error", f"LLM provider error: {e}"
            return self._finish(resp, t_start)
        except Exception as e:  # noqa: BLE001 - never leak a 500 for a user question
            resp.status, resp.error = "error", f"Unexpected error: {type(e).__name__}: {e}"
            return self._finish(resp, t_start)
