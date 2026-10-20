"use client";
import { useEffect, useState } from "react";
import { api, post, put } from "@/lib/api";
import type { ModelConfig } from "@/lib/types";
import { Banner, Toggle, useToast } from "@/components/ui";

interface Options { providers: string[]; default_models: Record<string, string>; dialects: Record<string, string>; provider_ready: Record<string, boolean>; embedding_backend: string }

export default function ModelConfigPage() {
  const [c, setC] = useState<ModelConfig | null>(null);
  const [o, setO] = useState<Options | null>(null);
  const [err, setErr] = useState("");
  const toast = useToast();

  useEffect(() => {
    api<{ settings: ModelConfig; options: Options }>("/admin/config").then((r) => { setC(r.settings); setO(r.options); }).catch((e) => setErr(e.message));
  }, []);

  async function save() {
    try { const r = await put<{ settings: ModelConfig }>("/admin/config", c); setC(r.settings); toast.show("Model configuration saved"); }
    catch (e: any) { toast.show(e.message, "error"); }
  }
  async function reset() {
    try { const r = await post<{ settings: ModelConfig }>("/admin/config/reset", {}); setC(r.settings); toast.show("Reset to defaults"); }
    catch (e: any) { toast.show(e.message, "error"); }
  }
  if (err) return <Banner kind="error">{err}</Banner>;
  if (!c || !o) return <p className="muted">Loading…</p>;
  const set = <K extends keyof ModelConfig>(k: K, v: ModelConfig[K]) => setC({ ...c, [k]: v });
  const ready = o.provider_ready[c.provider];

  return (
    <>
      <h1>Model config</h1>
      <p className="muted">Choose which model writes the SQL and how it behaves. API keys are read from server environment variables and are never stored here.</p>
      {c.provider === "offline" && <Banner kind="warn">Offline baseline is active: questions are answered by adapting the closest solved example. It is only meant for testing without an API key. Choose a provider for real results.</Banner>}
      {!ready && c.provider !== "offline" && <Banner kind="error">No API key found on the server for {c.provider}. Set {c.provider === "anthropic" ? "ANTHROPIC_API_KEY" : "OPENAI_API_KEY"} and restart the backend.</Banner>}

      <div className="card">
        <h2>Model</h2>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <label className="field grow">Provider
            <select value={c.provider} onChange={(e) => setC({ ...c, provider: e.target.value, model: o.default_models[e.target.value] })}>
              {o.providers.map((p) => <option key={p} value={p}>{p === "offline" ? "Offline baseline (no LLM)" : p[0].toUpperCase() + p.slice(1)}{o.provider_ready[p] ? "" : " — no key"}</option>)}</select></label>
          <label className="field grow">Model name<input type="text" value={c.model} onChange={(e) => set("model", e.target.value)} /></label>
        </div>
        {(c.provider === "ollama" || c.provider === "openai") && (
          <label className="field">Endpoint override<span className="hint">Ollama default is http://localhost:11434. Any OpenAI-compatible endpoint also works.</span>
            <input type="text" value={c.base_url} onChange={(e) => set("base_url", e.target.value)} placeholder="http://localhost:11434" /></label>)}
        <div className="row" style={{ alignItems: "flex-start" }}>
          <label className="field grow">Temperature: {c.temperature.toFixed(1)}<span className="hint">0 is most repeatable, and best for SQL.</span>
            <input type="range" min={0} max={1} step={0.1} value={c.temperature} onChange={(e) => set("temperature", Number(e.target.value))} style={{ width: "100%" }} /></label>
          <label className="field grow">Max tokens<span className="hint">Budget for each model reply.</span>
            <input type="number" min={64} max={8192} value={c.max_tokens} onChange={(e) => set("max_tokens", Number(e.target.value))} /></label>
          <label className="field grow">Examples per question<span className="hint">Few-shot examples retrieved ({o.embedding_backend}).</span>
            <input type="number" min={1} max={10} value={c.k_examples} onChange={(e) => set("k_examples", Number(e.target.value))} /></label>
        </div>
      </div>

      <div className="card">
        <h2>SQL dialect</h2>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <label className="field grow">Dialect the model writes<span className="hint">Must match the connected database.</span>
            <select value={c.dialect} onChange={(e) => set("dialect", e.target.value)}>{Object.entries(o.dialects).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className="field grow">Also show SQL converted to<span className="hint">Display only; the original is what runs.</span>
            <select value={c.output_dialect} onChange={(e) => set("output_dialect", e.target.value)}><option value="">Don’t convert</option>
              {Object.entries(o.dialects).filter(([k]) => k !== c.dialect).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        </div>
      </div>

      <div className="card">
        <h2>Behaviour</h2>
        <Toggle checked={c.self_heal} onChange={(v) => set("self_heal", v)} label="Retry once if the database rejects a query" hint="The error is sent back to the model so it can fix its own mistake." />
        <Toggle checked={c.clarify_ambiguities} onChange={(v) => set("clarify_ambiguities", v)} label="Ask before guessing on ambiguous terms" hint="For example, asking whether “revenue” means order totals or payments." />
        <label className="field">Business rules<span className="hint">Plain-language definitions the model must follow, such as what “revenue” or “last quarter” means.</span>
          <textarea className="mono" style={{ minHeight: "11rem" }} value={c.business_rules} onChange={(e) => set("business_rules", e.target.value)} /></label>
      </div>
      <div className="row"><button className="primary" onClick={save}>Save configuration</button><button onClick={reset}>Reset to defaults</button></div>
      {toast.node}
    </>
  );
}
