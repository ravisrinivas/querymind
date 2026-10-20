"use client";
import { useCallback, useEffect, useState } from "react";
import { api, del, post, put } from "@/lib/api";
import { QUERY_TYPES, type Example } from "@/lib/types";
import { Banner, Pill, useToast } from "@/components/ui";

type Row = Example & { id: number };
const blank = { question: "", sql: "", query_type: "" };

export default function ExamplesManager() {
  const [items, setItems] = useState<Row[]>([]);
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const [hits, setHits] = useState<Row[] | null>(null);
  const [form, setForm] = useState(blank);
  const [editing, setEditing] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const toast = useToast();

  const load = useCallback(async () => {
    try { setItems((await api<{ items: Row[] }>(`/admin/examples${filter ? `?query_type=${filter}` : ""}`)).items); setErr(""); }
    catch (e: any) { setErr(e.message); }
  }, [filter]);
  useEffect(() => { load(); }, [load]);

  async function runSearch() {
    if (!search.trim()) { setHits(null); return; }
    try { setHits((await post<{ items: Row[] }>("/admin/examples/search", { query: search, k: 8 })).items); }
    catch (e: any) { toast.show(e.message, "error"); }
  }
  async function save() {
    const body = { question: form.question, sql: form.sql, query_type: form.query_type || null };
    try {
      if (editing) await put(`/admin/examples/${editing}`, body); else await post("/admin/examples", body);
      toast.show(editing ? "Example updated" : "Example added"); setForm(blank); setEditing(null); await load();
    } catch (e: any) { toast.show(e.message, "error"); }
  }
  async function remove(id: number) {
    if (!confirm("Delete this example?")) return;
    try { await del(`/admin/examples/${id}`); toast.show("Example deleted"); await load(); setHits(null); }
    catch (e: any) { toast.show(e.message, "error"); }
  }

  const shown = hits ?? items;
  return (
    <>
      <h1>Examples manager</h1>
      <p className="muted">Solved question → SQL pairs. The most similar ones are shown to the model with every new question, so good examples are the fastest way to improve accuracy. {items.length} in the library.</p>
      {err && <Banner kind="error">{err}</Banner>}

      <div className="card">
        <h2>{editing ? `Edit example #${editing}` : "Add an example"}</h2>
        <label className="field">Question<input type="text" value={form.question} onChange={(e) => setForm({ ...form, question: e.target.value })} placeholder="How many orders were placed in 2024?" /></label>
        <label className="field">SQL<textarea className="mono" value={form.sql} onChange={(e) => setForm({ ...form, sql: e.target.value })} placeholder="SELECT COUNT(*) FROM orders WHERE …" /></label>
        <div className="row">
          <label className="field" style={{ margin: 0, minWidth: 200 }}>Query type
            <select value={form.query_type} onChange={(e) => setForm({ ...form, query_type: e.target.value })}>
              <option value="">Unlabelled</option>{QUERY_TYPES.map((t) => <option key={t} value={t}>{t.replace("SELECT_", "").toLowerCase()}</option>)}
            </select></label>
          <div className="grow" />
          {editing && <button onClick={() => { setEditing(null); setForm(blank); }}>Cancel</button>}
          <button className="primary" disabled={form.question.trim().length < 3 || form.sql.trim().length < 6} onClick={save}>{editing ? "Save changes" : "Add example"}</button>
        </div>
      </div>

      <div className="row" style={{ marginBottom: ".75rem" }}>
        <input type="text" className="grow" aria-label="Semantic search" placeholder="Search by meaning, e.g. money collected" value={search}
          onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && runSearch()} style={{ maxWidth: 420 }} />
        <button onClick={runSearch}>Search</button>
        {hits && <button className="ghost" onClick={() => { setHits(null); setSearch(""); }}>Clear search</button>}
        <div className="grow" />
        <select aria-label="Filter by type" value={filter} onChange={(e) => { setFilter(e.target.value); setHits(null); }} style={{ width: "auto" }}>
          <option value="">All types</option>{QUERY_TYPES.map((t) => <option key={t} value={t}>{t.replace("SELECT_", "").toLowerCase()}</option>)}
        </select>
      </div>
      {hits && <p className="muted small">Showing the {hits.length} most similar examples.</p>}

      {shown.map((e) => (
        <div className="card" key={e.id}>
          <div className="row">
            <strong className="grow">{e.question}</strong>
            {e.score != null && <Pill>{(e.score * 100).toFixed(0)}% match</Pill>}
            {e.query_type && <Pill>{e.query_type.replace("SELECT_", "").toLowerCase()}</Pill>}
            <button onClick={() => { setEditing(e.id); setForm({ question: e.question, sql: e.sql, query_type: e.query_type || "" }); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Edit</button>
            <button className="danger" onClick={() => remove(e.id)}>Delete</button>
          </div>
          <div className="working" style={{ marginTop: ".6rem" }}><pre>{e.sql}</pre></div>
        </div>))}
      {!shown.length && <p className="muted">No examples yet. Add one above.</p>}
      {toast.node}
    </>
  );
}
