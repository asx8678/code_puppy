"""Shared token estimation utilities.

Centralizes the token count heuristic so all parts of the codebase
use the same formula. Uses a tiered approach:
  - Code (detected by common code indicators): ~4.5 chars/token
  - Prose/natural language: ~4 chars/token (standard GPT tokenizer avg)
  - Fallback: ~3.5 chars/token (conservative, covers mixed content)
"""

import re

# Simple heuristics to detect code-heavy content
_CODE_INDICATORS = re.compile(
    r"[{}\[\]();]"  # braces, brackets, semicolons
    r"|^\s*(def |class |import |from |if |for |while |return )"  # Python keywords
    r"|^\s*(function |const |let |var |=>)"  # JS/TS keywords
    r"|^\s*#include\b",  # C/C++
    re.MULTILINE,
)


def _is_code_heavy(text: str) -> bool:
    """Heuristic: does the text look like source code?"""
    if len(text) < 20:
        return False
    # Count code indicator matches in first 2000 chars
    sample = text[:2000]
    matches = len(_CODE_INDICATORS.findall(sample))
    # If >5% of lines have code indicators, treat as code
    line_count = max(1, sample.count("\n") + 1)
    return matches / line_count > 0.3


def estimate_token_count(text: str) -> int:
    """Estimate the number of tokens in a text string.

    Uses a tiered heuristic based on content type:
    - Code: ~4.5 chars per token (code is more token-dense)
    - Prose: ~4.0 chars per token (standard GPT tokenizer average)

    Args:
        text: The text to estimate tokens for.

    Returns:
        Estimated token count, minimum 1.
    """
    if not text:
        return 1
    chars_per_token = 4.5 if _is_code_heavy(text) else 4.0
    return max(1, int(len(text) / chars_per_token))
