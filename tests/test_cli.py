from typer.testing import CliRunner
import agentfork
from agentfork import store
from agentfork.cli import app

def test_list_and_show(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFORK_DIR", str(tmp_path))

    @agentfork.tool
    def add(a, b):
        return a + b

    @agentfork.trace
    def agent():
        return add(2, 3)

    agent()
    run_id = store.list_runs(1)[0]["id"]
    runner = CliRunner()
    listed = runner.invoke(app, ["list"])
    assert listed.exit_code == 0 and run_id[:8] in listed.output
    shown = runner.invoke(app, ["show", run_id[:8]])
    assert shown.exit_code == 0 and "add" in shown.output
