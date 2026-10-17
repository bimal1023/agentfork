import pytest

pytest.importorskip("langgraph")
pytest.importorskip("langchain_openai")

from agentfork import replay, store

# A real LangGraph ReAct agent on ChatOpenAI, with the OpenAI HTTP API faked by httpx.MockTransport.
AGENT = '''
import json
import httpx
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
import agentfork

def fake_openai(request):
    messages = json.loads(request.content)["messages"]
    tool_results = [m["content"] for m in messages if m["role"] == "tool"]
    if tool_results:
        message = {"role": "assistant", "content": "The order says: " + tool_results[-1]}
        finish = "stop"
    else:
        message = {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "lookup_order", "arguments": json.dumps({"order_id": "A1"})}}]}
        finish = "tool_calls"
    return httpx.Response(200, json={
        "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "gpt-4o-mini",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}})

llm = agentfork.wrap_langchain(ChatOpenAI(
    model="gpt-4o-mini", api_key="test", max_retries=0,
    http_client=httpx.Client(transport=httpx.MockTransport(fake_openai))))

@tool
@agentfork.tool
def lookup_order(order_id: str) -> str:
    """Look up an order by id."""
    return "amount 4999 cents"

graph = create_react_agent(llm, [lookup_order], prompt="You are a support agent.")

@agentfork.trace
def run_agent(question):
    return graph.invoke({"messages": [("user", question)]})["messages"][-1].content
'''

def test_langgraph_record_and_fork(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFORK_DIR", str(tmp_path / "db"))
    path = tmp_path / "lg_agent.py"
    path.write_text(AGENT)
    assert replay.load_entry({"entry_file": str(path), "entry_name": "run_agent"})("refund A1") \
        == "The order says: amount 4999 cents"

    run = store.list_runs(1)[0]
    steps = store.get_steps(run["id"])
    assert [(s["type"], s["name"]) for s in steps] == [
        ("llm", "gpt-4o-mini"), ("tool", "lookup_order"), ("llm", "gpt-4o-mini")]
    assert steps[0]["tokens_in"] == 50

    new_id, result = replay.fork(run, 2, output="amount 49.99 dollars")
    assert result == "The order says: amount 49.99 dollars"
    assert [s["cached"] for s in store.get_steps(new_id)] == [1, 0, 0]
