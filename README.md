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

## Roadmap

- [x] Recorder, CLI viewer, fork and replay, diff, snapshot tests
- [ ] Anthropic SDK support
- [ ] LangGraph integration
- [ ] Web timeline UI
- [ ] PyPI release

## License

MIT
