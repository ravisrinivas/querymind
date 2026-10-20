"""Public query endpoint + per-component endpoints (each pipeline stage is independently callable)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..schemas import (ClassifierResult, ExecutionResult, GeneratorRequest, GeneratorResult, LinkerResult,
                       QueryRequest, QueryResponse, RetrieverResult, ValidatorResult)

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, request: Request):
    return request.app.state.pipeline.run(body)


class Q(BaseModel):
    question: str
    k: int = 4


class SQLIn(BaseModel):
    sql: str


@router.post("/components/link", response_model=LinkerResult)
def c_link(body: Q, request: Request):
    return request.app.state.pipeline.linker.link(body.question)


@router.post("/components/classify", response_model=ClassifierResult)
def c_classify(body: Q, request: Request):
    return request.app.state.pipeline.classifier.classify(body.question)


@router.post("/components/retrieve", response_model=RetrieverResult)
def c_retrieve(body: Q, request: Request):
    return request.app.state.pipeline.retriever.retrieve(body.question, k=body.k)


@router.post("/components/generate", response_model=GeneratorResult)
def c_generate(body: GeneratorRequest, request: Request):
    p = request.app.state.pipeline
    return p.generator.generate(body, p.store.get_settings("model"))


@router.post("/components/validate", response_model=ValidatorResult)
def c_validate(body: SQLIn, request: Request):
    p = request.app.state.pipeline
    return p.validator.validate(body.sql, p.store.get_settings("guardrails"), p.store.get_settings("model")["dialect"])


@router.post("/components/execute", response_model=ExecutionResult)
def c_execute(body: SQLIn, request: Request):
    """Validates first — this endpoint can never be used to bypass the guardrails."""
    p = request.app.state.pipeline
    g = p.store.get_settings("guardrails")
    v = p.validator.validate(body.sql, g, p.store.get_settings("model")["dialect"])
    if not v.valid:
        return ExecutionResult(error=v.error_text)
    return p.executor.execute(v.sanitized_sql, int(g["max_rows"]), float(g["query_timeout_s"]))
