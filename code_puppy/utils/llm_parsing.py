"""LLM output parsing utilities.

Robust JSON extraction from LLM text outputs that may include markdown fences,
prose explanations, or multiple JSON candidates.

This module is particularly useful when working with LLM APIs that return
JSON embedded in natural language text or markdown code blocks.

Migration candidates (code_puppy/ files that could use this utility):
- code_puppy/chatgpt_codex_client.py:287 - SSE event data parsing with
  json.loads(data_str) inside try/except JSONDecodeError
- code_puppy/gemini_code_assist.py:338 - SSE stream data parsing with
  json.loads(data_str) that silently continues on parse errors
- code_puppy/gemini_model.py:720 - Streaming response chunk parsing with
  json.loads(json_str) that silently continues on parse errors
- code_puppy/utils/stream_parser.py:186 - lenient JSONL parsing that could
  benefit from fenced JSON extraction before falling back to line parsing
"""

from __future__ import annotations

import json
import re
from typing import Any


# Regex to strip markdown code fences (```json or just ```)
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

# Regex to find JSON-like substrings (objects or arrays)
_JSON_SNIPPET_RE = re.compile(r"({[\s\S]*?})|(\[[\s\S]*?])")


def extract_json_from_text(text: str | None) -> Any | None:
    """Extract and parse JSON from LLM output text.

    Tries multiple strategies in order of likelihood:
    1. Direct JSON parsing on raw text
    2. Strip markdown code fences and retry
    3. Regex-find JSON-looking substrings (objects/arrays) and try each

    This function never raises exceptions - it returns None on any failure,
    making it safe for use in parsing pipelines where malformed input is
    expected and should be handled gracefully.

    Args:
        text: Raw text from an LLM, which may contain JSON surrounded by
            markdown fences, prose, or other formatting. Can be None.

    Returns:
        The parsed JSON value (dict, list, str, int, etc.) if found and valid,
        otherwise None.

    Examples:
        >>> extract_json_from_text('{"key": "value"}')
        {'key': 'value'}

        >>> extract_json_from_text('```json\\n{"key": "value"}\\n```')
        {'key': 'value'}

        >>> extract_json_from_text('```\\n[1, 2, 3]\\n```')
        [1, 2, 3]

        >>> extract_json_from_text('Here is the result: {"key": "value"} Thanks!')
        {'key': 'value'}

        >>> extract_json_from_text('Invalid { json here') is None
        True

        >>> extract_json_from_text(None) is None
        True
    """
    if text is None:
        return None

    text = text.strip()
    if not text:
        return None

    # Strategy 1: Try raw parse on the full text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Strip markdown code fences and retry
    cleaned = _CODE_FENCE_RE.sub("", text).strip()
    if cleaned != text:
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    # Strategy 3: Find JSON-looking substrings and try each
    # This handles cases like "Here is the data: {...} and some prose after"
    for match in _JSON_SNIPPET_RE.finditer(text):
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    # All strategies failed
    return None
