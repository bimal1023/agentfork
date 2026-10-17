import json
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
import agentfork

# The refund agent from refund_agent_cents.py, built with LangGraph.
# wrap_langchain records the model's calls; @agentfork.tool (under @tool) records the tools.
llm = agentfork.wrap_langchain(ChatOpenAI(model="gpt-4o-mini"))

SYSTEM = "You are a support agent. Look up the order, then refund the full order amount in USD."
ORDERS = {"A123": {"order_id": "A123", "item": "laptop", "amount": 4999, "currency": "USD", "status": "delivered"}}

@tool
@agentfork.tool
def lookup_order(order_id: str) -> str:
    """Look up an order by id."""
    return json.dumps(ORDERS.get(order_id, {"error": "not found"}))

@tool
@agentfork.tool
def issue_refund(order_id: str, amount_usd: float) -> str:
    """Refund an order. amount_usd is in US dollars."""
    return f"Refunded ${amount_usd:,.2f} for order {order_id}"

graph = create_react_agent(llm, [lookup_order, issue_refund], prompt=SYSTEM)

@agentfork.trace
def run_agent(question):
    return graph.invoke({"messages": [("user", question)]})["messages"][-1].content

if __name__ == "__main__":
    print(run_agent("My headphones from order A123 arrived broken. Please refund me."))
