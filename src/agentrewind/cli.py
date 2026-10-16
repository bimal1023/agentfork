import json
from datetime import datetime

import typer
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich.tree import Tree

from . import store

app = typer.Typer(help="agentrewind: record, inspect and replay LLM agent runs.")
console = Console()
STATUS_COLOR = {"ok": "green", "error": "red", "running": "yellow"}

def _load(text):
    return json.loads(text) if text else None

def _fmt_time(ts):
    return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M:%S") if ts else "-"

def _duration(run):
    if not run.get("ended_at"):
        return "-"
    return f"{run['ended_at'] - run['started_at']:.1f}s"

def _summarize(step):
    inp, out = _load(step["input_json"]), _load(step["output_json"])
    if step["error"]:
        return f"[red]{step['error']}[/red]"
    if step["type"] == "tool" and isinstance(inp, dict):
        args = inp.get("kwargs") or inp.get("args")
        return f"{args} -> {out}"
    if step["type"] == "llm" and isinstance(out, dict):
        msg = (out.get("choices") or [{}])[0].get("message") or {}
        calls = msg.get("tool_calls") or []
        if calls:
            return "calls " + ", ".join(c["function"]["name"] for c in calls)
        return (msg.get("content") or "")[:120]
    return str(out)[:120]

def _resolve(prefix):
    matches = store.find_runs(prefix)
    if not matches:
        console.print(f"[red]No run found starting with '{prefix}'[/red]")
        raise typer.Exit(1)
    if len(matches) > 1:
        console.print(f"[yellow]'{prefix}' matches {len(matches)} runs; use more characters[/yellow]")
        raise typer.Exit(1)
    return matches[0]

@app.command("list")
def list_runs(limit: int = typer.Option(10, help="How many recent runs to show.")):
    """List recent runs."""
    table = Table(title="Recent runs")
    for col in ["id", "name", "status", "steps", "tokens", "duration", "started"]:
        table.add_column(col)
    for r in store.list_runs(limit):
        color = STATUS_COLOR.get(r["status"], "white")
        table.add_row(r["id"][:8], r["name"], f"[{color}]{r['status']}[/{color}]",
                      str(r["n_steps"]), str(r["tokens"]), _duration(r), _fmt_time(r["started_at"]))
    console.print(table)

@app.command()
def show(run_id: str = typer.Argument(..., help="Run id or its first few characters."),
         full: bool = typer.Option(False, "--full", help="Show full inputs and outputs.")):
    """Show one run as a step tree."""
    run = _resolve(run_id)
    color = STATUS_COLOR.get(run["status"], "white")
    root = Tree(f"[bold]{run['name']}[/bold] {run['id'][:8]} "
                f"[{color}]{run['status']}[/{color}] {_duration(run)}")
    nodes = {}
    for s in store.get_steps(run["id"]):
        parent = nodes.get(s["parent_id"], root)
        tokens = f" {s['tokens_in']}->{s['tokens_out']} tok" if s["tokens_in"] is not None else ""
        kind = "cyan" if s["type"] == "llm" else "magenta"
        label = (f"[dim]#{s['seq']}[/dim] [{kind}]{s['type']}[/{kind}] [bold]{s['name']}[/bold] "
                 f"[dim]{s['latency_ms']:.0f}ms{tokens}[/dim]  {_summarize(s)}")
        node = parent.add(label)
        if full:
            node.add(Syntax(json.dumps(_load(s["input_json"]), indent=2), "json", word_wrap=True))
            node.add(Syntax(json.dumps(_load(s["output_json"]), indent=2), "json", word_wrap=True))
        nodes[s["id"]] = node
    console.print(root)
    console.print(f"[bold]Final output:[/bold] {_load(run['output_json'])}")
