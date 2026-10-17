"""Model prices for cost estimates, in USD per 1M tokens: (input, output).

Standard-tier list prices, checked October 2026. Prices change, so add or
override models in .agentfork/prices.json, for example:

    {"gpt-4o-mini": [0.15, 0.60], "my-finetune": [3.0, 12.0]}
"""
import json, re, warnings
from . import store

PRICES = {
    # OpenAI
    "gpt-5": (1.25, 10.00), "gpt-5-mini": (0.25, 2.00), "gpt-5-nano": (0.05, 0.40),
    "gpt-4.1": (2.00, 8.00), "gpt-4.1-mini": (0.40, 1.60), "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o": (2.50, 10.00), "gpt-4o-mini": (0.15, 0.60),
    "o3": (2.00, 8.00), "o3-mini": (1.10, 4.40), "o4-mini": (1.10, 4.40),
    # Anthropic
    "claude-fable-5-1": (10.00, 50.00), "claude-fable-5": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00), "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00), "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00), "claude-opus-4-5": (5.00, 25.00),
    "claude-opus-4-1": (15.00, 75.00), "claude-opus-4": (15.00, 75.00),
    "claude-sonnet-5-5": (2.00, 10.00), "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00), "claude-sonnet-4-5": (3.00, 15.00),
    "claude-sonnet-4": (3.00, 15.00), "claude-3-7-sonnet": (3.00, 15.00),
    "claude-haiku-5-5": (0.10, 0.50), "claude-haiku-4-5": (1.00, 5.00),
    "claude-3-5-haiku": (0.80, 4.00),
}

# Dated snapshots and aliases cost the same as the base model: gpt-4o-mini-2024-07-18, claude-3-5-haiku-latest.
_SUFFIX = re.compile(r"-(\d{8}|\d{4}-\d{2}-\d{2}|latest)$")

def _user_prices():
    path = store.db_path().parent / "prices.json"
    try:
        return {k.lower(): tuple(v) for k, v in json.loads(path.read_text()).items()}
    except FileNotFoundError:
        return {}
    except (ValueError, TypeError, AttributeError) as e:
        warnings.warn(f"agentfork: ignoring {path}: {e}")
        return {}

def price(model):
    """(input, output) USD per 1M tokens, or None if the model is unknown."""
    if not model:
        return None
    table = {**PRICES, **_user_prices()}
    name = model.lower()
    return table.get(name) or table.get(_SUFFIX.sub("", name))

def steps_cost(steps, model=None):
    """Total USD for the LLM steps, priced at `model` if given. None if a model or token count is unknown."""
    total = 0.0
    for s in steps:
        if s["type"] != "llm":
            continue
        p = price(model or s["name"])
        if p is None or s["tokens_in"] is None:
            return None
        total += (s["tokens_in"] * p[0] + (s["tokens_out"] or 0) * p[1]) / 1e6
    return total

def unpriced(steps, model=None):
    """Models among the LLM steps that have no price."""
    return sorted({model or s["name"] for s in steps if s["type"] == "llm" and price(model or s["name"]) is None})

def fmt(cost):
    if cost is None:
        return "-"
    return f"${cost:.4f}" if cost < 0.01 else f"${cost:.2f}"
