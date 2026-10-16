from agentrewind import replay, store

AGENT = '''
import agentrewind

@agentrewind.tool
def lookup(city):
    return {"kathmandu": "sunny", "paris": "cloudy"}.get(city, "unknown")

@agentrewind.trace
def agent(city):
    return f"{city}: {lookup(city)}, paris: {lookup('paris')}"
'''

def test_fork_reuses_cache_and_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTREWIND_DIR", str(tmp_path / "db"))
    path = tmp_path / "toy_agent.py"
    path.write_text(AGENT)
    agent = replay.load_entry({"entry_file": str(path), "entry_name": "agent"})
    assert agent("kathmandu") == "kathmandu: sunny, paris: cloudy"

    original = store.list_runs(1)[0]
    new_id, result = replay.fork(original, step=2, output="rainy")
    assert result == "kathmandu: sunny, paris: rainy"

    new_run = store.find_runs(new_id)[0]
    assert new_run["parent_run_id"] == original["id"] and new_run["fork_step"] == 2
    steps = store.get_steps(new_id)
    assert [(s["seq"], s["cached"]) for s in steps] == [(1, 1), (2, 0)]
