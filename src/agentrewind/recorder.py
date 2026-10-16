import contextvars, functools, hashlib, inspect, json, time, uuid, warnings
from . import store

_run_id = contextvars.ContextVar("run_id", default=None)
_parent_step = contextvars.ContextVar("parent_step", default=None)
_seq = contextvars.ContextVar("seq", default=None)
_replay = contextvars.ContextVar("replay", default=None)

DECODERS = {}
last_run_id = None

def to_jsonable(obj):
    if hasattr(obj, "model_dump"):
        return to_jsonable(obj.model_dump())
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return repr(obj)

def dumps(obj):
    return json.dumps(to_jsonable(obj), sort_keys=True)

def make_cache_key(step_type, name, input_json):
    return hashlib.sha256(f"{step_type}|{name}|{input_json}".encode()).hexdigest()

def _apply_override(step_type, kwargs, override):
    kwargs = dict(kwargs)
    if step_type == "llm":
        if override.get("model"):
            kwargs["model"] = override["model"]
        if override.get("system"):
            msgs = [m for m in kwargs.get("messages", [])
                    if not (isinstance(m, dict) and m.get("role") == "system")]
            kwargs["messages"] = [{"role": "system", "content": override["system"]}] + msgs
    return kwargs

def _last_descendant_seq(steps, step):
    ids, last = {step["id"]}, step["seq"]
    for s in sorted(steps.values(), key=lambda s: s["seq"]):
        if s["seq"] > step["seq"] and s["parent_id"] in ids:
            ids.add(s["id"])
            last = s["seq"]
    return last

def record_step(step_type, name, fn, args, kwargs):
    run_id = _run_id.get()
    if run_id is None:
        return fn(*args, **kwargs)
    counter = _seq.get()
    counter[0] += 1
    seq = counter[0]
    replay = _replay.get()
    cached_step, use_forced = None, False
    if replay and seq < replay["fork_step"]:
        cached_step = replay["steps"].get(seq)
    elif replay and seq == replay["fork_step"]:
        if "output" in replay["override"]:
            use_forced = True
        else:
            kwargs = _apply_override(step_type, kwargs, replay["override"])
    input_json = dumps({"args": args, "kwargs": kwargs})
    key = make_cache_key(step_type, name, input_json)
    step_id, parent = uuid.uuid4().hex, _parent_step.get()
    token = _parent_step.set(step_id)
    started = time.time()
    output, error, cached = None, None, 0
    try:
        if cached_step is not None:
            if cached_step["cache_key"] != key:
                warnings.warn(f"agentrewind: step {seq} inputs differ from the original run; reusing its cached output")
            decode = DECODERS.get(step_type, lambda x: x)
            output = decode(json.loads(cached_step["output_json"]))
            counter[0] = _last_descendant_seq(replay["steps"], cached_step)
            cached = 1
        elif use_forced:
            output = replay["override"]["output"]
        else:
            output = fn(*args, **kwargs)
        return output
    except Exception as e:
        error = repr(e)
        raise
    finally:
        _parent_step.reset(token)
        usage = None if cached else getattr(output, "usage", None)
        store.insert("steps", {
            "id": step_id, "run_id": run_id, "parent_id": parent, "seq": seq,
            "type": step_type, "name": name,
            "input_json": input_json, "output_json": dumps(output), "cache_key": key,
            "tokens_in": getattr(usage, "prompt_tokens", None),
            "tokens_out": getattr(usage, "completion_tokens", None),
            "latency_ms": (time.time() - started) * 1000,
            "error": error, "started_at": started, "cached": cached,
        })

def trace(fn=None, *, name=None):
    def deco(f):
        try:
            entry_file = inspect.getsourcefile(f)
        except TypeError:
            entry_file = None

        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            global last_run_id
            if _run_id.get() is not None:
                return f(*args, **kwargs)
            run_id = uuid.uuid4().hex
            replay = _replay.get() or {}
            store.insert("runs", {
                "id": run_id, "name": name or f.__name__, "started_at": time.time(),
                "status": "running", "input_json": dumps({"args": args, "kwargs": kwargs}),
                "entry_file": entry_file, "entry_name": f.__qualname__,
                "parent_run_id": replay.get("parent_run_id"), "fork_step": replay.get("fork_step"),
            })
            last_run_id = run_id
            t_run, t_seq, t_parent = _run_id.set(run_id), _seq.set([0]), _parent_step.set(None)
            status, output = "error", None
            try:
                output = f(*args, **kwargs)
                status = "ok"
                return output
            finally:
                _run_id.reset(t_run); _seq.reset(t_seq); _parent_step.reset(t_parent)
                store.update_run(run_id, ended_at=time.time(), status=status, output_json=dumps(output))
                print(f"[agentrewind] saved run {run_id[:8]} ({status})")
        return wrapper
    return deco(fn) if fn else deco

def tool(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return record_step("tool", fn.__name__, fn, args, kwargs)
    return wrapper

def wrap_openai(client):
    from openai.types.chat import ChatCompletion
    DECODERS["llm"] = ChatCompletion.model_validate
    original = client.chat.completions.create
    def create(*args, **kwargs):
        return record_step("llm", kwargs.get("model", "llm"), original, args, kwargs)
    client.chat.completions.create = create
    return client
