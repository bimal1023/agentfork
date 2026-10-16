import os, sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, name TEXT, started_at REAL, ended_at REAL,
  status TEXT, input_json TEXT, output_json TEXT,
  parent_run_id TEXT, fork_step INTEGER
);
CREATE TABLE IF NOT EXISTS steps (
  id TEXT PRIMARY KEY, run_id TEXT, parent_id TEXT, seq INTEGER,
  type TEXT, name TEXT, input_json TEXT, output_json TEXT,
  cache_key TEXT, tokens_in INTEGER, tokens_out INTEGER,
  latency_ms REAL, error TEXT, started_at REAL
);
CREATE INDEX IF NOT EXISTS idx_steps_run ON steps(run_id, seq);
"""

def db_path():
    return Path(os.environ.get("AGENTREWIND_DIR", ".agentrewind")) / "traces.db"

def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn

def _exec(sql, params):
    with closing(connect()) as conn, conn:
        conn.execute(sql, params)

def insert(table, row):
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    _exec(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))

def update_run(run_id, **fields):
    sets = ", ".join(f"{k}=?" for k in fields)
    _exec(f"UPDATE runs SET {sets} WHERE id=?", [*fields.values(), run_id])
