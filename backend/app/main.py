"""QueryMind AI — FastAPI application.  Run:  uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS
from .pipeline import QueryMindPipeline
from .routers import admin, query


def create_app(pipeline: Optional[QueryMindPipeline] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pipeline = pipeline or QueryMindPipeline()
        yield

    app = FastAPI(title="QueryMind AI", version="1.0.0",
                  description="Text-to-SQL analytics engine with an admin API.", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
    app.include_router(query.router)
    app.include_router(admin.router)

    @app.get("/health")
    def health():
        p = app.state.pipeline
        return {"status": "ok", "tables": len(p.schema.tables), "examples": p.store.count_examples(),
                "retriever": p.retriever.backend, "provider": p.store.get_settings("model")["provider"]}

    return app


app = create_app()
