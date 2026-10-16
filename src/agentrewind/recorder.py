import contextvars, functools, hashlib, json, time, uuid
from . import store

_run_id = contextvars.ContextVar("run_id", default=None)
_parent_step = contextvars.ContextVar("parent_step", default=None)
_seq = contextvars.ContextVar("seq", default=None)

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
    raw = f"{step_type}|{name}|{input_json}"
    return hashlib.sha256(raw.encode()).hexdigest()

def record_step(step_type, name, inputs, call):
    run_id = _run_id.get()
    if run_id is None:
        return call()
    input_json = dumps(inputs)
    counter = _seq.get()
    counter[0] += 1
    step_id, seq, parent = uuid.uuid4().hex, counter[0], _parent_step.get()
    token = _parent_step.set(step_id)
    started = time.time()
    output, error = None, None
    try:
        output = call()
        return output
    except Exception as e:
        error = repr(e)
        raise
    finally:
        _parent_step.reset(token)
        usage = getattr(output, "usage", None)
        store.insert("steps", {
            "id": step_id, "run_id": run_id, "parent_id": parent, "seq": seq,
            "type": step_type, "name": name,
            "input_json": input_json, "output_json": dumps(output),
            "cache_key": make_cache_key(step_type, name, input_json),
            "tokens_in": getattr(usage, "prompt_tokens", None),
            "tokens_out": getattr(usage, "completion_tokens", None),
            "latency_ms": (time.time() - started) * 1000,
            "error": error, "started_at": started,
        })

def trace(fn=None, *, name=None):
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if _run_id.get() is not None:
                return f(*args, **kwargs)
            run_id = uuid.uuid4().hex
            store.insert("runs", {
                "id": run_id, "name": name or f.__name__, "started_at": time.time(),
                "status": "running", "input_json": dumps({"args": args, "kwargs": kwargs}),
            })
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
        return record_step("tool", fn.__name__, {"args": args, "kwargs": kwargs},
                           lambda: fn(*args, **kwargs))
    return wrapper

def wrap_openai(client):
    original = client.chat.completions.create
    def create(*args, **kwargs):
        return record_step("llm", kwargs.get("model", "llm"), kwargs,
                           lambda: original(*args, **kwargs))
    client.chat.completions.create = create
    return client
