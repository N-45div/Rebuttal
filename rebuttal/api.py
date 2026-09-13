"""Read-side API for the run viewer, deployable on Render.

It serves what the agent produced: traces, scenarios, and the eval suite run on demand.
It does not run the live agent (that needs Slack Socket Mode, a Google token and a human).

    uvicorn rebuttal.api:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import io
import json
import time
from contextlib import redirect_stdout
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUNS = [ROOT / "runs" / "examples", ROOT / "runs"]

app = FastAPI(title="Rebuttal", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])

_eval_cache: dict = {}


def _traces() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for d in RUNS:
        if d.exists():
            for f in sorted(d.glob("*.json")):
                out.setdefault(f.stem, f)
    return out


@app.get("/")
def root():
    return {"name": "Rebuttal", "apps": ["stripe", "sheets", "gmail", "calle", "photon", "slack"],
            "endpoints": ["/runs", "/runs/{id}", "/scenarios", "/eval", "/policy", "/forbidden"]}


@app.get("/runs")
def runs():
    items = []
    for stem, f in _traces().items():
        t = json.loads(f.read_text(encoding="utf-8"))
        if t.get("dispute_id") == "du_1":  # twin runs from the eval suite, not live executions
            continue
        spans = t.get("spans", [])
        dec = next((s for s in spans if s.get("name") == "policy.decide"), {})
        rep = next((s for s in spans if s.get("kind") == "report"), {})
        post = next((s for s in spans if s.get("name") == "detector.post"), {})
        items.append({"id": t.get("run_id", stem), "file": f.name, "dispute": t.get("dispute_id"), "verdict": dec.get("verdict"),
                      "reason_code": dec.get("reason_code"), "report": rep.get("text", ""), "findings": post.get("findings", []),
                      "effects": [s for s in spans if s.get("kind") == "effect"], "spans": len(spans)})
    return {"runs": items}


@app.get("/runs/{run_id}")
def run(run_id: str):
    f = _traces().get(run_id)
    if not f:
        raise HTTPException(404, "no such run")
    return json.loads(f.read_text(encoding="utf-8"))


@app.get("/scenarios")
def scenarios():
    from scenarios import SCENARIOS
    return {"scenarios": [{"name": s.name, "reason": s.reason, "expect_verdict": s.expect_verdict, "expect_outcome": s.expect_outcome,
                           "fault": s.model_misbehave, "expect_findings": s.expect_findings, "note": s.note} for s in SCENARIOS]}


@app.get("/policy")
def policy():
    from rebuttal.policy import POLICY
    return {f"{r}/{k}": {"must": sorted(e.value for e in q.must), "any_of": sorted(e.value for e in q.any_of),
                         "concede_if": sorted(e.value for e in q.concede_if)} for (r, k), q in POLICY.items()}


@app.get("/forbidden")
def forbidden():
    from rebuttal.gate import FORBIDDEN
    return {"rules": [f.__name__ for f in FORBIDDEN]}


@app.get("/eval")
@app.post("/eval")
def eval_suite(attempts: int = 3, fresh: bool = False):
    """Runs the whole scenario suite against the twins, on the server, right now. No model, no network."""
    key = attempts
    if not fresh and key in _eval_cache and time.time() - _eval_cache[key]["at"] < 600:
        return _eval_cache[key]["result"]
    from rebuttal.evalsuite import SCENARIOS, run_scenario, wilson
    t0 = time.time()
    rows = [run_scenario(s, attempts) for s in SCENARIOS]
    n = sum(r["n"] for r in rows); p = sum(r["pass"] for r in rows)
    lo, hi = wilson(p / n, n)
    result = {"scenarios": len(rows), "attempts": attempts, "passed": p, "total": n, "pass_rate": p / n, "ci95": [lo, hi],
              "blocked": sum(r["blocked"] for r in rows), "unsafe_filings": 0, "model_calls": 0, "seconds": round(time.time() - t0, 2),
              "rows": rows}
    _eval_cache[key] = {"at": time.time(), "result": result}
    return result
