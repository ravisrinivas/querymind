"use client";
import { useEffect, useRef, useState } from "react";
import { post } from "@/lib/api";
import type { QueryResponse } from "@/lib/types";
import DataTable from "@/components/DataTable";
import AutoChart from "@/components/AutoChart";
import { Banner, Pill } from "@/components/ui";

const SUGGESTIONS = [
  "What was total revenue by month in 2025?",
  "Top 5 customers by revenue last quarter",
  "How many orders are there for each status?",
  "Average delivery time in days by carrier",
  "Which product categories have the best average rating?",
];

type Turn = { id: number; req: { question: string; clarifications: Record<string, string> }; res?: QueryResponse; err?: string; loading: boolean };

export default function Page() {
  const [q, setQ] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [explain, setExplain] = useState(false);
  const [clarify, setClarify] = useState(false);
  const [listening, setListening] = useState(false);
  const [speechOk, setSpeechOk] = useState(false);
  const nextId = useRef(1);
  const recRef = useRef<any>(null);

  useEffect(() => { setSpeechOk(typeof window !== "undefined" && !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)); }, []);

  async function ask(question: string, clarifications: Record<string, string> = {}, replaceId?: number) {
    const text = question.trim();
    if (!text) return;
    const id = replaceId ?? nextId.current++;
    const base: Turn = { id, req: { question: text, clarifications }, loading: true };
    setTurns((t) => replaceId ? t.map((x) => x.id === id ? base : x) : [base, ...t]);
    if (!replaceId) setQ("");
    try {
      const res = await post<QueryResponse>("/query", { question: text, clarifications, clarify, explain });
      setTurns((t) => t.map((x) => x.id === id ? { ...x, res, loading: false } : x));
    } catch (e: any) {
      setTurns((t) => t.map((x) => x.id === id ? { ...x, err: e.message, loading: false } : x));
    }
  }

  function toggleMic() {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) return;
    if (listening) { recRef.current?.stop(); return; }
    const rec = new SR();
    rec.lang = "en-US"; rec.interimResults = false; rec.maxAlternatives = 1;
    rec.onresult = (e: any) => setQ((prev) => (prev ? prev + " " : "") + e.results[0][0].transcript);
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec; setListening(true); rec.start();
  }

  return (
    <>
      <h1>Ask a question about your data</h1>
      <p className="muted">Type it the way you’d say it. QueryMind shows its working so you can check the answer.</p>

      <div className="card">
        <form className="askbar" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
          <textarea aria-label="Your question" placeholder="e.g. Which customers placed an order in the last 7 days?" value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(q); } }} />
          {speechOk && <button type="button" onClick={toggleMic} aria-pressed={listening} title="Speak your question">{listening ? "Stop" : "Speak"}</button>}
          <button className="primary" type="submit" disabled={!q.trim()}>Ask</button>
        </form>
        <div className="row small" style={{ marginTop: ".6rem" }}>
          <label className="check" style={{ margin: 0 }}><input type="checkbox" checked={explain} onChange={(e) => setExplain(e.target.checked)} />Explain the query in plain English</label>
          <label className="check" style={{ margin: 0 }}><input type="checkbox" checked={clarify} onChange={(e) => setClarify(e.target.checked)} />Check with me when a term is ambiguous</label>
        </div>
        {turns.length === 0 && (
          <div className="chips" style={{ marginTop: ".8rem" }}>
            <div className="muted small" style={{ marginBottom: ".4rem" }}>Try one of these</div>
            {SUGGESTIONS.map((s) => <button key={s} onClick={() => ask(s)}>{s}</button>)}
          </div>
        )}
      </div>

      {turns.map((t) => <TurnView key={t.id} turn={t} onClarify={(c) => ask(t.req.question, { ...t.req.clarifications, ...c }, t.id)} />)}
    </>
  );
}

function TurnView({ turn, onClarify }: { turn: Turn; onClarify: (c: Record<string, string>) => void }) {
  const { res } = turn;
  const [showTrace, setShowTrace] = useState(false);
  const [copied, setCopied] = useState(false);
  return (
    <section className="turn card" aria-live="polite">
      <div className="q">{turn.req.question}</div>
      {turn.loading && <p className="muted">Working on it…</p>}
      {turn.err && <Banner kind="error">{turn.err}</Banner>}
      {res?.status === "unsupported" && <Banner kind="warn">{res.error}</Banner>}
      {res?.status === "blocked" && <Banner kind="error"><strong>Blocked by guardrails.</strong> {res.error}</Banner>}
      {res?.status === "error" && <Banner kind="error">{res.error}{res.generated_sql && <div className="mono" style={{ marginTop: ".4rem" }}>{res.generated_sql}</div>}</Banner>}

      {res?.status === "needs_clarification" && (
        <div>
          <p><strong>Before I run this:</strong> some terms could mean more than one thing. Pick the meaning you intend.</p>
          {res.ambiguities.filter((a) => a.resolved_by === "default" || a.resolved_by === "none").map((a) => (
            <div key={a.term} style={{ marginBottom: ".6rem" }}>
              <div className="small muted">By “{a.term}” do you mean…</div>
              <div className="chips">{a.candidates.map((c) => <button key={c} onClick={() => onClarify({ [a.term]: c })}>{c}</button>)}</div>
            </div>))}
        </div>
      )}

      {res?.status === "success" && res.table && (
        <>
          <div className="answer">{res.nl_summary}</div>
          {res.ambiguities.some((a) => a.resolved_by === "default") && (
            <Banner kind="warn">
              {res.ambiguities.filter((a) => a.resolved_by === "default").map((a) => (
                <div key={a.term}>“{a.term}” can mean {a.candidates.join(", ")}. I used <strong>{a.chosen}</strong>. Turn on “check with me” to choose.</div>))}
            </Banner>)}
          <div className="split">
            <div>
              <AutoChart table={res.table} />
              <DataTable table={res.table} />
              {res.truncated && <p className="small muted">Results were capped by the row limit set in Guardrails.</p>}
            </div>
            <div>
              <div className="row" style={{ marginBottom: ".4rem" }}>
                <h2 className="grow" style={{ margin: 0 }}>Working</h2>
                <button className="ghost" onClick={() => { navigator.clipboard?.writeText(res.sql || ""); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>{copied ? "Copied" : "Copy SQL"}</button>
              </div>
              <div className="working"><pre>{res.sql}</pre></div>
              {res.sql_dialect_output && <><div className="small muted" style={{ margin: ".6rem 0 .3rem" }}>Converted SQL</div><div className="working"><pre>{res.sql_dialect_output}</pre></div></>}
              {res.explanation && <p className="small" style={{ marginTop: ".6rem" }}>{res.explanation}</p>}
            </div>
          </div>
          <div className="row small muted" style={{ marginTop: ".75rem" }}>
            <Pill kind="success">{res.row_count.toLocaleString()} rows</Pill>
            <span>query {res.latency_ms.toFixed(1)} ms · total {res.total_ms.toFixed(0)} ms</span>
            {res.query_type && <span>{res.query_type.replace("SELECT_", "").toLowerCase()}</span>}
            {res.retried && <Pill>{res.self_healed ? "self-healed" : "retried once"}</Pill>}
            <span>{res.provider}/{res.model}</span>
            <button className="ghost" onClick={() => setShowTrace((s) => !s)}>{showTrace ? "Hide steps" : "Show steps"}</button>
          </div>
          {showTrace && <div className="trace">{res.trace.map((s, i) => <span key={i}>{s.stage} {s.ms}ms</span>)}</div>}
        </>
      )}
    </section>
  );
}
