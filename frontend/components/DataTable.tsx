"use client";
import { useMemo, useState } from "react";
import type { TableData } from "@/lib/types";

const fmt = (v: unknown) => v === null || v === undefined ? "–" : typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 })) : String(v);

export default function DataTable({ table }: { table: TableData }) {
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null);
  const rows = useMemo(() => {
    if (!sort) return table.rows;
    return [...table.rows].sort((a, b) => {
      const x = a[sort.col], y = b[sort.col];
      if (x === y) return 0;
      if (x === null) return 1;
      if (y === null) return -1;
      return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * sort.dir;
    });
  }, [table.rows, sort]);
  if (!table.rows.length) return <p className="muted">No rows matched.</p>;
  return (
    <div className="scroll">
      <table className="data">
        <thead><tr>{table.columns.map((c, i) => (
          <th key={c + i} aria-sort={sort?.col === i ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
            <button onClick={() => setSort(sort?.col === i ? { col: i, dir: sort.dir === 1 ? -1 : 1 } : { col: i, dir: 1 })}>
              {c}{sort?.col === i ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
            </button>
          </th>))}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className={typeof v === "number" ? "num" : ""}>{fmt(v)}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}
