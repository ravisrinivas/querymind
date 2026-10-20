"use client";
import { useCallback, useEffect, useState } from "react";
import { api, put, post } from "@/lib/api";
import type { Column, TableInfo } from "@/lib/types";
import { Banner, useToast } from "@/components/ui";

export default function SchemaManager() {
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [sel, setSel] = useState<string>("");
  const [err, setErr] = useState("");
  const toast = useToast();

  const load = useCallback(async () => {
    try {
      const r = await api<{ tables: TableInfo[] }>("/admin/schema");
      setTables(r.tables); setSel((s) => s || r.tables[0]?.name || ""); setErr("");
    } catch (e: any) { setErr(e.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const table = tables.find((t) => t.name === sel);

  async function saveCol(c: Column, patch: Partial<Pick<Column, "description" | "is_sensitive" | "synonyms">>) {
    try { await put(`/admin/schema/${sel}/${c.name}`, patch); toast.show(`Saved ${sel}.${c.name}`); await load(); }
    catch (e: any) { toast.show(e.message, "error"); }
  }
  async function saveTable(patch: { description?: string; synonyms?: string[] }) {
    try { await put(`/admin/schema/${sel}`, patch); toast.show(`Saved ${sel}`); await load(); }
    catch (e: any) { toast.show(e.message, "error"); }
  }

  return (
    <>
      <h1>Schema manager</h1>
      <p className="muted">Describe columns in business language, add synonyms, and mark columns as sensitive. Sensitive columns are removed from the model’s context and rejected if a query touches them.</p>
      {err && <Banner kind="error">{err}</Banner>}
      <div className="row end" style={{ marginBottom: ".5rem" }}>
        <button onClick={async () => { await post("/admin/schema/refresh", {}); await load(); toast.show("Schema re-read from the database"); }}>Re-scan database</button>
      </div>
      <div className="split-cols">
        <div className="card list" role="list" aria-label="Tables">
          {tables.map((t) => (
            <button key={t.name} className="item" aria-pressed={t.name === sel} onClick={() => setSel(t.name)}>
              {t.name}<span className="muted small"> · {t.row_count.toLocaleString()} rows</span>
            </button>))}
        </div>
        {table && (
          <div>
            <div className="card">
              <label className="field">Table description
                <textarea key={table.name + "d"} defaultValue={table.description} onBlur={(e) => e.target.value !== table.description && saveTable({ description: e.target.value })} />
              </label>
              <label className="field">Table synonyms
                <span className="hint">Comma-separated words users might say for this table.</span>
                <input type="text" key={table.name + "s"} defaultValue={table.synonyms.join(", ")}
                  onBlur={(e) => saveTable({ synonyms: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
              </label>
            </div>
            <div className="card" style={{ padding: 0 }}>
              <div className="scroll" style={{ maxHeight: "none", border: 0 }}>
                <table className="data">
                  <thead><tr><th>Column</th><th>Type</th><th>Description</th><th>Synonyms</th><th>Sensitive</th></tr></thead>
                  <tbody>
                    {table.columns.map((c) => (
                      <tr key={table.name + c.name}>
                        <td><strong>{c.name}</strong>{c.pk && <span className="pill" style={{ marginLeft: 6 }}>key</span>}
                          {c.fk && <div className="muted small">→ {c.fk}</div>}
                          {c.sample_values.length > 0 && <div className="muted small">{c.sample_values.slice(0, 5).join(", ")}{c.sample_values.length > 5 ? "…" : ""}</div>}</td>
                        <td className="mono">{c.type}</td>
                        <td style={{ minWidth: 220 }}><textarea aria-label={`${c.name} description`} style={{ minHeight: "3rem" }} defaultValue={c.description}
                          onBlur={(e) => e.target.value !== c.description && saveCol(c, { description: e.target.value })} /></td>
                        <td style={{ minWidth: 160 }}><input type="text" aria-label={`${c.name} synonyms`} defaultValue={c.synonyms.join(", ")} placeholder="revenue*, sales"
                          onBlur={(e) => saveCol(c, { synonyms: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></td>
                        <td><input type="checkbox" aria-label={`${c.name} is sensitive`} checked={c.is_sensitive} onChange={(e) => saveCol(c, { is_sensitive: e.target.checked })} /></td>
                      </tr>))}
                  </tbody>
                </table>
              </div>
            </div>
            <p className="muted small">Tip: end a synonym with * (for example <span className="mono">revenue*</span>) to make this column the default when a term could mean several columns.</p>
          </div>)}
      </div>
      {toast.node}
    </>
  );
}
