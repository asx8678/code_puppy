"""Pricing data and cost calculation for the cost tracker plugin.

Provides model pricing lookups and cost calculations.
"""

import logging

logger = logging.getLogger(__name__)

# Default pricing per 1K tokens (in USD) - industry standard rates
# These are approximate rates; users can override via config
DEFAULT_PRICING = {
    # OpenAI models
    "gpt-4o": {"input": 0.0025, "output": 0.010},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.010, "output": 0.030},
    "gpt-4": {"input": 0.030, "output": 0.060},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    # Anthropic models
    "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-5-haiku": {"input": 0.0008, "output": 0.004},
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    "claude-code": {"input": 0.003, "output": 0.015},
    # Google/Gemini models
    "gemini-2": {"input": 0.0007, "output": 0.0021},
    "gemini-1.5-pro": {"input": 0.0035, "output": 0.0105},
    "gemini-1.5-flash": {"input": 0.00035, "output": 0.00105},
    "gemini-1.0-pro": {"input": 0.0005, "output": 0.0015},
    # Antigravity models (uses Gemini rates)
    "antigravity": {"input": 0.0007, "output": 0.0021},
}


def get_pricing_for_model(model_name: str) -> dict[str, float]:
    """Get pricing for a model, with fallback to defaults."""
    # Try exact match
    if model_name in DEFAULT_PRICING:
        return DEFAULT_PRICING[model_name]

    # Try prefix match (e.g., "gpt-4o-2024-08-06" matches "gpt-4o")
    for prefix, pricing in DEFAULT_PRICING.items():
        if model_name.startswith(prefix):
            return pricing

    # Default fallback pricing
    logger.debug(f"No pricing found for model: {model_name}, using defaults")
    return {"input": 0.001, "output": 0.003}  # Conservative defaults


def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for a model call."""
    pricing = get_pricing_for_model(model_name)
    input_cost = (input_tokens / 1000) * pricing["input"]
    output_cost = (output_tokens / 1000) * pricing["output"]
    return round(input_cost + output_cost, 6)
