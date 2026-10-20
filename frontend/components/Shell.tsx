"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";

const NAV = [
  { href: "/", label: "Ask a question" },
  { group: "Admin" },
  { href: "/admin/schema", label: "Schema manager" },
  { href: "/admin/examples", label: "Examples manager" },
  { href: "/admin/logs", label: "Query logs" },
  { href: "/admin/guardrails", label: "Guardrails" },
  { href: "/admin/config", label: "Model config" },
] as const;

export default function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">QueryMind<small>Ask your data in plain English</small></div>
        <nav className="nav" aria-label="Main">
          {NAV.map((n, i) =>
            "group" in n ? <div key={i} className="group">{n.group}</div> : (
              <Link key={n.href} href={n.href} aria-current={path === n.href ? "page" : undefined}>{n.label}</Link>
            ))}
        </nav>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
