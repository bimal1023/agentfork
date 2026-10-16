import json, re
from openai import OpenAI
from agentfork import trace, tool, wrap_openai
client = wrap_openai(OpenAI())
MODEL = "gpt-4o-mini"

TOOLS = [
    {"type": "function", "function": {
        "name": "calculator",
        "description": "Evaluate a basic arithmetic expression like '23*(4+5)'.",
        "parameters": {"type": "object",
                       "properties": {"expression": {"type": "string"}},
                       "required": ["expression"]}}},
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string"}},
                       "required": ["city"]}}},
]
@tool
def calculator(expression):
    if not re.fullmatch(r"[\d\s+\-*/().]+", expression):
        return "error: invalid expression"
    return str(eval(expression))
@tool
def get_weather(city):
    fake = {"new york": "18C, cloudy", "kathmandu": "22C, sunny"}
    return fake.get(city.lower(), "15C, clear")

TOOL_FUNCS = {"calculator": calculator, "get_weather": get_weather}
@trace
def run_agent(question, max_turns=5):
    messages = [{"role": "user", "content": question}]
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
    print(run_agent("What's the weather in Kathmandu, and what is 23*(4+5)?"))
