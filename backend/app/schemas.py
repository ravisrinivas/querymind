"""Typed contracts between pipeline components and the REST API.

Every component takes and returns one of these models, so each can be called and tested in isolation.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ───────────────────────── Query classifier ─────────────────────────
class QueryType(str, Enum):
    SELECT_SIMPLE = "SELECT_SIMPLE"
    SELECT_AGGREGATE = "SELECT_AGGREGATE"
    SELECT_JOIN = "SELECT_JOIN"
    SELECT_TEMPORAL = "SELECT_TEMPORAL"
    UNSUPPORTED = "UNSUPPORTED"


class ClassifierResult(BaseModel):
    query_type: QueryType
    tables_mentioned: list[str] = []
    columns_mentioned: list[str] = []          # "table.column"
    reason: str = ""                            # human-readable; used as the error for UNSUPPORTED


# ───────────────────────── Schema linker ─────────────────────────
class Ambiguity(BaseModel):
    term: str
    candidates: list[str]                       # "table.column"
    chosen: Optional[str] = None                # default pick, if any
    resolved_by: Literal["context", "default", "user", "none"] = "none"


class LinkerResult(BaseModel):
    resolved_tables: list[str] = []
    resolved_columns: list[str] = []            # "table.column"
    ambiguities: list[Ambiguity] = []


# ───────────────────────── Examples retriever ─────────────────────────
class Example(BaseModel):
    id: Optional[int] = None
    question: str
    sql: str
    query_type: Optional[str] = None
    score: Optional[float] = None


class RetrieverResult(BaseModel):
    examples: list[Example] = []


# ───────────────────────── SQL generator ─────────────────────────
class GeneratorRequest(BaseModel):
    question: str
    classifier: ClassifierResult
    linker: LinkerResult
    examples: list[Example] = []
    previous_sql: Optional[str] = None          # set on retry
    error_feedback: Optional[str] = None        # validator or execution error to fix


class GeneratorResult(BaseModel):
    sql: str
    explanation: str = ""
    raw_response: str = ""
    provider: str = ""
    model: str = ""
    latency_ms: float = 0.0


# ───────────────────────── SQL validator ─────────────────────────
class ValidationIssue(BaseModel):
    code: Literal["EMPTY", "SYNTAX", "MULTI_STATEMENT", "GUARDRAIL", "UNKNOWN_TABLE", "UNKNOWN_COLUMN",
                  "SENSITIVE_COLUMN", "SCOPE", "NOT_SELECT"]
    message: str


class ValidatorResult(BaseModel):
    valid: bool
    sanitized_sql: str = ""
    errors: list[ValidationIssue] = []
    warnings: list[str] = []

    @property
    def error_text(self) -> str:
        return "; ".join(f"[{e.code}] {e.message}" for e in self.errors)

    @property
    def is_guardrail_block(self) -> bool:
        return any(e.code in ("GUARDRAIL", "NOT_SELECT", "SENSITIVE_COLUMN", "SCOPE") for e in self.errors)


# ───────────────────────── SQL executor ─────────────────────────
class ExecutionResult(BaseModel):
    rows: list[list[Any]] = []
    columns: list[str] = []
    row_count: int = 0
    latency_ms: float = 0.0
    truncated: bool = False
    error: Optional[str] = None


# ───────────────────────── Result formatter ─────────────────────────
class TableData(BaseModel):
    columns: list[str] = []
    rows: list[list[Any]] = []


class FormatterResult(BaseModel):
    table: TableData
    nl_summary: str = ""


# ───────────────────────── Orchestrated /query ─────────────────────────
class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    clarifications: dict[str, str] = Field(default_factory=dict, description="term -> 'table.column' picks")
    clarify: Optional[bool] = Field(default=None, description="override the Model Config clarify setting")
    explain: bool = False                        # include a plain-English breakdown of the SQL
    session_id: Optional[str] = None


QueryStatus = Literal["success", "error", "blocked", "unsupported", "needs_clarification"]


class StageTrace(BaseModel):
    stage: str
    ms: float
    detail: dict[str, Any] = {}


class QueryResponse(BaseModel):
    query_id: Optional[int] = None
    status: QueryStatus
    question: str
    query_type: Optional[QueryType] = None
    sql: Optional[str] = None
    generated_sql: Optional[str] = None          # before validation/sanitising
    sql_dialect_output: Optional[str] = None     # bonus: transpiled SQL
    explanation: Optional[str] = None
    table: Optional[TableData] = None
    row_count: int = 0
    latency_ms: float = 0.0                      # execution latency
    total_ms: float = 0.0                        # end-to-end
    nl_summary: Optional[str] = None
    error: Optional[str] = None
    ambiguities: list[Ambiguity] = []
    examples_used: list[Example] = []
    retried: bool = False
    self_healed: bool = False
    truncated: bool = False
    provider: str = ""
    model: str = ""
    trace: list[StageTrace] = []


# ───────────────────────── Admin payloads ─────────────────────────
class ColumnUpdate(BaseModel):
    description: Optional[str] = None
    is_sensitive: Optional[bool] = None
    synonyms: Optional[list[str]] = None


class TableUpdate(BaseModel):
    description: Optional[str] = None
    synonyms: Optional[list[str]] = None


class ExampleIn(BaseModel):
    question: str = Field(min_length=3)
    sql: str = Field(min_length=6)
    query_type: Optional[QueryType] = None


class ExampleSearch(BaseModel):
    query: str
    k: int = 5
