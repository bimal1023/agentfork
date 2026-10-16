import pytest
from typer.testing import CliRunner

from agentfork import replay, store
from agentfork.cli import app
from agentfork.recorder import ReplayMismatch

AGENT = '''
import agentfork

@agentfork.tool
def lookup(city):
    return {"kathmandu": "sunny", "paris": "cloudy"}.get(city, "unknown")

@agentfork.trace
def agent(city):
    return f"{city}: {lookup(city)}, paris: {lookup('paris')}"
'''

def _record(tmp_path, monkeypatch, source):
    monkeypatch.setenv("AGENTFORK_DIR", str(tmp_path / "db"))
    path = tmp_path / "toy_agent.py"
    path.write_text(source)
    replay.load_entry({"entry_file": str(path), "entry_name": "agent"})("kathmandu")
    run = store.list_runs(1)[0]
    return path, {"run": run, "steps": store.get_steps(run["id"])}

def test_check_passes_then_catches_changes(tmp_path, monkeypatch):
    path, fixture = _record(tmp_path, monkeypatch, AGENT)
    assert replay.check(fixture) == "kathmandu: sunny, paris: cloudy"
    path.write_text(AGENT.replace("lookup('paris')", "lookup('london')"))
    with pytest.raises(ReplayMismatch, match="step 2"):
        replay.check(fixture)

def test_save_test_writes_files(tmp_path, monkeypatch):
    _, fixture = _record(tmp_path, monkeypatch, AGENT)
    short = fixture["run"]["id"][:8]
    out = tmp_path / "generated"
    result = CliRunner().invoke(app, ["save-test", short, "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / f"run_{short}.json").exists()
    assert (out / f"test_run_{short}.py").exists()
