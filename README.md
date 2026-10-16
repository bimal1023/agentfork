# agentrewind

[![tests](https://github.com/bimal1023/agentrewind/actions/workflows/tests.yml/badge.svg)](https://github.com/bimal1023/agentrewind/actions/workflows/tests.yml)

**Rewind, fork and replay your LLM agent runs, then turn them into regression tests.**

Debugging agents is painful: a bug shows up at step 7, and every attempt to fix it means re-running (and paying for) steps 1 to 6. agentrewind records every LLM and tool call to a local SQLite file, lets you **fork any run from any step** with one change while earlier steps replay instantly from cache, and turns runs into **pytest snapshot tests** that run in CI with no API key.

Everything runs locally. No account, no server, no data leaves your machine.

## Quickstart

```bash
pip install -e .   # PyPI release coming soon
```

Add three things to your agent:

```python
from openai import OpenAI
from agentrewind import trace, tool, wrap_openai

client = wrap_openai(OpenAI())      # records every LLM call

@tool                               # records every tool call
def get_weather(city): ...

@trace                              # one run = one call of your agent
def run_agent(question): ...
```

Run your agent as usual. Each run is saved to `.agentrewind/traces.db`.

## Commands

| Command | What it does |
| --- | --- |
| `agentrewind list` | Recent runs with steps, tokens, duration and fork lineage |
| `agentrewind show <id> [--full]` | A run as a step tree, with optional full JSON |
| `agentrewind fork <id> --step N --output "..."` | Replay with a fake result for tool step N |
| `agentrewind fork <id> --step N --model ...` | Replay with a different model at LLM step N |
| `agentrewind fork <id> --step N --system "..."` | Replay with a new system prompt at LLM step N |
| `agentrewind diff <a> <b>` | Compare two runs step by step |
| `agentrewind save-test <id>` | Save a run as a pytest test that replays from cache |

## How it works

1. **Record.** `@trace`, `@tool` and `wrap_openai` capture each step's inputs, outputs, tokens and latency, plus a hash of its inputs.
2. **Fork.** `fork` re-imports your agent and re-runs it. Steps before N come straight from the cache (free and identical), step N gets your change, and everything after runs live.
3. **Test.** `save-test` writes a JSON snapshot and a pytest file. The test replays every step from cache and fails with a diff if any step's inputs, the number of steps, or the final output changes.

## Example

```text
$ agentrewind fork f2628b01 --step 4 --system "Answer like a pirate in one sentence."
run_agent 94bfdf0a ok 0.8s fork of f2628b01 at step 4
├── #1 llm gpt-4o-mini 3ms (cached)  calls get_weather, calculator
├── #2 tool get_weather 0ms (cached)  {'city': 'Kathmandu'} -> 22C, sunny
├── #3 tool calculator 0ms (cached)  {'expression': '23*(4+5)'} -> 207
└── #4 llm gpt-4o-mini 786ms 165->42 tok  Arrr, in Kathmandu it be a pleasant 22°C...
```

## Real bug walkthrough: the $4,999 refund

A support agent looks up an order and refunds it ([examples/refund_agent.py](examples/refund_agent.py)). The order API returns `"amount": 4999, "currency": "USD"`. The amount is in **cents**, but nothing says so, and the agent refunds **$4,999.00** for a $49.99 laptop.

**1. Find it.** `agentrewind show 5a75d971` shows the lookup returning `4999` at step 2 and the refund of `4999` at step 4.

**2. Test a fix without touching code.** Give step 2 the corrected data and let the rest run live:

```bash
agentrewind fork 5a75d971 --step 2 --output '{"order_id": "A123", "item": "laptop", "amount_usd": 49.99, "status": "delivered"}'
```

Step 1 replays from cache (4 ms, no tokens), and the agent now refunds **$49.99**.

**3. See exactly what changed.** `agentrewind diff 5a75d971 ebb96ab1`:

```text
#     original (5a75d971)                     fork (ebb96ab1)
1     llm   calls lookup_order                llm   calls lookup_order (cached)
2 *   tool  lookup_order -> "amount": 4999    tool  lookup_order -> "amount_usd": 49.99
3     llm   calls issue_refund                llm   calls issue_refund
4 *   tool  issue_refund -> $4,999.00         tool  issue_refund -> $49.99
5 *   llm   "processed a full refund of       llm   "processed a refund of $49.99..."
            $4,999.00..."
```

**4. Fix it and lock it in.** Return `amount_usd` from the tool, re-run the agent, and save the good run as a test:

```bash
agentrewind save-test <good-run-id>
```

The test replays the run from cache in CI. If anyone changes the order format, prompt or tools again, it fails and shows a diff of exactly what changed.

## Roadmap

- [x] Recorder, CLI viewer, fork and replay, diff, snapshot tests
- [ ] Anthropic SDK support
- [ ] LangGraph integration
- [ ] Web timeline UI
- [ ] PyPI release

## License

MIT
