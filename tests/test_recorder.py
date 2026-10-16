import sqlite3
import agentfork
from agentfork import store

def test_records_tool_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFORK_DIR", str(tmp_path))

    @agentfork.tool
    def add(a, b):
        return a + b

    @agentfork.trace
    def agent():
        return add(2, 3) + add(1, 1)

    assert agent() == 7
    conn = sqlite3.connect(store.db_path())
    rows = conn.execute("SELECT seq, type, name, output_json FROM steps ORDER BY seq").fetchall()
    assert rows == [(1, "tool", "add", "5"), (2, "tool", "add", "2")]
