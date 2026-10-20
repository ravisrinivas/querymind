"use client";
import type { TableData } from "@/lib/types";

/** Bonus: if the result has exactly 2 columns and the second is numeric, draw a bar chart (line for time-like labels). */
export function chartable(t: TableData) {
  return t.columns.length === 2 && t.rows.length >= 2 && t.rows.length <= 40 && t.rows.every((r) => typeof r[1] === "number");
}

export default function AutoChart({ table }: { table: TableData }) {
  if (!chartable(table)) return null;
  const vals = table.rows.map((r) => r[1] as number);
  const labels = table.rows.map((r) => String(r[0]));
  const max = Math.max(...vals, 0), min = Math.min(...vals, 0);
  const span = max - min || 1;
  const timeLike = labels.every((l) => /^\d{4}(-\d{2})?$/.test(l));
  const W = 560, H = 220, pad = { l: 8, r: 8, t: 12, b: 52 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const y = (v: number) => pad.t + ih - ((v - min) / span) * ih;
  const step = iw / vals.length;
  const x = (i: number) => pad.l + step * i + step / 2;
  const every = Math.ceil(vals.length / 12);
  return (
    <figure style={{ margin: "0 0 .75rem" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`${table.columns[1]} by ${table.columns[0]}`}>
        <line x1={pad.l} x2={W - pad.r} y1={y(0)} y2={y(0)} stroke="var(--rule)" />
        {timeLike ? (
          <polyline fill="none" stroke="var(--accent)" strokeWidth="2.5" points={vals.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
        ) : vals.map((v, i) => (
          <rect key={i} x={x(i) - step * 0.34} width={step * 0.68} y={Math.min(y(v), y(0))} height={Math.abs(y(v) - y(0))} fill="var(--accent)" rx="2">
            <title>{`${labels[i]}: ${v.toLocaleString()}`}</title>
          </rect>
        ))}
        {timeLike && vals.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r="3" fill="var(--accent)"><title>{`${labels[i]}: ${v.toLocaleString()}`}</title></circle>)}
        {labels.map((l, i) => i % every === 0 && (
          <text key={i} x={x(i)} y={H - pad.b + 14} fontSize="10" fill="var(--ink-2)" textAnchor="end" transform={`rotate(-35 ${x(i)} ${H - pad.b + 14})`}>
            {l.length > 16 ? l.slice(0, 15) + "…" : l}
          </text>))}
      </svg>
      <figcaption className="muted small">{table.columns[1]} by {table.columns[0]}</figcaption>
    </figure>
  );
}
