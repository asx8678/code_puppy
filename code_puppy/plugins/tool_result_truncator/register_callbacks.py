"""Tool Result Truncator Plugin

Truncates oversized tool results before they enter message history.
Uses the post_tool_call callback to intercept and trim results that exceed
the configured tool_result_max_tokens threshold.

Configuration:
    tool_result_max_tokens: Maximum tokens per tool result (default: 8000)
    Set via: /set tool_result_max_tokens=8000

Truncation Strategy:
    - Results exceeding threshold are truncated from the middle
    - Beginning and end context are preserved (most relevant parts)
    - A truncation indicator shows original and final token counts
"""

import logging
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.config import get_tool_result_max_tokens
from code_puppy.token_utils import estimate_token_count

logger = logging.getLogger(__name__)

# Tools whose results should be checked for truncation
# These produce potentially large text outputs
TRUNCATED_TOOLS = frozenset([
    "read_file",
    "grep",
    "list_files",
    "run_shell_command",
    "agent_run_shell_command",
])

# Indicator template for truncated results
TRUNCATION_INDICATOR = "\n\n[...truncated - original was {original_tokens} tokens, showing first {kept_tokens_beginning} and last {kept_tokens_end}]\n"


def _extract_result_text(result: Any) -> tuple[str, bool]:
    """Extract text content from various tool result formats.

    Args:
        result: Tool result (string, dict, Pydantic model, or other)

    Returns:
        Tuple of (text_content, was_modified) where was_modified indicates
        if we extracted from a structured type that needs to be reconstructed
    """
    # Handle None
    if result is None:
        return "", False

    # Handle strings directly
    if isinstance(result, str):
        return result, False

    # Handle bytes
    if isinstance(result, bytes):
        try:
            return result.decode("utf-8", errors="replace"), False
        except Exception:
            return str(result), False

    # Handle dicts - look for common content fields
    if isinstance(result, dict):
        # Common field names for content
        for field in ["content", "output", "result", "stdout", "text", "data"]:
            if field in result:
                field_value = result[field]
                if isinstance(field_value, str):
                    return field_value, True
                # For structured content, convert to string
                return str(field_value), True
        # No recognized field, stringify the whole thing
        return str(result), True

    # Handle Pydantic models with content attributes
    if hasattr(result, "content"):
        content = getattr(result, "content")
        if isinstance(content, str):
            return content, True
        return str(content), True

    # Handle objects with __str__ or string representation
    try:
        return str(result), True
    except Exception:
        return repr(result), True


def _reconstruct_result_with_truncation(
    original_result: Any,
    truncated_text: str,
    original_text: str
) -> Any:
    """Reconstruct a result object with truncated text.

    Args:
        original_result: The original result object
        truncated_text: The truncated text to inject
        original_text: The original text for reference

    Returns:
        Modified result with truncated content
    """
    # If original was a string, return truncated string
    if isinstance(original_result, str):
        return truncated_text

    # If original was bytes, encode truncated text
    if isinstance(original_result, bytes):
        return truncated_text.encode("utf-8")

    # If original was a dict, update the content field
    if isinstance(original_result, dict):
        result_copy = dict(original_result)
        # Find and update content field
        for field in ["content", "output", "result", "stdout", "text", "data"]:
            if field in result_copy:
                result_copy[field] = truncated_text
                return result_copy
        # If no content field found, add one
        result_copy["content"] = truncated_text
        return result_copy

    # If original was a Pydantic model, try to create a copy with new content
    if hasattr(original_result, "model_copy"):
        # Pydantic v2
        try:
            copied = original_result.model_copy()
            if hasattr(copied, "content"):
                copied.content = truncated_text
                return copied
        except Exception as e:
            logger.debug(f"Failed to copy Pydantic model: {e}")

    # If original was a dataclass or other object with content attr
    if hasattr(original_result, "content"):
        try:
            # Try to set content attribute
            original_result.content = truncated_text
            return original_result
        except Exception as e:
            logger.debug(f"Failed to set content attribute: {e}")

    # Fallback: return truncated text as string
    return truncated_text


