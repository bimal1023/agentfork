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
