import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import pricing, replay, store

PAGE = Path(__file__).with_name("ui.html")
app = FastAPI(title="agentfork")

def _load(text):
    return json.loads(text) if text else None

def _resolve(prefix):
    matches = store.find_runs(prefix)
    if not matches:
        raise HTTPException(404, f"No run starting with {prefix}")
    if len(matches) > 1:
        raise HTTPException(400, f"{prefix} matches several runs")
    return matches[0]

def _preview(text, limit=160):
    val = _load(text)
    if val is None:
        return ""
    if isinstance(val, dict) and "args" in val:
        parts = list(val.get("args") or []) + list((val.get("kwargs") or {}).values())
        val = parts[0] if len(parts) == 1 else parts
    return (val if isinstance(val, str) else json.dumps(val))[:limit]

def _brief(run, steps=None):
    cost = None
    if steps is not None:
        n_steps = len(steps)
        tokens = sum((s["tokens_in"] or 0) + (s["tokens_out"] or 0) for s in steps)
        cost = pricing.steps_cost([s for s in steps if not s["cached"]])
    else:
        n_steps, tokens = run.get("n_steps", 0), run.get("tokens", 0)
    duration = f"{run['ended_at'] - run['started_at']:.1f}s" if run.get("ended_at") else "-"
    started = datetime.fromtimestamp(run["started_at"]).strftime("%m-%d %H:%M:%S")
    return {"id": run["id"], "name": run["name"], "status": run["status"], "n_steps": n_steps,
            "tokens": tokens, "cost": cost, "duration": duration, "started": started,
            "parent_run_id": run.get("parent_run_id"), "fork_step": run.get("fork_step"),
            "input_preview": _preview(run.get("input_json")), "output_preview": _preview(run.get("output_json"))}

def summarize(step):
    inp, out = _load(step["input_json"]), _load(step["output_json"])
    if step["error"]:
        return step["error"]
    if step["type"] == "tool" and isinstance(inp, dict):
        return f"{inp.get('kwargs') or inp.get('args')} -> {out}"
    if step["type"] == "llm" and isinstance(out, dict):
        if "choices" in out:
            msg = (out.get("choices") or [{}])[0].get("message") or {}
            calls = msg.get("tool_calls") or []
            if calls:
                return "calls " + ", ".join(c["function"]["name"] for c in calls)
            return (msg.get("content") or "")[:300]
        blocks = [b for b in (out.get("content") or []) if isinstance(b, dict)]
        tools = [b.get("name") for b in blocks if b.get("type") == "tool_use"]
        if tools:
            return "calls " + ", ".join(tools)
        return " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")[:300]
    return str(out)[:300]

@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE.read_text()

@app.get("/api/runs")
def runs(limit: int = 100):
    return [_brief(r) for r in store.list_runs(limit)]

@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    run = _resolve(run_id)
    steps = store.get_steps(run["id"])
    return {"run": _brief(run, steps), "input": _load(run["input_json"]), "output": _load(run["output_json"]),
            "steps": [{"seq": s["seq"], "type": s["type"], "name": s["name"], "cached": bool(s["cached"]),
                       "error": s["error"], "latency_ms": s["latency_ms"] or 0,
                       "tokens_in": s["tokens_in"], "tokens_out": s["tokens_out"],
                       "input": _load(s["input_json"]), "output": _load(s["output_json"]),
                       "summary": summarize(s)} for s in steps]}

class ForkIn(BaseModel):
    run_id: str
    step: int
    output: Optional[str] = None
    model: Optional[str] = None
    system: Optional[str] = None

@app.post("/api/fork")
def fork(body: ForkIn):
    run = _resolve(body.run_id)
    try:
        new_id, _ = replay.fork(run, body.step, output=body.output, model=body.model, system=body.system)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Fork failed: {e!r}")
    return {"run_id": new_id}

class SweepIn(BaseModel):
    run_id: str
    step: int
    kind: str
    values: List[str]
    repeat: int = 1
    expect: Optional[str] = None
    parallel: int = 4

def _group(label, value, rows, expect):
    n = len(rows)
    return {"label": label, "value": value, "runs": n,
            "ok": sum(r["status"] == "ok" for r in rows),
            "passed": None if expect is None else sum(bool(r["passed"]) for r in rows),
            "avg_tokens": round(sum(r["tokens"] for r in rows) / n),
            "avg_time_s": round(sum(r["latency_ms"] for r in rows) / n / 1000, 1),
            "avg_cost": None if any(r["cost"] is None for r in rows) else sum(r["cost"] for r in rows) / n,
            "sample": str(rows[0]["result"])[:200],
            "run_ids": [r["run_id"] for r in rows if r["run_id"]]}

def _variants(body):
    if body.kind not in ("model", "system", "output"):
        raise HTTPException(400, "kind must be model, system or output")
    values = [v.strip() if body.kind == "model" else v for v in body.values if v.strip()]
    if not values:
        raise HTTPException(400, "Add at least one variant")
    return [{body.kind: v} for v in values]

@app.post("/api/estimate")
def estimate(body: SweepIn):
    try:
        return replay.estimate(_resolve(body.run_id), body.step, _variants(body), max(1, min(body.repeat, 10)))
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/api/sweep")
def sweep(body: SweepIn):
    variants = _variants(body)
    run = _resolve(body.run_id)
    try:
        results = replay.sweep(run, body.step, variants, repeat=max(1, min(body.repeat, 10)), expect=body.expect,
                               parallel=max(1, min(body.parallel, 10)))
    except ValueError as e:
        raise HTTPException(400, str(e))
    groups = [_group("original", None, [replay.baseline(run, body.step, body.expect)], body.expect)]
    for i, v in enumerate(variants, 1):
        rows = [r for r in results if r["variant"] is v]
        label = f"model={v['model']}" if body.kind == "model" else f"{body.kind} #{i}"
        groups.append(_group(label, None if body.kind == "model" else v[body.kind], rows, body.expect))
    return {"groups": groups}
