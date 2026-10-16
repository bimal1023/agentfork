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
