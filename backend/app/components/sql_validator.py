"""Component 6 — SQL Validator.

Defence in depth, evaluated on the parsed AST (not just string matching):
  1. syntax        — sqlglot parse in the configured dialect; exactly one statement
  2. guardrails    — DROP/DELETE/UPDATE/INSERT/TRUNCATE/ALTER (+ any non-SELECT root) blocked unless the admin
                     toggled that operation on
  3. schema        — every table and column must exist (sqlglot qualify); sensitive columns are rejected
  4. scope         — optional table allow-list / prefix restriction
  5. row limit     — LIMIT appended when absent, clamped to max_rows when larger
The returned `sanitized_sql` is regenerated from the validated AST (comments stripped), so what is executed is
exactly what was checked.
"""
from __future__ import annotations

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, SqlglotError, TokenError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope
from sqlglot.schema import MappingSchema

from ..schema_manager import SchemaManager
from ..schemas import ValidationIssue, ValidatorResult

OP_NODES: dict[type, str] = {
    exp.Drop: "DROP", exp.Delete: "DELETE", exp.Update: "UPDATE", exp.Insert: "INSERT",
    exp.Alter: "ALTER", exp.TruncateTable: "TRUNCATE",
}
_KEYWORD_OPS = {"drop": "DROP", "delete": "DELETE", "update": "UPDATE", "insert": "INSERT", "truncate": "TRUNCATE",
                "alter": "ALTER", "replace": "INSERT", "merge": "UPDATE"}
_RAW_OP_RE = re.compile(r"\b(drop|delete|update|insert|truncate|alter)\b", re.I)
_LITERAL_RE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|`[^`]*`")


class SQLValidator:
    def __init__(self, schema: SchemaManager):
        self.schema = schema

    def validate(self, sql: str, guardrails: dict, dialect: str = "sqlite") -> ValidatorResult:
        errors: list[ValidationIssue] = []
        warnings: list[str] = []
        sql = (sql or "").strip().rstrip(";").strip()
        if not sql:
            return ValidatorResult(valid=False, errors=[ValidationIssue(code="EMPTY", message="No SQL was generated.")])

        # ── 1. syntax ──
        try:
            stmts = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
        except (ParseError, TokenError, SqlglotError) as e:
            stmts, errors = [], [ValidationIssue(code="SYNTAX", message=f"SQL could not be parsed: {str(e)[:200]}")]

        # ── 2. guardrails (checked on raw text too, so even unparseable input cannot slip a write through) ──
        def allowed(op: str) -> bool:
            return bool(guardrails.get(f"allow_{op.lower()}", False))

        found_ops: set[str] = set(m.group(1).upper() for m in _RAW_OP_RE.finditer(_LITERAL_RE.sub("''", sql)))
        for s in stmts:
            for node in s.find_all(*OP_NODES):
                found_ops.add(OP_NODES[type(node)])
        for op in sorted(found_ops):
            if not allowed(op):
                errors.append(ValidationIssue(
                    code="GUARDRAIL", message=f"{op} statements are blocked by the Guardrails configuration."))
        if len(stmts) > 1:
            errors.append(ValidationIssue(code="MULTI_STATEMENT", message="Only a single SQL statement is allowed."))
        if errors or not stmts:
            return ValidatorResult(valid=False, errors=errors)

        stmt = stmts[0]
        is_query = isinstance(stmt, exp.Query)
        if not is_query:
            root_op = OP_NODES.get(type(stmt))
            if root_op is None and isinstance(stmt, exp.Command):
                root_op = _KEYWORD_OPS.get(str(stmt.this).strip().lower())
            if root_op and allowed(root_op):
                warnings.append(f"{root_op} permitted by guardrail toggle. The executor connection is still "
                                "read-only unless QUERYMIND_ALLOW_WRITES=1.")
                return ValidatorResult(valid=True, sanitized_sql=stmt.sql(dialect=dialect), warnings=warnings)
            kind = type(stmt).__name__.upper()
            return ValidatorResult(valid=False, errors=[ValidationIssue(
                code="NOT_SELECT", message=f"Only SELECT queries are permitted (got {root_op or kind}).")])

        # ── 3. schema check ──
        schema_dict = self.schema.schema_dict()
        cte_names = {c.alias_or_name.lower() for c in stmt.find_all(exp.CTE)}
        real_tables: set[str] = set()
        for t in stmt.find_all(exp.Table):
            name = t.name.lower()
            if not name or name in cte_names:
                continue
            if t.db and t.db.lower() not in ("main", "public"):
                errors.append(ValidationIssue(code="SCOPE", message=f"Cross-schema access ({t.db}.{t.name}) is not allowed."))
                continue
            if name not in schema_dict:
                errors.append(ValidationIssue(
                    code="UNKNOWN_TABLE",
                    message=f"Table '{t.name}' does not exist. Available tables: {', '.join(sorted(schema_dict))}."))
            else:
                real_tables.add(name)

        # ── 4. scope restriction ──
        allow_tables = {x.lower() for x in guardrails.get("allowed_tables", [])}
        prefixes = tuple(x.lower() for x in guardrails.get("allowed_table_prefixes", []))
        if allow_tables or prefixes:
            for name in sorted(real_tables):
                if name not in allow_tables and not (prefixes and name.startswith(prefixes)):
                    errors.append(ValidationIssue(code="SCOPE", message=f"Table '{name}' is outside the allowed query scope."))
        if errors:
            return ValidatorResult(valid=False, errors=errors)

        try:
            q = qualify(stmt.copy(), schema=MappingSchema(schema_dict, dialect=dialect), dialect=dialect,
                        validate_qualify_columns=True, expand_stars=True, identify=False)
        except SqlglotError as e:
            cols = "; ".join(f"{t}({', '.join(schema_dict[t])})" for t in sorted(real_tables))
            return ValidatorResult(valid=False, errors=[ValidationIssue(
                code="UNKNOWN_COLUMN", message=f"{str(e)[:160]}. Columns available: {cols}")])

        sensitive = self.schema.sensitive_columns()
        if sensitive:
            hit = set()
            for scope in traverse_scope(q):
                for col in scope.columns:
                    src = scope.sources.get(col.table)
                    if isinstance(src, exp.Table) and (src.name.lower(), col.name.lower()) in sensitive:
                        hit.add(f"{src.name}.{col.name}")
            if hit:
                errors.append(ValidationIssue(
                    code="SENSITIVE_COLUMN",
                    message=f"Query touches restricted column(s): {', '.join(sorted(hit))}. "
                            "Select explicit non-sensitive columns instead of SELECT *."))
                return ValidatorResult(valid=False, errors=errors)

        # ── 5. row limit ──
        max_rows = int(guardrails.get("max_rows", 1000))
        default_limit = min(int(guardrails.get("default_limit", max_rows)), max_rows)
        limit = stmt.args.get("limit")
        if limit is None:
            stmt = stmt.limit(default_limit)
            warnings.append(f"LIMIT {default_limit} appended.")
        else:
            expr = limit.args.get("expression")
            if isinstance(expr, exp.Literal) and expr.is_int and int(expr.name) > max_rows:
                stmt.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
                warnings.append(f"LIMIT reduced from {expr.name} to the configured maximum of {max_rows}.")

        return ValidatorResult(valid=True, sanitized_sql=stmt.sql(dialect=dialect), warnings=warnings)
