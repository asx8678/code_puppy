"""Shared token estimation utilities.

Centralizes the token count heuristic so all parts of the codebase
use the same formula: 1 token per 2.5 characters (rounded down).
"""


def estimate_token_count(text: str) -> int:
    """Estimate the number of tokens in a text string.

    Uses a conservative heuristic of 1 token per 2.5 characters.
    This matches the formula used by base_agent.py's token estimation.

    Args:
        text: The text to estimate tokens for.

    Returns:
        Estimated token count, minimum 1.
    """
    return max(1, len(text) * 2 // 5)
