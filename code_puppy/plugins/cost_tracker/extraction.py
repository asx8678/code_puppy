"""Token extraction from API response formats.

Handles various response formats from different providers (OpenAI, Anthropic, etc.).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_tokens_from_result(result: Any) -> dict[str, int] | None:
    """Extract token counts from an API result.

    Handles various response formats from different providers.
    """
    try:
        # Handle dict results (common for API responses)
        if isinstance(result, dict):
            # Anthropic format first (input_tokens/output_tokens)
            if "usage" in result and isinstance(result["usage"], dict):
                usage = result["usage"]
                # Check for Anthropic-style field names first
                if "input_tokens" in usage or "output_tokens" in usage:
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    # Only return if at least one token count is present
                    if (
                        input_tokens > 0
                        or output_tokens > 0
                        or "input_tokens" in usage
                        or "output_tokens" in usage
                    ):
                        return {
                            "input": input_tokens,
                            "output": output_tokens,
                        }
                # Then check for OpenAI-style field names
                if "prompt_tokens" in usage or "completion_tokens" in usage:
                    return {
                        "input": usage.get("prompt_tokens", 0),
                        "output": usage.get("completion_tokens", 0),
                    }

            # Direct fields - check for Anthropic style first
            if "input_tokens" in result or "output_tokens" in result:
                return {
                    "input": result.get("input_tokens", 0),
                    "output": result.get("output_tokens", 0),
                }
            # Then OpenAI style
            if "prompt_tokens" in result or "completion_tokens" in result:
                return {
                    "input": result.get("prompt_tokens", 0),
                    "output": result.get("completion_tokens", 0),
                }

            # If we have a usage dict but couldn't extract tokens, return None
            if "usage" in result:
                return None

        # Handle objects with attributes
        if hasattr(result, "usage") and result.usage:
            usage = result.usage
            if isinstance(usage, dict):
                # Check for Anthropic-style field names first
                if "input_tokens" in usage or "output_tokens" in usage:
                    return {
                        "input": usage.get("input_tokens", 0),
                        "output": usage.get("output_tokens", 0),
                    }
                # Then OpenAI-style field names
                return {
                    "input": usage.get("prompt_tokens", 0),
                    "output": usage.get("completion_tokens", 0),
                }
            # Handle object-style usage - check for Anthropic style first
            if hasattr(usage, "input_tokens") or hasattr(usage, "output_tokens"):
                return {
                    "input": getattr(usage, "input_tokens", 0),
                    "output": getattr(usage, "output_tokens", 0),
                }
            # Then OpenAI style
            return {
                "input": getattr(usage, "prompt_tokens", 0),
                "output": getattr(usage, "completion_tokens", 0),
            }

    except (AttributeError, TypeError, KeyError) as e:
        logger.debug(f"Failed to extract tokens from result: {e}")

    return None
