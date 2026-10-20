"""Component 2 — Query Classifier.

Rule-based intent detection that runs BEFORE any LLM call, so destructive requests never reach the generator.
"""
from __future__ import annotations

import re

from ..schemas import ClassifierResult, LinkerResult, QueryType
from .schema_linker import SchemaLinker

_LEAD = r"^\s*(?:please\s+|can you\s+|could you\s+|would you\s+|i want to\s+|i need to\s+|go ahead and\s+)?"
_VERBS = r"(?:delete|drop|truncate|insert|update|alter|create|remove|erase|wipe|destroy|purge|grant|revoke|rename|replace|merge|attach|pragma)"
UNSUPPORTED_PATTERNS = [
    (re.compile(_LEAD + _VERBS + r"\b", re.I), "starts with a data-modifying command"),
    (re.compile(r";\s*" + _VERBS + r"\b", re.I), "contains a chained data-modifying statement"),
    (re.compile(r"\b(?:delete|drop|truncate|erase|wipe|purge|destroy)\s+(?:all|the|every|each|my|our|these|those|any|entire|whole|table|database|order|customer|review|product|record|row)", re.I), "asks to delete data"),
    (re.compile(r"\b(?:insert|add)\s+(?:a\s+|an\s+)?(?:new\s+)?(?:row|record|customer|order|product|entry)", re.I), "asks to insert data"),
    (re.compile(r"\b(?:update|change|modify|set|edit)\s+(?:the\s+|all\s+)?(?:\w+\s+){0,3}?(?:to|=)\s", re.I), "asks to change data"),
    (re.compile(r"\b(?:alter|create|rename)\s+(?:the\s+)?(?:table|column|index|view|database|schema)", re.I), "asks to change the schema"),
    (re.compile(r"\bremove\s+(?:all|every|the|these|those)\b", re.I), "asks to remove data"),
    (re.compile(r"\bignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+instructions", re.I), "looks like a prompt-injection attempt"),
]
_STRIP = re.compile(r"\b(?:last|first)\s+names?\b|\bmost recent\b|\blatest\b|\bnewest\b|\boldest\b", re.I)
_TEMPORAL = re.compile(r"\b(?:year|years|month|months|quarter|quarters|week|weeks|day|days|date|daily|weekly|monthly|yearly|annual|annually|yesterday|today|since|before|after|ago|between|during|past|ytd|q[1-4]|20\d\d|last|this)\b", re.I)
_AGGREGATE = re.compile(r"\b(?:how many|total|sum|average|avg|mean|count|number of|maximum|minimum|max|min|most|least|highest|lowest|best|worst|top|per|each|by|percent|percentage|ratio|median|revenue)\b", re.I)

HELP_TEXT = ("QueryMind is read-only: it answers questions about your data but cannot change it. "
             "Try rephrasing as a question, e.g. \"How many orders were cancelled in 2025?\"")


class QueryClassifier:
    def __init__(self, linker: SchemaLinker):
        self.linker = linker

    def classify(self, question: str, linker_result: LinkerResult | None = None) -> ClassifierResult:
        link = linker_result or self.linker.link(question)
        for pat, why in UNSUPPORTED_PATTERNS:
            if pat.search(question):
                return ClassifierResult(query_type=QueryType.UNSUPPORTED, tables_mentioned=link.resolved_tables,
                                        columns_mentioned=link.resolved_columns,
                                        reason=f"This request {why}. {HELP_TEXT}")
        cleaned = _STRIP.sub(" ", question)
        if _TEMPORAL.search(cleaned):
            qt = QueryType.SELECT_TEMPORAL
        elif _AGGREGATE.search(cleaned):
            qt = QueryType.SELECT_AGGREGATE
        elif len(link.resolved_tables) >= 2:
            qt = QueryType.SELECT_JOIN
        else:
            qt = QueryType.SELECT_SIMPLE
        return ClassifierResult(query_type=qt, tables_mentioned=link.resolved_tables,
                                columns_mentioned=link.resolved_columns)
