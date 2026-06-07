"""
Pattern matching engine for hook filters.

Provides flexible pattern matching to determine if a hook should execute
based on tool name, arguments, and other event data.
"""

from __future__ import annotations

import functools
import re
from typing import Any

from .aliases import get_aliases

# Upper bound on the haystack length we feed to a user-supplied regex. Matcher
# patterns come from hook config (user-authored) but the strings matched against
# can include model-influenced file paths, so we bound the input to limit the
# blast radius of a pathological (catastrophic-backtracking) pattern. Full ReDoS
# safety would require a timeout-capable regex engine.
_MAX_REGEX_HAYSTACK = 4096


@functools.lru_cache(maxsize=512)
def _compile_pattern(pattern: str, flags: int) -> re.Pattern | None:
    """Compile and cache a user pattern. Returns None if it is invalid."""
    try:
        return re.compile(pattern, flags)
    except re.error:
        return None


def _safe_search(pattern: str, text: str) -> bool:
    """Case-insensitive ``re.search`` with a cached pattern and bounded input."""
    compiled = _compile_pattern(pattern, re.IGNORECASE)
    if compiled is None:
        return False
    return bool(compiled.search(text[:_MAX_REGEX_HAYSTACK]))


def matches(matcher: str, tool_name: str, tool_args: dict[str, Any]) -> bool:
    """
    Evaluate if a matcher pattern matches the tool call.

    Matcher Syntax:
        - "*" - Matches all tools
        - "ToolName" - Exact tool name match
        - ".ext" - File extension match (e.g., ".py", ".ts")
        - "Pattern1 && Pattern2" - AND condition (all must match)
        - "Pattern1 || Pattern2" - OR condition (any must match)
    """
    if not matcher:
        return False

    if matcher.strip() == "*":
        return True

    if "||" in matcher:
        parts = [p.strip() for p in matcher.split("||")]
        return any(matches(part, tool_name, tool_args) for part in parts)

    if "&&" in matcher:
        parts = [p.strip() for p in matcher.split("&&")]
        return all(matches(part, tool_name, tool_args) for part in parts)

    return _match_single(matcher.strip(), tool_name, tool_args)


def _match_single(pattern: str, tool_name: str, tool_args: dict[str, Any]) -> bool:
    if pattern == tool_name:
        return True

    if pattern.lower() == tool_name.lower():
        return True

    # Check cross-provider aliases: a hook written for "Bash" (Claude Code) should
    # fire when code_puppy calls "agent_run_shell_command", and vice-versa.
    tool_aliases = get_aliases(tool_name)
    pattern_aliases = get_aliases(pattern)
    if tool_aliases & pattern_aliases:  # non-empty intersection → same logical tool
        return True

    if pattern.startswith("."):
        file_path = _extract_file_path(tool_args)
        if file_path:
            return file_path.endswith(pattern)
        return False

    if "*" in pattern:
        parts = pattern.split("*")
        regex_pattern = "^" + ".*".join(re.escape(part) for part in parts) + "$"
        compiled = _compile_pattern(regex_pattern, re.IGNORECASE)
        if compiled is not None and compiled.match(tool_name):
            return True

    if _is_regex_pattern(pattern):
        if _safe_search(pattern, tool_name):
            return True
        file_path = _extract_file_path(tool_args)
        if file_path and _safe_search(pattern, file_path):
            return True

    return False


def _extract_file_path(tool_args: dict[str, Any]) -> str | None:
    file_keys = [
        "file_path",
        "file",
        "path",
        "target",
        "input_file",
        "output_file",
        "source",
        "destination",
        "src",
        "dest",
        "filename",
    ]
    for key in file_keys:
        if key in tool_args:
            value = tool_args[key]
            if isinstance(value, str):
                return value
            if hasattr(value, "__fspath__"):
                return str(value)
    for value in tool_args.values():
        if isinstance(value, str) and _looks_like_file_path(value):
            return value
    return None


def _looks_like_file_path(value: str) -> bool:
    if not value:
        return False
    if "." in value and not value.startswith("."):
        parts = value.rsplit(".", 1)
        if len(parts) == 2 and len(parts[1]) <= 10 and parts[1].isalnum():
            return True
    if "/" in value or "\\" in value:
        return True
    return False


def _is_regex_pattern(pattern: str) -> bool:
    regex_chars = ["^", "$", ".", "+", "?", "[", "]", "(", ")", "{", "}", "|", "\\"]
    return any(char in pattern for char in regex_chars)


def extract_file_extension(file_path: str) -> str | None:
    if not file_path or "." not in file_path:
        return None
    if "/" in file_path:
        file_path = file_path.rsplit("/", 1)[-1]
    if "\\" in file_path:
        file_path = file_path.rsplit("\\", 1)[-1]
    if "." in file_path:
        return "." + file_path.rsplit(".", 1)[-1]
    return None


def matches_tool(tool_name: str, *names: str) -> bool:
    return tool_name.lower() in [name.lower() for name in names]


def matches_file_extension(tool_args: dict[str, Any], *extensions: str) -> bool:
    file_path = _extract_file_path(tool_args)
    if not file_path:
        return False
    ext = extract_file_extension(file_path)
    return ext in extensions


def matches_file_pattern(tool_args: dict[str, Any], pattern: str) -> bool:
    file_path = _extract_file_path(tool_args)
    if not file_path:
        return False
    try:
        return bool(re.search(pattern, file_path, re.IGNORECASE))
    except re.error:
        return False
