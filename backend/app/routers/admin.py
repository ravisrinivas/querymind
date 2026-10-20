"""Admin API: schema, examples, logs, guardrails, model config."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response

from ..config import DEFAULT_SETTINGS, PROVIDER_DEFAULT_MODELS, SUPPORTED_DIALECTS
from ..schemas import ColumnUpdate, ExampleIn, ExampleSearch, TableUpdate

router = APIRouter(prefix="/admin", tags=["admin"])


def pipe(request: Request):
    return request.app.state.pipeline


# ───────────── Schema Manager ─────────────
@router.get("/schema")
def get_schema(request: Request):
    return {"tables": pipe(request).schema.get_schema()}


@router.post("/schema/refresh")
def refresh_schema(request: Request):
    pipe(request).schema.refresh()
    return {"ok": True}


@router.put("/schema/{table}")
def update_table(table: str, body: TableUpdate, request: Request):
    try:
        pipe(request).schema.update_table(table, description=body.description, synonyms=body.synonyms)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.put("/schema/{table}/{column}")
def update_column(table: str, column: str, body: ColumnUpdate, request: Request):
    try:
        pipe(request).schema.update_column(table, column, description=body.description,
                                           is_sensitive=body.is_sensitive, synonyms=body.synonyms)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


# ───────────── Examples Manager ─────────────
@router.get("/examples")
def list_examples(request: Request, query_type: Optional[str] = None):
    return {"items": pipe(request).store.list_examples(query_type)}


@router.post("/examples", status_code=201)
def add_example(body: ExampleIn, request: Request):
    p = pipe(request)
    new_id = p.store.add_example(body.question, body.sql, body.query_type.value if body.query_type else None)
    p.retriever.reindex()
    return p.store.get_example(new_id)


@router.put("/examples/{example_id}")
def update_example(example_id: int, body: ExampleIn, request: Request):
    p = pipe(request)
    if not p.store.update_example(example_id, body.question, body.sql, body.query_type.value if body.query_type else None):
        raise HTTPException(404, "Example not found")
    p.retriever.reindex()
    return p.store.get_example(example_id)


@router.delete("/examples/{example_id}")
def delete_example(example_id: int, request: Request):
    p = pipe(request)
    if not p.store.delete_example(example_id):
        raise HTTPException(404, "Example not found")
    p.retriever.reindex()
    return {"ok": True}


@router.post("/examples/search")
def search_examples(body: ExampleSearch, request: Request):
    return {"items": [e.model_dump() for e in pipe(request).retriever.search(body.query, body.k)]}


# ───────────── Query Logs ─────────────
@router.get("/logs")
def get_logs(request: Request, status: Optional[str] = None, search: Optional[str] = None,
             query_type: Optional[str] = None, limit: int = Query(100, le=1000), offset: int = 0):
    return pipe(request).store.query_logs(status=status, search=search, query_type=query_type, limit=limit, offset=offset)


@router.get("/logs/stats")
def log_stats(request: Request):
    return pipe(request).store.log_stats()


@router.get("/logs/export")
def export_logs(request: Request, status: Optional[str] = None, search: Optional[str] = None,
                query_type: Optional[str] = None):
    csv_text = pipe(request).store.logs_csv(status=status, search=search, query_type=query_type)
    return Response(csv_text, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="querymind_logs.csv"'})


# ───────────── Guardrails ─────────────
def _validate_guardrails(v: dict) -> None:
    if "max_rows" in v and not (1 <= int(v["max_rows"]) <= 100000):
        raise HTTPException(422, "max_rows must be between 1 and 100000")
    if "default_limit" in v and not (1 <= int(v["default_limit"]) <= 100000):
        raise HTTPException(422, "default_limit must be between 1 and 100000")
    if "query_timeout_s" in v and not (1 <= float(v["query_timeout_s"]) <= 120):
        raise HTTPException(422, "query_timeout_s must be between 1 and 120")
    for k in ("allowed_tables", "allowed_table_prefixes"):
        if k in v and not (isinstance(v[k], list) and all(isinstance(x, str) for x in v[k])):
            raise HTTPException(422, f"{k} must be a list of strings")
    for k, val in v.items():
        if k.startswith("allow_") and not isinstance(val, bool):
            raise HTTPException(422, f"{k} must be true or false")


@router.get("/guardrails")
def get_guardrails(request: Request):
    return {"settings": pipe(request).store.get_settings("guardrails"),
            "writes_executable": os.getenv("QUERYMIND_ALLOW_WRITES", "0") == "1",
            "tables": pipe(request).schema.tables}


@router.put("/guardrails")
def put_guardrails(body: dict, request: Request):
    _validate_guardrails(body)
    try:
        return {"settings": pipe(request).store.update_settings("guardrails", body)}
    except ValueError as e:
        raise HTTPException(422, str(e))


# ───────────── Model config ─────────────
@router.get("/config")
def get_config(request: Request):
    return {
        "settings": pipe(request).store.get_settings("model"),
        "options": {
            "providers": list(PROVIDER_DEFAULT_MODELS),
            "default_models": PROVIDER_DEFAULT_MODELS,
            "dialects": SUPPORTED_DIALECTS,
            "provider_ready": {
                "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
                "openai": bool(os.getenv("OPENAI_API_KEY")),
                "ollama": True, "offline": True,
            },
            "embedding_backend": pipe(request).retriever.backend,
        },
    }


@router.put("/config")
def put_config(body: dict, request: Request):
    if "provider" in body and body["provider"] not in PROVIDER_DEFAULT_MODELS:
        raise HTTPException(422, f"provider must be one of {list(PROVIDER_DEFAULT_MODELS)}")
    if "dialect" in body and body["dialect"] not in SUPPORTED_DIALECTS:
        raise HTTPException(422, f"dialect must be one of {list(SUPPORTED_DIALECTS)}")
    if body.get("output_dialect") and body["output_dialect"] not in SUPPORTED_DIALECTS:
        raise HTTPException(422, f"output_dialect must be one of {list(SUPPORTED_DIALECTS)}")
    if "temperature" in body and not (0 <= float(body["temperature"]) <= 2):
        raise HTTPException(422, "temperature must be between 0 and 2")
    if "max_tokens" in body and not (64 <= int(body["max_tokens"]) <= 8192):
        raise HTTPException(422, "max_tokens must be between 64 and 8192")
    if "k_examples" in body and not (1 <= int(body["k_examples"]) <= 10):
        raise HTTPException(422, "k_examples must be between 1 and 10")
    try:
        return {"settings": pipe(request).store.update_settings("model", body)}
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/config/reset")
def reset_config(request: Request):
    return {"settings": pipe(request).store.update_settings("model", DEFAULT_SETTINGS["model"])}
