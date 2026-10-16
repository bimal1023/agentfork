import re
import anthropic
from agentrewind import trace, tool, wrap_anthropic

client = wrap_anthropic(anthropic.Anthropic())
MODEL = "claude-haiku-5-5"

TOOLS = [
    {"name": "calculator",
     "description": "Evaluate a basic arithmetic expression like '23*(4+5)'.",
     "input_schema": {"type": "object",
                      "properties": {"expression": {"type": "string"}},
                      "required": ["expression"]}},
    {"name": "get_weather",
     "description": "Get the current weather for a city.",
     "input_schema": {"type": "object",
                      "properties": {"city": {"type": "string"}},
                      "required": ["city"]}},
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
        resp = client.messages.create(model=MODEL, max_tokens=1024, tools=TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                output = TOOL_FUNCS[block.name](**block.input)
                print(f"  tool {block.name}({block.input}) -> {output}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
    return "stopped: too many turns"

if __name__ == "__main__":
    print(run_agent("What's the weather in Kathmandu, and what is 23*(4+5)?"))
