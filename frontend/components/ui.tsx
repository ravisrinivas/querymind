"use client";
import { ReactNode, useCallback, useEffect, useState } from "react";

export function useToast() {
  const [msg, setMsg] = useState<{ text: string; kind: "ok" | "error" } | null>(null);
  useEffect(() => { if (msg) { const t = setTimeout(() => setMsg(null), 3500); return () => clearTimeout(t); } }, [msg]);
  const show = useCallback((text: string, kind: "ok" | "error" = "ok") => setMsg({ text, kind }), []);
  const node = msg ? <div className={`toast banner ${msg.kind}`} role="status">{msg.text}</div> : null;
  return { show, node };
}

export const Banner = ({ kind, children }: { kind: "error" | "warn" | "ok"; children: ReactNode }) =>
  <div className={`banner ${kind}`} role={kind === "error" ? "alert" : undefined}>{children}</div>;

export const Pill = ({ children, kind = "" }: { children: ReactNode; kind?: string }) => <span className={`pill ${kind}`}>{children}</span>;

export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="check">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span><strong>{label}</strong>{hint && <span className="muted small" style={{ display: "block" }}>{hint}</span>}</span>
    </label>
  );
}
