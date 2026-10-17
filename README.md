# agentfork

[![tests](https://github.com/bimal1023/agentfork/actions/workflows/tests.yml/badge.svg)](https://github.com/bimal1023/agentfork/actions/workflows/tests.yml)

**Fork your LLM agent at any step, then sweep prompts, models or tool results to find what actually fixes it.**

![agentfork demo](https://raw.githubusercontent.com/bimal1023/agentfork/main/docs/demo.gif)

When an agent misbehaves at step 3, the usual loop is: tweak the prompt, re-run everything, eyeball one output, repeat. That is slow, costs tokens on steps that didn't change, and one lucky run proves nothing. agentfork records every LLM and tool call, replays earlier steps from cache, and runs **many variants of one step, several times each**, so you get pass rates instead of anecdotes.

Everything runs locally. No account, no server, no data leaves your machine.

## The headline example

A refund agent reads `"amount": 4999, "currency": "USD"` from an order API. The amount is in cents, and the agent refunds **$4,999** for a $49.99 laptop ([examples/refund_agent_cents.py](examples/refund_agent_cents.py)). Is the fix a better model or a better prompt?

```text
$ agentfork sweep de994fe6 --step 3 --repeat 3 --expect "49.99" --model gpt-4o-mini,gpt-4o

variant             runs  pass  avg tokens  sample output
original            1     0/1   445         I have processed a refund of $4,999.00...
model=gpt-4o-mini   3     0/3   444         I have processed a refund of $4,999.00...
model=gpt-4o        3     0/3   292         I apologize, it seems there was a mis...
```

A bigger model doesn't fix it. One sentence in the prompt does:

```text
$ agentfork sweep de994fe6 --step 3 --repeat 3 --expect "49.99" \
    --system "You are a support agent. Look up the order, then refund the full order amount in USD." \
    --system "... Order amounts from the API are in cents; divide by 100 before refunding."

variant      runs  pass  avg tokens  sample output
original     1     0/1   445         I have processed a refund of $4,999.00...
system #1    3     0/3   445         A full refund of $4,999.00 has ...
system #2    3     3/3   460         I have processed a refund of $49.99...
```

Steps 1 and 2 replayed from cache in every run, so only the step that mattered was paid for.

## Quickstart

```bash
pip install "agentfork-cli[openai]"      # or agentfork-cli[anthropic]
```

Add three things to your agent:

```python
from openai import OpenAI
from agentfork import trace, tool, wrap_openai

client = wrap_openai(OpenAI())      # records every LLM call (wrap_anthropic for Claude)

@tool                               # records every tool call
def lookup_order(order_id): ...

@trace                              # one run = one call of your agent
def run_agent(question): ...
```

Run your agent as usual. Each run is saved to `.agentfork/traces.db`.

## Commands

| Command | What it does |
| --- | --- |
| `agentfork list` | Recent runs with steps, tokens, duration and fork lineage |
| `agentfork show <id> [--full]` | A run as a step tree, with optional full JSON |
| `agentfork fork <id> --step N --output/--model/--system ...` | Re-run from step N with one change; earlier steps come from cache |
| `agentfork sweep <id> --step N --model a,b --system ... --repeat K --expect TEXT` | Try many variants of step N, K times each, and compare pass rate, tokens and time |
| `agentfork diff <a> <b>` | Compare two runs step by step |
| `agentfork save-test <id>` | Save a run as a pytest test that replays from cache in CI with no API key |
| `agentfork ui [--port N]` | Open the local web UI to browse, fork, sweep and compare runs |

## Web UI

Prefer clicking to typing? The same fork, sweep and diff are available in a local web UI.

```bash
pip install "agentfork-cli[openai,ui]"
agentfork ui        # opens http://127.0.0.1:8000
```

Start it from the folder you ran your agent in, since runs are saved to `.agentfork/` there. The server only listens on your own machine.

1. **Find the step that went wrong.** Pick a run on the left. Its timeline shows each LLM and tool call in plain words, such as `Decided to call issue_refund(amount_usd=4999)`. Click a step to see its full input and output.
2. **Try a change.** On that step, use another model, edit the system prompt, or fake a tool's result. Earlier steps replay from cache, and the new run appears under the original.
3. **Test several.** Enter a few changes, how many times to run each, and text the final output must contain. You get a pass rate per change, with the original run as the baseline:

   ```text
   Change      Passed   Example output
   Original    ○ 0/1    I have processed a refund of $4,999.00...
   Change 1    ●●● 3/3  I have processed a refund of $49.99...
   Change 2    ○○○ 0/3  I have processed a refund of $4,999.00...
   ```

4. **Compare.** Tick two runs to see them side by side, with the first step where they differ highlighted.

## How it works

1. **Record.** `@trace`, `@tool` and `wrap_openai`/`wrap_anthropic` capture each step's inputs, outputs, tokens and latency, plus a hash of its inputs.
2. **Fork.** agentfork re-imports your agent and re-runs it. Steps before N are served from the cache, step N gets your change, and everything after runs live. A model change applies to every LLM call from step N on.
3. **Sweep.** Runs fork for each variant `--repeat` times and checks each final output for your `--expect` text.
4. **Test.** `save-test` writes a JSON snapshot plus a pytest file. The test replays every step from cache and fails with a diff if any step's inputs, the step count, or the final output changes.

## Related work

agentfork overlaps with record/replay tools like [agent-rewind](https://pypi.org/project/agent-rewind/), which supports many more providers, and [agentstep](https://pypi.org/project/agentstep/), a LangGraph time-travel debugger with a web UI. agentfork's focus is the step after replay: sweeping many variants of one step, with repeats and pass rates, to choose a fix with evidence.

## Roadmap

- [x] Recorder, CLI viewer, fork, diff, snapshot tests
- [x] OpenAI and Anthropic support
- [x] Sweep with repeats and pass rates
- [x] Local web UI
- [ ] Cost estimates per variant
- [ ] Parallel sweeps
- [ ] LangGraph integration

## License

MIT
