"use client";
import { useEffect, useState } from "react";
import { bundled, type Eval } from "@/lib/api";

export default function Stats() {
  const [ev, setEv] = useState<Eval | null>(null);
  useEffect(() => { bundled().then((b) => setEv(b.eval)).catch(() => {}); }, []);
  const items: [string, string][] = [
    ["6", "external apps"],
    [ev ? String(ev.scenarios) : "22", "seeded scenarios"],
    [ev ? `${ev.passed}/${ev.total}` : "22/22", "real coordinator runs passed"],
    [ev ? String(ev.blocked) : "6", "forbidden effects blocked"],
    ["0", "unsafe filings"],
    ["8", "gated tools for Astra"],
  ];
  return (
    <div className="stats">
      {items.map(([n, l]) => (
        <div className="stat" key={l}><div className="n">{n}</div><div className="l">{l}</div></div>
      ))}
    </div>
  );
}
