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
    spec = importlib.util.spec_from_file_location("agentrewind_entry", path)
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
