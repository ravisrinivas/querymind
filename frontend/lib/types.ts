export type QueryType = "SELECT_SIMPLE" | "SELECT_AGGREGATE" | "SELECT_JOIN" | "SELECT_TEMPORAL" | "UNSUPPORTED";
export const QUERY_TYPES: QueryType[] = ["SELECT_SIMPLE", "SELECT_AGGREGATE", "SELECT_JOIN", "SELECT_TEMPORAL"];

export interface Ambiguity { term: string; candidates: string[]; chosen: string | null; resolved_by: string }
export interface Example { id: number | null; question: string; sql: string; query_type: string | null; score?: number | null }
export interface Trace { stage: string; ms: number; detail: Record<string, unknown> }
export interface TableData { columns: string[]; rows: (string | number | null)[][] }

export interface QueryResponse {
  query_id: number | null;
  status: "success" | "error" | "blocked" | "unsupported" | "needs_clarification";
  question: string; query_type: QueryType | null;
  sql: string | null; generated_sql: string | null; sql_dialect_output: string | null;
  explanation: string | null; table: TableData | null; row_count: number;
  latency_ms: number; total_ms: number; nl_summary: string | null; error: string | null;
  ambiguities: Ambiguity[]; examples_used: Example[]; retried: boolean; self_healed: boolean;
  truncated: boolean; provider: string; model: string; trace: Trace[];
}

export interface Column {
  name: string; type: string; pk: boolean; fk: string | null; description: string;
  is_sensitive: boolean; synonyms: string[]; sample_values: string[];
}
export interface TableInfo { name: string; description: string; synonyms: string[]; row_count: number; columns: Column[] }

export interface LogRow {
  id: number; ts: string; question: string; query_type: string | null; generated_sql: string | null;
  final_sql: string | null; status: string; error: string | null; latency_ms: number | null;
  total_ms: number | null; row_count: number; provider: string | null; model: string | null;
  retried: number; self_healed: number;
}

export interface Guardrails {
  allow_insert: boolean; allow_update: boolean; allow_delete: boolean; allow_drop: boolean;
  allow_truncate: boolean; allow_alter: boolean; max_rows: number; default_limit: number;
  allowed_tables: string[]; allowed_table_prefixes: string[]; query_timeout_s: number;
}
export interface ModelConfig {
  provider: string; model: string; temperature: number; max_tokens: number; dialect: string;
  output_dialect: string; base_url: string; k_examples: number; self_heal: boolean;
  clarify_ambiguities: boolean; business_rules: string;
}
