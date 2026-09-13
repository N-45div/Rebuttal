export const API = (process.env.NEXT_PUBLIC_API_URL || "https://rebuttal-api.onrender.com").replace(/\/$/, "");

export type Span = Record<string, any> & { t: number; kind: string; name: string };
export type Trace = { run_id: string; dispute_id: string; spans: Span[] };
export type EvalRow = { name: string; expect: string; pass: number; n: number; blocked: number; findings: Record<string, number>; note: string };
export type Eval = { scenarios: number; attempts: number; passed: number; total: number; ci95: [number, number]; blocked: number; rows: EvalRow[]; seconds?: number };
export type Bundle = { examples: Record<string, Trace>; eval: Eval };

export async function bundled(): Promise<Bundle> {
  const r = await fetch("/data.json", { cache: "no-store" });
  return r.json();
}

export async function liveRuns(): Promise<Record<string, Trace> | null> {
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 8000);
    const r = await fetch(`${API}/runs`, { signal: ctl.signal });
    clearTimeout(t);
    if (!r.ok) return null;
    const list = (await r.json()).runs as { id: string }[];
    const out: Record<string, Trace> = {};
    for (const it of list.slice(0, 12)) {
      const tr = await fetch(`${API}/runs/${it.id}`);
      if (tr.ok) out[it.id] = await tr.json();
    }
    return out;
  } catch {
    return null;
  }
}

export async function liveEval(fresh = false): Promise<Eval | null> {
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 60000);
    const r = await fetch(`${API}/eval?attempts=3${fresh ? "&fresh=true" : ""}`, { signal: ctl.signal, method: fresh ? "POST" : "GET" });
    clearTimeout(t);
    return r.ok ? r.json() : null;
  } catch {
    return null;
  }
}
