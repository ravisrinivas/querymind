"use client";
import { useEffect, useState } from "react";
import { api, put } from "@/lib/api";
import type { Guardrails } from "@/lib/types";
import { Banner, Toggle, useToast } from "@/components/ui";

const OPS: [keyof Guardrails, string, string][] = [
  ["allow_delete", "DELETE", "Remove rows"], ["allow_update", "UPDATE", "Change rows"], ["allow_insert", "INSERT", "Add rows"],
  ["allow_drop", "DROP", "Remove tables"], ["allow_truncate", "TRUNCATE", "Empty tables"], ["allow_alter", "ALTER", "Change table structure"],
];

export default function GuardrailsPage() {
  const [g, setG] = useState<Guardrails | null>(null);
  const [tables, setTables] = useState<string[]>([]);
  const [writes, setWrites] = useState(false);
  const [prefixes, setPrefixes] = useState("");
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  useEffect(() => {
    api<{ settings: Guardrails; tables: string[]; writes_executable: boolean }>("/admin/guardrails")
      .then((r) => { setG(r.settings); setTables(r.tables); setWrites(r.writes_executable); setPrefixes(r.settings.allowed_table_prefixes.join(", ")); })
      .catch((e) => setErr(e.message));
  }, []);

  async function save(next: Guardrails = g!) {
    setSaving(true);
    try {
      const body = { ...next, allowed_table_prefixes: prefixes.split(",").map((s) => s.trim()).filter(Boolean) };
      const r = await put<{ settings: Guardrails }>("/admin/guardrails", body);
      setG(r.settings); toast.show("Guardrails saved");
    } catch (e: any) { toast.show(e.message, "error"); } finally { setSaving(false); }
  }
  if (err) return <Banner kind="error">{err}</Banner>;
  if (!g) return <p className="muted">Loading…</p>;
  const anyOn = OPS.some(([k]) => g[k]);

  return (
    <>
      <h1>Guardrails</h1>
      <p className="muted">Controls what generated SQL is allowed to do. SELECT is always allowed; everything else is blocked unless you switch it on.</p>
      {anyOn && <Banner kind="warn">One or more write operations are allowed past the validator. {writes
        ? "The executor is configured to run writes (QUERYMIND_ALLOW_WRITES=1)." : "The database connection is still read-only, so these statements will fail at execution. Set QUERYMIND_ALLOW_WRITES=1 on the server to actually permit them."}</Banner>}

      <div className="card">
        <h2>SQL operations</h2>
        {OPS.map(([k, name, hint]) => (
          <Toggle key={k} checked={g[k] as boolean} label={`Allow ${name}`} hint={hint} onChange={(v) => { const n = { ...g, [k]: v }; setG(n); save(n); }} />))}
        <p className="small muted">Natural-language requests to modify data are rejected before reaching the model regardless of these toggles.</p>
      </div>

      <div className="card">
        <h2>Limits</h2>
        <div className="row">
          <label className="field grow">Maximum rows returned
            <span className="hint">Hard cap. Larger LIMITs are reduced to this.</span>
            <input type="number" min={1} max={100000} value={g.max_rows} onChange={(e) => setG({ ...g, max_rows: Number(e.target.value) })} /></label>
          <label className="field grow">Default LIMIT
            <span className="hint">Added when a query has no LIMIT (never above the maximum).</span>
            <input type="number" min={1} max={100000} value={g.default_limit} onChange={(e) => setG({ ...g, default_limit: Number(e.target.value) })} /></label>
          <label className="field grow">Query timeout (seconds)
            <span className="hint">Slow queries are cancelled.</span>
            <input type="number" min={1} max={120} value={g.query_timeout_s} onChange={(e) => setG({ ...g, query_timeout_s: Number(e.target.value) })} /></label>
        </div>
      </div>

      <div className="card">
        <h2>Query scope</h2>
        <p className="muted small">Leave everything unticked to allow all tables. Otherwise queries may only touch ticked tables or tables starting with a listed prefix.</p>
        <div className="row" style={{ alignItems: "flex-start" }}>
          {tables.map((t) => (
            <label key={t} className="check" style={{ minWidth: 150 }}>
              <input type="checkbox" checked={g.allowed_tables.includes(t)}
                onChange={(e) => setG({ ...g, allowed_tables: e.target.checked ? [...g.allowed_tables, t] : g.allowed_tables.filter((x) => x !== t) })} />{t}</label>))}
        </div>
        <label className="field">Allowed table prefixes<span className="hint">Comma-separated, for example sales_, dim_</span>
          <input type="text" value={prefixes} onChange={(e) => setPrefixes(e.target.value)} /></label>
      </div>
      <button className="primary" disabled={saving} onClick={() => save()}>Save guardrails</button>
      {toast.node}
    </>
  );
}
