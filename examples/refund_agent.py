import json
from openai import OpenAI
from agentfork import trace, tool, wrap_openai

client = wrap_openai(OpenAI())
MODEL = "gpt-4o-mini"

SYSTEM = "You are a support agent. Look up the order, then refund the full order amount in USD."

TOOLS = [
    {"type": "function", "function": {
        "name": "lookup_order",
        "description": "Look up an order by id.",
        "parameters": {"type": "object",
                       "properties": {"order_id": {"type": "string"}},
                       "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "issue_refund",
        "description": "Refund an order. amount_usd is in US dollars.",
        "parameters": {"type": "object",
                       "properties": {"order_id": {"type": "string"},
                                      "amount_usd": {"type": "number"}},
                       "required": ["order_id", "amount_usd"]}}},
]

ORDERS = {"A123": {"order_id": "A123", "item": "laptop", "amount_usd": 49.99, "status": "delivered"}}
@tool
def lookup_order(order_id):
    return json.dumps(ORDERS.get(order_id, {"error": "not found"}))

@tool
def issue_refund(order_id, amount_usd):
    return f"Refunded ${amount_usd:,.2f} for order {order_id}"

TOOL_FUNCS = {"lookup_order": lookup_order, "issue_refund": issue_refund}

@trace
def run_agent(question, max_turns=6):
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    for _ in range(max_turns):
        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
        msg = resp.choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments)
            output = TOOL_FUNCS[call.function.name](**args)
            print(f"  tool {call.function.name}({args}) -> {output}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
    return "stopped: too many turns"

if __name__ == "__main__":
    print(run_agent("My headphones from order A123 arrived broken. Please refund me."))
