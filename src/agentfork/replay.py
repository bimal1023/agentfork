import importlib.util, json, sys
from pathlib import Path
from . import recorder, store

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

def fork(run, step, output=None, model=None, system=None):
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
    token = recorder._replay.set({"parent_run_id": run["id"], "fork_step": step,
                                  "steps": steps, "override": override})
    try:
        result = fn(*inputs["args"], **inputs["kwargs"])
    finally:
        recorder._replay.reset(token)
    return recorder.last_run_id, result

def check(fixture, root="."):
    run = fixture["run"]
    steps = {s["seq"]: s for s in fixture["steps"]}
    fn = load_entry(dict(run, entry_file=str(Path(root) / run["entry_file"])))
    inputs = json.loads(run["input_json"])
    token = recorder._replay.set({"parent_run_id": None, "fork_step": float("inf"),
                                  "steps": steps, "override": {}, "strict": True})
    try:
        result = fn(*inputs["args"], **inputs["kwargs"])
    finally:
        recorder._replay.reset(token)
    if recorder.last_run_seq != max(steps, default=0):
        raise recorder.ReplayMismatch(
            f"the recorded run had {max(steps, default=0)} steps but the replay made {recorder.last_run_seq}")
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
        "passed": None if expect is None else expect.lower() in str(result).lower(),
    }

def baseline(run, step, expect=None):
    steps = [s for s in store.get_steps(run["id"]) if s["seq"] >= step]
    result = json.loads(run["output_json"]) if run["output_json"] else None
    return dict({"variant": {"original": True}, "run_id": run["id"],
                 "status": run["status"], "result": result}, **_summary(steps, result, expect))

def sweep(run, step, variants, repeat=1, expect=None, on_result=None):
    import contextlib, io
    _check_variants(run, step, variants)
    results = []
    for variant in variants:
        for _ in range(repeat):
            before = recorder.last_run_id
            status, run_id, result = "error", None, None
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    run_id, result = fork(run, step, **variant)
                status = "ok"
            except Exception as e:
                result = repr(e)
                if recorder.last_run_id != before:
                    run_id = recorder.last_run_id
            live = [s for s in (store.get_steps(run_id) if run_id else []) if not s["cached"]]
            record = dict({"variant": variant, "run_id": run_id, "status": status,
                           "result": result}, **_summary(live, result, expect))
            results.append(record)
            if on_result:
                on_result(record)
    return results
