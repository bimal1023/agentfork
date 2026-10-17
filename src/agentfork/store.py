import os, sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, name TEXT, started_at REAL, ended_at REAL,
  status TEXT, input_json TEXT, output_json TEXT,
  parent_run_id TEXT, fork_step INTEGER, entry_file TEXT, entry_name TEXT
);
CREATE TABLE IF NOT EXISTS steps (
  id TEXT PRIMARY KEY, run_id TEXT, parent_id TEXT, seq INTEGER,
  type TEXT, name TEXT, input_json TEXT, output_json TEXT,
  cache_key TEXT, tokens_in INTEGER, tokens_out INTEGER,
  latency_ms REAL, error TEXT, started_at REAL, cached INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_steps_run ON steps(run_id, seq);
"""

MIGRATIONS = [
    "ALTER TABLE runs ADD COLUMN entry_file TEXT",
    "ALTER TABLE runs ADD COLUMN entry_name TEXT",
    "ALTER TABLE steps ADD COLUMN cached INTEGER DEFAULT 0",
]

def db_path():
    return Path(os.environ.get("AGENTFORK_DIR", ".agentfork")) / "traces.db"

def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for sql in MIGRATIONS:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass
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

def query(sql, params=()):
    with closing(connect()) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]

def list_runs(limit=10):
    return query("""
        SELECT r.*, COUNT(s.id) AS n_steps,
               COALESCE(SUM(s.tokens_in), 0) + COALESCE(SUM(s.tokens_out), 0) AS tokens
        FROM runs r LEFT JOIN steps s ON s.run_id = r.id
        GROUP BY r.id ORDER BY r.started_at DESC LIMIT ?""", (limit,))

def find_runs(prefix):
    return query("SELECT * FROM runs WHERE id LIKE ? ORDER BY started_at DESC", (prefix + "%",))

def get_steps(run_id):
    return query("SELECT * FROM steps WHERE run_id = ? ORDER BY seq", (run_id,))

def tokens_for(cache_key):
    """Token counts from the run that made this call live; cached copies don't record them."""
    rows = query("SELECT tokens_in, tokens_out FROM steps WHERE cache_key = ? AND tokens_in IS NOT NULL LIMIT 1",
                 (cache_key,))
    return (rows[0]["tokens_in"], rows[0]["tokens_out"]) if rows else (None, None)
