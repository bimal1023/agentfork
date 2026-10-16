import json
from datetime import datetime
from typing import List, Optional

import typer
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich.tree import Tree

from . import replay, store

app = typer.Typer(help="agentfork: record, inspect and replay LLM agent runs.")
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
        if "choices" in out:
            msg = (out.get("choices") or [{}])[0].get("message") or {}
            calls = msg.get("tool_calls") or []
            if calls:
                return "calls " + ", ".join(c["function"]["name"] for c in calls)
            return (msg.get("content") or "")[:120]
        blocks = [b for b in (out.get("content") or []) if isinstance(b, dict)]
        tools = [b.get("name") for b in blocks if b.get("type") == "tool_use"]
        if tools:
            return "calls " + ", ".join(tools)
        return " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")[:120]
    return str(out)[:120]

def _label(s):
    tokens = f" {s['tokens_in']}->{s['tokens_out']} tok" if s["tokens_in"] is not None else ""
    kind = "cyan" if s["type"] == "llm" else "magenta"
    cached = " [green](cached)[/green]" if s.get("cached") else ""
    return (f"[dim]#{s['seq']}[/dim] [{kind}]{s['type']}[/{kind}] [bold]{s['name']}[/bold] "
            f"[dim]{s['latency_ms']:.0f}ms{tokens}[/dim]{cached}  {_summarize(s)}")

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
    for col in ["id", "name", "status", "steps", "tokens", "duration", "started", "fork of"]:
        table.add_column(col)
    for r in store.list_runs(limit):
        color = STATUS_COLOR.get(r["status"], "white")
        fork = f"{r['parent_run_id'][:8]}@{r['fork_step']}" if r.get("parent_run_id") else ""
        table.add_row(r["id"][:8], r["name"], f"[{color}]{r['status']}[/{color}]",
                      str(r["n_steps"]), str(r["tokens"]), _duration(r), _fmt_time(r["started_at"]), fork)
    console.print(table)

@app.command()
def show(run_id: str = typer.Argument(..., help="Run id or its first few characters."),
         full: bool = typer.Option(False, "--full", help="Show full inputs and outputs.")):
    """Show one run as a step tree."""
    run = _resolve(run_id)
    color = STATUS_COLOR.get(run["status"], "white")
    fork = (f" [dim]fork of {run['parent_run_id'][:8]} at step {run['fork_step']}[/dim]"
            if run.get("parent_run_id") else "")
    root = Tree(f"[bold]{run['name']}[/bold] {run['id'][:8]} "
                f"[{color}]{run['status']}[/{color}] {_duration(run)}{fork}")
    nodes = {}
    for s in store.get_steps(run["id"]):
        node = nodes.get(s["parent_id"], root).add(_label(s))
        if full:
            node.add(Syntax(json.dumps(_load(s["input_json"]), indent=2), "json", word_wrap=True))
            node.add(Syntax(json.dumps(_load(s["output_json"]), indent=2), "json", word_wrap=True))
        nodes[s["id"]] = node
    console.print(root)
    console.print(f"[bold]Final output:[/bold] {_load(run['output_json'])}")

@app.command()
def fork(run_id: str = typer.Argument(..., help="Run to fork."),
         step: int = typer.Option(..., "--step", help="Step number to change (see `show`)."),
         output: Optional[str] = typer.Option(None, "--output", help="Fake result for a tool step."),
         model: Optional[str] = typer.Option(None, "--model", help="Different model for an LLM step."),
         system: Optional[str] = typer.Option(None, "--system", help="System prompt for an LLM step.")):
    """Re-run a past run from one step with one change; earlier steps come from the cache."""
    if output is None and model is None and system is None:
        console.print("[red]Give one change: --output, --model or --system[/red]")
        raise typer.Exit(1)
    run = _resolve(run_id)
    try:
        new_id, _ = replay.fork(run, step, output=output, model=model, system=system)
    except Exception as e:
        console.print(f"[red]Fork failed: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Forked {run['id'][:8]} at step {step} -> new run {new_id[:8]}[/green]")
    show(new_id, full=False)
    console.print(f"[dim]Compare: agentfork diff {run['id'][:8]} {new_id[:8]}[/dim]")

@app.command()
def diff(run_a: str = typer.Argument(..., help="First run."),
         run_b: str = typer.Argument(..., help="Second run.")):
    """Compare two runs step by step."""
    a, b = _resolve(run_a), _resolve(run_b)
    sa = {s["seq"]: s for s in store.get_steps(a["id"])}
    sb = {s["seq"]: s for s in store.get_steps(b["id"])}
    table = Table(title=f"{a['id'][:8]} vs {b['id'][:8]}", show_lines=True)
    table.add_column("#")
    table.add_column(a["id"][:8])
    table.add_column(b["id"][:8])
    for seq in sorted(set(sa) | set(sb)):
        left = _label(sa[seq]) if seq in sa else "[dim]-[/dim]"
        right = _label(sb[seq]) if seq in sb else "[dim]-[/dim]"
        same = seq in sa and seq in sb and _summarize(sa[seq]) == _summarize(sb[seq])
        table.add_row(str(seq) if same else f"[yellow]{seq} *[/yellow]", left, right)
    console.print(table)
    console.print(f"[bold]{a['id'][:8]} output:[/bold] {_load(a['output_json'])}")
    console.print(f"[bold]{b['id'][:8]} output:[/bold] {_load(b['output_json'])}")

