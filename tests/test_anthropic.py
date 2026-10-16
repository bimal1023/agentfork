from agentfork import replay, store

AGENT = '''
import agentfork
from anthropic.types import Message, TextBlock, Usage

class _Messages:
    def create(self, **kwargs):
        return Message(id="msg_1", type="message", role="assistant", model=kwargs["model"],
                       content=[TextBlock(type="text", text="system=" + kwargs.get("system", "none"))],
                       stop_reason="end_turn", stop_sequence=None,
                       usage=Usage(input_tokens=10, output_tokens=5))

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

def test_anthropic_record_fork_and_check(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFORK_DIR", str(tmp_path / "db"))
    path = tmp_path / "claude_agent.py"
    path.write_text(AGENT)
    agent = replay.load_entry({"entry_file": str(path), "entry_name": "agent"})
    assert agent("hi") == "system=none"

    run = store.list_runs(1)[0]
    steps = store.get_steps(run["id"])
    assert steps[0]["tokens_in"] == 10 and steps[0]["tokens_out"] == 5

    _, result = replay.fork(run, step=1, system="be a pirate")
    assert result == "system=be a pirate"
    assert replay.check({"run": run, "steps": steps}) == "system=none"
