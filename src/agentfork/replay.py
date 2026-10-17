import importlib.util, json, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from . import pricing, recorder, store

def load_entry(run):
    path, qualname = run.get("entry_file"), run.get("entry_name")
    if not path or not Path(path).exists():
        raise RuntimeError("this run has no saved entry point; run your agent again and fork the new run")
    folder = str(Path(path).parent)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    spec = importlib.util.spec_from_file_location("agentfork_entry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    obj = module
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj

def fork(run, step, output=None, model=None, system=None, ctx=None):
    """Re-run `run` from `step` with one change. Returns (new run id, result).

    Pass a dict as `ctx` to read the new run id from ctx["run_id"] even if the agent raises.
    """
    steps = {s["seq"]: s for s in store.get_steps(run["id"])}
    if step not in steps:
        raise ValueError(f"run {run['id'][:8]} has no step {step}")
    kind = steps[step]["type"]
    override = {}
    if output is not None:
        if kind != "tool":
            raise ValueError("--output only works on tool steps")
        override["output"] = output
    if model or system:
        if kind != "llm":
            raise ValueError("--model and --system only work on llm steps")
        override.update({"model": model, "system": system})
    fn = load_entry(run)
    inputs = json.loads(run["input_json"])
    ctx = {} if ctx is None else ctx
    ctx.update({"parent_run_id": run["id"], "fork_step": step, "steps": steps, "override": override})
    token = recorder._replay.set(ctx)
    try:
        result = fn(*inputs["args"], **inputs["kwargs"])
    finally:
        recorder._replay.reset(token)
    return ctx.get("run_id"), result

def check(fixture, root="."):
    run = fixture["run"]
    steps = {s["seq"]: s for s in fixture["steps"]}
    fn = load_entry(dict(run, entry_file=str(Path(root) / run["entry_file"])))
    inputs = json.loads(run["input_json"])
    ctx = {"parent_run_id": None, "fork_step": float("inf"), "steps": steps, "override": {}, "strict": True}
    token = recorder._replay.set(ctx)
    try:
        result = fn(*inputs["args"], **inputs["kwargs"])
    finally:
        recorder._replay.reset(token)
    if ctx.get("seq") != max(steps, default=0):
        raise recorder.ReplayMismatch(
            f"the recorded run had {max(steps, default=0)} steps but the replay made {ctx.get('seq')}")
    expected = json.loads(run["output_json"])
    if recorder.to_jsonable(result) != expected:
        raise recorder.ReplayMismatch(f"final output changed\n  recorded: {expected!r}\n  now:      {result!r}")
    return result

def _check_variants(run, step, variants):
    steps = {s["seq"]: s for s in store.get_steps(run["id"])}
    if step not in steps:
        raise ValueError(f"run {run['id'][:8]} has no step {step}")
    kind = steps[step]["type"]
    for v in variants:
        if "output" in v and kind != "tool":
            raise ValueError("--output only works on tool steps")
        if ("model" in v or "system" in v) and kind != "llm":
            raise ValueError("--model and --system only work on llm steps")

def _summary(steps, result, expect):
    return {
        "tokens": sum((s["tokens_in"] or 0) + (s["tokens_out"] or 0) for s in steps),
        "latency_ms": sum(s["latency_ms"] or 0 for s in steps),
        "cost": pricing.steps_cost(steps),
        "passed": None if expect is None else expect.lower() in str(result).lower(),
    }

def steps_from(run, step):
    """The run's steps from `step` on, with token counts filled in for steps that were replayed from cache."""
    steps = []
    for s in store.get_steps(run["id"]):
        if s["seq"] >= step:
            if s["type"] == "llm" and s["tokens_in"] is None:
                s = dict(s)
                s["tokens_in"], s["tokens_out"] = store.tokens_for(s["cache_key"])
            steps.append(s)
    return steps

def estimate(run, step, variants, repeat=1):
    """Expected USD for a sweep, from the tokens the original run used from `step` on.

    A model variant is priced at that model for every LLM call from `step` on, as fork applies it.
    """
    steps = steps_from(run, step)
    per_run = [pricing.steps_cost(steps, v.get("model")) for v in variants]
    missing = sorted({m for v in variants for m in pricing.unpriced(steps, v.get("model"))})
    total = None if any(c is None for c in per_run) else sum(per_run) * repeat
    return {"per_run": per_run, "total": total, "unpriced": missing}

def baseline(run, step, expect=None):
    steps = steps_from(run, step)
    result = json.loads(run["output_json"]) if run["output_json"] else None
    return dict({"variant": {"original": True}, "run_id": run["id"],
                 "status": run["status"], "result": result}, **_summary(steps, result, expect))

class _MuteWorkers:
    """Stands in for sys.stdout during a sweep: the agent's prints from worker threads are dropped,
    while the thread running the sweep can still report progress."""
    def __init__(self, real):
        self._real, self._owner = real, threading.get_ident()
    def write(self, text):
        return self._real.write(text) if threading.get_ident() == self._owner else len(text)
    def __getattr__(self, name):
        return getattr(self._real, name)

def sweep(run, step, variants, repeat=1, expect=None, on_result=None, parallel=4):
    """Fork `run` at `step` once per variant, `repeat` times each, up to `parallel` at a time.

    Results come back in variant order; `on_result` is called as each run finishes.
    """
    _check_variants(run, step, variants)

    def one(variant):
        ctx, status, result = {}, "error", None
        try:
            _, result = fork(run, step, ctx=ctx, **variant)
            status = "ok"
        except Exception as e:
            result = repr(e)
        run_id = ctx.get("run_id")
        live = [s for s in (store.get_steps(run_id) if run_id else []) if not s["cached"]]
        return dict({"variant": variant, "run_id": run_id, "status": status,
                     "result": result}, **_summary(live, result, expect))

    real_stdout = sys.stdout
    sys.stdout = _MuteWorkers(real_stdout)
    try:
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            futures = [pool.submit(one, v) for v in variants for _ in range(repeat)]
            for f in as_completed(futures):
                if on_result:
                    on_result(f.result())
        return [f.result() for f in futures]
    finally:
        sys.stdout = real_stdout
