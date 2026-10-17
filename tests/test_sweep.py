from typer.testing import CliRunner

from agentfork import replay, store
from agentfork.cli import app

AGENT = '''
import agentfork

@agentfork.tool
def lookup(city):
    return "cloudy"

@agentfork.trace
def agent(city):
    return f"{city} is {lookup(city)}"
'''

def _record(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFORK_DIR", str(tmp_path / "db"))
    path = tmp_path / "toy_agent.py"
    path.write_text(AGENT)
    replay.load_entry({"entry_file": str(path), "entry_name": "agent"})("paris")
    return store.list_runs(1)[0]

def test_sweep_tool_outputs(tmp_path, monkeypatch):
    run = _record(tmp_path, monkeypatch)
    results = replay.sweep(run, 1, [{"output": "sunny"}, {"output": "rainy"}], repeat=2, expect="sunny")
    assert [r["passed"] for r in results] == [True, True, False, False]
    assert all(r["status"] == "ok" and r["run_id"] for r in results)
    assert replay.baseline(run, 1, expect="sunny")["passed"] is False

def test_sweep_cli(tmp_path, monkeypatch):
    run = _record(tmp_path, monkeypatch)
    result = CliRunner().invoke(app, ["sweep", run["id"][:8], "--step", "1",
                                      "--output", "sunny", "--output", "rainy", "--expect", "sunny"])
    assert result.exit_code == 0, result.output
    assert "2 variants" in result.output

SLOW_AGENT = '''
import time
import agentfork

@agentfork.tool
def lookup(city):
    return "cloudy"

@agentfork.trace
def agent(city):
    weather = lookup(city)
    print("the agent prints this")
    time.sleep(0.3)
    return f"{city} is {weather}"
'''

def test_sweep_runs_in_parallel(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTFORK_DIR", str(tmp_path / "db"))
    path = tmp_path / "slow_agent.py"
    path.write_text(SLOW_AGENT)
    replay.load_entry({"entry_file": str(path), "entry_name": "agent"})("paris")
    run = store.list_runs(1)[0]
    capsys.readouterr()

    import time
    started = time.time()
    results = replay.sweep(run, 1, [{"output": w} for w in ["sunny", "rainy", "windy", "foggy"]],
                           repeat=2, parallel=8, on_result=lambda r: print("done", r["result"]))
    assert time.time() - started < 1.5          # one at a time would take 8 x 0.3s
    assert [r["result"] for r in results] == [f"paris is {w}" for w in ["sunny", "rainy", "windy", "foggy"] for _ in range(2)]
    assert len({r["run_id"] for r in results}) == 8
    for r in results:
        assert store.find_runs(r["run_id"])[0]["output_json"] == f'"{r["result"]}"'
    out = capsys.readouterr().out
    assert out.count("done paris is") == 8 and "the agent prints this" not in out
