"use client";
import { Fragment, useCallback, useEffect, useState } from "react";
import { API, api } from "@/lib/api";
import { QUERY_TYPES, type LogRow } from "@/lib/types";
import { Banner, Pill } from "@/components/ui";

const PAGE = 25;
const STATUSES = ["success", "error", "blocked", "unsupported", "needs_clarification"];

export default function Logs() {
  const [rows, setRows] = useState<LogRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [status, setStatus] = useState("");
  const [qtype, setQtype] = useState("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [stats, setStats] = useState<Record<string, number | null>>({});
  const [err, setErr] = useState("");

  const params = useCallback((extra: Record<string, string | number> = {}) => {
    const p = new URLSearchParams();
    if (status) p.set("status", status); if (qtype) p.set("query_type", qtype); if (search) p.set("search", search);
    Object.entries(extra).forEach(([k, v]) => p.set(k, String(v)));
    return p.toString();
  }, [status, qtype, search]);

  const load = useCallback(async () => {
    try {
      const r = await api<{ total: number; items: LogRow[] }>(`/admin/logs?${params({ limit: PAGE, offset: page * PAGE })}`);
      setRows(r.items); setTotal(r.total); setStats(await api("/admin/logs/stats")); setErr("");
    } catch (e: any) { setErr(e.message); }
  }, [params, page]);
  useEffect(() => { load(); }, [load]);

  return (
    <>
      <h1>Query logs</h1>
      <p className="muted">Every question, the SQL that was generated and run, and how it went.</p>
      {err && <Banner kind="error">{err}</Banner>}
      <div className="row small" style={{ marginBottom: ".75rem" }}>
        <Pill>{stats.total ?? 0} total</Pill><Pill kind="success">{stats.success ?? 0} succeeded</Pill>
        <Pill kind="error">{stats.error ?? 0} errors</Pill><Pill kind="blocked">{stats.blocked ?? 0} blocked</Pill>
        <Pill kind="unsupported">{stats.unsupported ?? 0} unsupported</Pill>
        {stats.avg_latency_ms != null && <span className="muted">avg query time {stats.avg_latency_ms} ms</span>}
      </div>
      <div className="card row">
        <input type="text" aria-label="Search logs" placeholder="Search question or SQL" value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }} style={{ maxWidth: 300 }} />
        <select aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }} style={{ width: "auto" }}>
          <option value="">Any status</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
        <select aria-label="Query type" value={qtype} onChange={(e) => { setQtype(e.target.value); setPage(0); }} style={{ width: "auto" }}>
          <option value="">Any type</option>{[...QUERY_TYPES, "UNSUPPORTED"].map((s) => <option key={s} value={s}>{s.replace("SELECT_", "").toLowerCase()}</option>)}</select>
        <div className="grow" />
        <button onClick={load}>Refresh</button>
        <a href={`${API}/admin/logs/export?${params()}`}><button className="primary" type="button">Export CSV</button></a>
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div className="scroll" style={{ maxHeight: "none", border: 0 }}>
          <table className="data">
            <thead><tr><th>Time</th><th>Question</th><th>Type</th><th>Status</th><th>Latency</th><th>Rows</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => (
                <Fragment key={r.id}>
                  <tr>
                    <td className="small">{new Date(r.ts).toLocaleString()}</td><td>{r.question}</td>
                    <td className="small">{r.query_type?.replace("SELECT_", "").toLowerCase() ?? "–"}</td>
                    <td><Pill kind={r.status}>{r.status}</Pill>{r.retried ? <span className="muted small"> retried</span> : null}</td>
                    <td className="num">{r.latency_ms != null ? `${r.latency_ms.toFixed(1)} ms` : "–"}</td><td className="num">{r.row_count}</td>
                    <td><button className="ghost" onClick={() => setOpen(open === r.id ? null : r.id)} aria-expanded={open === r.id}>{open === r.id ? "Hide" : "Details"}</button></td>
                  </tr>
                  {open === r.id && (
                    <tr><td colSpan={7}>
                      {r.error && <Banner kind="error">{r.error}</Banner>}
                      {r.generated_sql && <><div className="small muted">Generated</div><div className="working"><pre>{r.generated_sql}</pre></div></>}
                      {r.final_sql && r.final_sql !== r.generated_sql && <><div className="small muted" style={{ marginTop: ".5rem" }}>Executed (after validation)</div><div className="working"><pre>{r.final_sql}</pre></div></>}
                      <div className="small muted" style={{ marginTop: ".4rem" }}>{r.provider}/{r.model} · total {r.total_ms?.toFixed(0)} ms</div>
                    </td></tr>)}
                </Fragment>))}
              {!rows.length && <tr><td colSpan={7} className="muted">No queries logged yet. Ask a question on the main page.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      <div className="row">
        <button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
        <span className="muted small">Page {page + 1} of {Math.max(1, Math.ceil(total / PAGE))} · {total} matching</span>
        <button disabled={(page + 1) * PAGE >= total} onClick={() => setPage(page + 1)}>Next</button>
      </div>
    </>
  );
}