TEST_TEMPLATE = '''# Generated by `agentfork save-test` from run {run_id}.
# Replays the recorded run entirely from cache: no API calls, no cost.
# If you change prompts, tools or agent logic on purpose, record a new run
# and run `agentfork save-test <new-run-id>` again.
import json
from pathlib import Path

from agentfork import replay

FIXTURE = Path(__file__).with_name("run_{short}.json")
ROOT = Path(__file__).resolve().parents[{depth}]


def test_run_{short}_replays(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFORK_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-agentfork-replay")
    replay.check(json.loads(FIXTURE.read_text()), ROOT)
'''

@app.command("save-test")
def save_test(run_id: str = typer.Argument(..., help="Run to turn into a test."),
              out: str = typer.Option("tests/agentfork", "--out", help="Folder for the generated test.")):
    """Save a run as a pytest regression test that replays it from cache."""
    import os
    from pathlib import Path
    run = _resolve(run_id)
    if not run.get("entry_file"):
        console.print("[red]This run has no saved entry point; run your agent again and save the new run.[/red]")
        raise typer.Exit(1)
    if run.get("parent_run_id"):
        console.print("[yellow]This run is a fork, and its change isn't in your code yet. "
                      "Apply the fix, run your agent again, and save that run.[/yellow]")
        raise typer.Exit(1)
    cwd = Path.cwd()
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    short = run["id"][:8]
    fixture = {"run": dict(run, entry_file=os.path.relpath(run["entry_file"], cwd)),
               "steps": store.get_steps(run["id"])}
    fixture_path = out_dir / f"run_{short}.json"
    test_path = out_dir / f"test_run_{short}.py"
    fixture_path.write_text(json.dumps(fixture, indent=2))
    depth = len(Path(os.path.relpath(out_dir.resolve(), cwd)).parts)
    test_path.write_text(TEST_TEMPLATE.format(run_id=run["id"], short=short, depth=depth))
    console.print(f"[green]Saved {test_path} and {fixture_path.name}[/green]")
    console.print(f"[dim]Run it with: pytest {test_path}[/dim]")


def _variant_label(v):
    if v.get("original"):
        return "original"
    key, value = next(iter(v.items()))
    value = str(value)
    return f"{key}={value if len(value) <= 40 else value[:37] + '...'}"

@app.command()
def sweep(run_id: str = typer.Argument(..., help="Run to sweep."),
          step: int = typer.Option(..., "--step", help="Step to vary (see `show`)."),
          model: Optional[str] = typer.Option(None, "--model", help="Comma-separated models to try."),
          system: Optional[List[str]] = typer.Option(None, "--system", help="System prompt to try; repeat for more."),
          output: Optional[List[str]] = typer.Option(None, "--output", help="Tool result to try; repeat for more."),
          repeat: int = typer.Option(1, "--repeat", help="Runs per variant (LLMs vary run to run)."),
          expect: Optional[str] = typer.Option(None, "--expect", help="Text a good final output contains.")):
    """Fork one step across several models, prompts or tool results and compare outcomes."""
    variants = [{"model": m.strip()} for m in (model or "").split(",") if m.strip()]
    variants += [{"system": s} for s in (system or [])]
    variants += [{"output": o} for o in (output or [])]
    if not variants:
        console.print("[red]Give at least one variant: --model, --system or --output[/red]")
        raise typer.Exit(1)
    run = _resolve(run_id)
    console.print(f"[bold]Sweeping step {step} of {run['id'][:8]}: "
                  f"{len(variants)} variants x {repeat} = {len(variants) * repeat} runs[/bold]")

    def progress(r):
        mark = "[green]ok[/green]" if r["status"] == "ok" else "[red]error[/red]"
        verdict = "" if r["passed"] is None else (" [green]pass[/green]" if r["passed"] else " [red]fail[/red]")
        console.print(f"  {mark}{verdict} {_variant_label(r['variant'])} [dim]{r['tokens']} tok[/dim]")

    try:
        results = replay.sweep(run, step, variants, repeat=repeat, expect=expect, on_result=progress)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    groups = {}
    for r in [replay.baseline(run, step, expect)] + results:
        groups.setdefault(_variant_label(r["variant"]), []).append(r)
    table = Table(title=f"Sweep of step {step} ({run['id'][:8]})", show_lines=True)
    cols = ["variant", "runs", "ok"] + (["pass"] if expect else []) + ["avg tokens", "avg time", "sample output", "run ids"]
    for col in cols:
        if col == "sample output":
            table.add_column(col, max_width=40, overflow="ellipsis", no_wrap=True)
        else:
            table.add_column(col, no_wrap=True)
    for label, rs in groups.items():
        n = len(rs)
        row = [label, str(n), f"{sum(r['status'] == 'ok' for r in rs)}/{n}"]
        if expect:
            passed = sum(bool(r["passed"]) for r in rs)
            color = "green" if passed == n else ("yellow" if passed else "red")
            row.append(f"[{color}]{passed}/{n}[/{color}]")
        row += [f"{sum(r['tokens'] for r in rs) / n:.0f}",
                f"{sum(r['latency_ms'] for r in rs) / n / 1000:.1f}s",
                str(rs[0]["result"])[:80],
                ", ".join((r["run_id"] or "-")[:8] for r in rs)]
        table.add_row(*row)
    console.print(table)
