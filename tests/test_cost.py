import json

import pytest

from agentfork import pricing, replay, store

AGENT = '''
import agentfork
from anthropic.types import Message, TextBlock, Usage

class _Messages:
    def create(self, **kwargs):
        return Message(id="msg_1", type="message", role="assistant", model=kwargs["model"],
                       content=[TextBlock(type="text", text="hi")], stop_reason="end_turn",
                       stop_sequence=None, usage=Usage(input_tokens=1000, output_tokens=200))

class FakeAnthropic:
    def __init__(self):
        self.messages = _Messages()

client = agentfork.wrap_anthropic(FakeAnthropic())

@agentfork.trace
def agent(question):
    resp = client.messages.create(model="claude-haiku-5-5", max_tokens=100,
                                  messages=[{"role": "user", "content": question}])
    return resp.content[0].text
'''

@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFORK_DIR", str(tmp_path / "db"))
    path = tmp_path / "claude_agent.py"
    path.write_text(AGENT)
    replay.load_entry({"entry_file": str(path), "entry_name": "agent"})("hello")
    return store.list_runs(1)[0]

def test_price_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFORK_DIR", str(tmp_path / "db"))
    assert pricing.price("gpt-4o-mini") == (0.15, 0.60)
    assert pricing.price("gpt-4o-mini-2024-07-18") == (0.15, 0.60)
    assert pricing.price("claude-3-5-haiku-latest") == (0.80, 4.00)
    assert pricing.price("gpt-5.5") is None      # not priced as gpt-5
    assert pricing.price("my-model") is None
    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "prices.json").write_text(json.dumps({"my-model": [1, 2], "gpt-4o-mini": [9, 9]}))
    assert pricing.price("my-model") == (1, 2)
    assert pricing.price("gpt-4o-mini") == (9, 9)

def test_run_cost_and_estimate(run):
    steps = store.get_steps(run["id"])
    assert pricing.steps_cost(steps) == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1e6)

    est = replay.estimate(run, 1, [{"model": "claude-opus-5-5"}, {"system": "be brief"}], repeat=3)
    opus, haiku = (1000 * 4 + 200 * 20) / 1e6, (1000 * 0.10 + 200 * 0.50) / 1e6
    assert est["per_run"] == [pytest.approx(opus), pytest.approx(haiku)]
    assert est["total"] == pytest.approx((opus + haiku) * 3)

    unknown = replay.estimate(run, 1, [{"model": "mystery-model"}])
    assert unknown["total"] is None and unknown["unpriced"] == ["mystery-model"]

def test_sweep_reports_cost(run):
    results = replay.sweep(run, 1, [{"model": "claude-opus-5-5"}], repeat=2)
    assert [r["cost"] for r in results] == [pytest.approx((1000 * 4 + 200 * 20) / 1e6)] * 2