def _truncate_text(text: str, max_tokens: int) -> str:
    """Truncate text to fit within max_tokens, preserving beginning and end.

    Args:
        text: Original text to truncate
        max_tokens: Maximum tokens allowed

    Returns:
        Truncated text with indicator
    """
    original_tokens = estimate_token_count(text)

    if original_tokens <= max_tokens:
        return text  # No truncation needed

    # Calculate how much to keep from beginning and end
    # Reserve tokens for the truncation indicator
    indicator_template = TRUNCATION_INDICATOR.format(
        original_tokens=original_tokens,
        kept_tokens_beginning=0,
        kept_tokens_end=0
    )
    indicator_tokens = estimate_token_count(indicator_template)
    available_tokens = max_tokens - indicator_tokens

    # Keep 60% from beginning, 40% from end
    beginning_ratio = 0.6
    beginning_target = int(available_tokens * beginning_ratio)
    end_target = available_tokens - beginning_target

    # Estimate character ratios based on tokens
    # Rough approximation: 1 token ≈ 4 characters for English text
    chars_per_token = 4
    beginning_chars = beginning_target * chars_per_token
    end_chars = end_target * chars_per_token

    # Split and reconstruct
    lines = text.split("\n")

    # Take beginning lines
    beginning_lines = []
    beginning_chars_count = 0
    for line in lines:
        if beginning_chars_count + len(line) + 1 > beginning_chars:
            break
        beginning_lines.append(line)
        beginning_chars_count += len(line) + 1

    # Take ending lines
    end_lines = []
    end_chars_count = 0
    for line in reversed(lines):
        if end_chars_count + len(line) + 1 > end_chars:
            break
        end_lines.insert(0, line)
        end_chars_count += len(line) + 1

    # Reconstruct truncated text
    beginning_text = "\n".join(beginning_lines)
    end_text = "\n".join(end_lines)

    # Calculate actual tokens kept
    kept_tokens_beginning = estimate_token_count(beginning_text)
    kept_tokens_end = estimate_token_count(end_text)

    indicator = TRUNCATION_INDICATOR.format(
        original_tokens=original_tokens,
        kept_tokens_beginning=kept_tokens_beginning,
        kept_tokens_end=kept_tokens_end
    )

    truncated = beginning_text + indicator + end_text

    # Log truncation event
    final_tokens = estimate_token_count(truncated)
    logger.info(
        f"Truncated tool result: {original_tokens} -> {final_tokens} tokens "
        f"(limit: {max_tokens})"
    )

    return truncated


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None
) -> Any:
    """Callback to truncate oversized tool results.

    This is called after a tool completes but before the result is sent
    to the LLM. We intercept and truncate results that exceed the
    configured token threshold.

    Args:
        tool_name: Name of the tool that was called
        tool_args: Arguments passed to the tool
        result: The tool result (may be modified)
        duration_ms: Execution time in milliseconds
        context: Optional context data

    Returns:
        The (possibly modified) result
    """
    # Only process tools that produce large text outputs
    if tool_name not in TRUNCATED_TOOLS:
        return None  # Let other callbacks handle it

    # Get the configured max tokens
    max_tokens = get_tool_result_max_tokens()

    # Extract text content from the result
    result_text, is_structured = _extract_result_text(result)

    if not result_text:
        return None  # Nothing to truncate

    # Check if truncation is needed
    original_tokens = estimate_token_count(result_text)
    if original_tokens <= max_tokens:
        return None  # Within limits, no truncation needed

    # Truncate the text
    truncated_text = _truncate_text(result_text, max_tokens)

    # If original was structured, reconstruct with truncated content
    if is_structured:
        return _reconstruct_result_with_truncation(result, truncated_text, result_text)

    # Original was a string, return truncated string
    return truncated_text


# Register the callback
register_callback("post_tool_call", _on_post_tool_call)
