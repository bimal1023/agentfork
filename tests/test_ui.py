from fastapi.testclient import TestClient

from agentfork import replay, store
from agentfork.server import app

AGENT = '''
import agentfork

@agentfork.tool
def lookup(city):
    return "cloudy"

@agentfork.trace
def agent(city):
    return f"{city} is {lookup(city)}"
'''

def test_ui_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFORK_DIR", str(tmp_path / "db"))
    path = tmp_path / "toy_agent.py"
    path.write_text(AGENT)
    replay.load_entry({"entry_file": str(path), "entry_name": "agent"})("paris")
    run_id = store.list_runs(1)[0]["id"]
    client = TestClient(app)

    assert "agentfork" in client.get("/").text
    assert client.get("/api/runs").json()[0]["id"] == run_id
    detail = client.get(f"/api/runs/{run_id[:8]}").json()
    assert detail["steps"][0]["summary"].endswith("-> cloudy")
    assert detail["run"]["input_preview"] == "paris"
    assert detail["run"]["output_preview"] == "paris is cloudy"

    forked = client.post("/api/fork", json={"run_id": run_id, "step": 1, "output": "sunny"}).json()
    assert client.get(f"/api/runs/{forked['run_id']}").json()["output"] == "paris is sunny"

    sweep = client.post("/api/sweep", json={"run_id": run_id, "step": 1, "kind": "output",
                                            "values": ["sunny", "rainy"], "repeat": 2, "expect": "sunny"}).json()
    assert [g["passed"] for g in sweep["groups"]] == [0, 2, 0]
