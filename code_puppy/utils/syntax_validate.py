"""Post-edit syntax validation helpers.

Inspired by plandex's app/server/syntax/validate.go. After every agent
edit, validate the file syntax within a short timeout. If parsing fails
or times out, surface structured error markers to the agent so it can
self-correct on the next turn.

This module is designed to **fail open**:
- If turbo_parse is unavailable, validation is skipped silently.
- If the language has no registered parser, validation is skipped.
- If the parser hits the timeout, a TimedOut result is returned.
- Exceptions inside the parser are logged and treated as "parser
  unavailable" rather than being propagated as edit failures.

Usage:

    result = validate_file_sync(path="foo.py", content=new_content, timeout_s=0.5)
    if result.status is ValidationStatus.INVALID:
        # Surface result.errors back to the agent
        ...

bd-93: Migrated from direct turbo_parse_bridge to NativeBackend for
Elixir-first routing and unified acceleration access.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

PARSER_TIMEOUT_S = 0.5  # matches plandex's 500ms

# Extensions we try to validate. Anything else returns PARSER_UNAVAILABLE.
# Keep this conservative — expansion should happen as turbo_parse gains coverage.
_VALIDATABLE_EXTS: frozenset[str] = frozenset(
    {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".rb",
        ".php",
        ".swift",
        ".kt",
    }
)

# Map extensions to tree-sitter language names for turbo_parse
_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
}


class ValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    TIMED_OUT = "timed_out"
    PARSER_UNAVAILABLE = "parser_unavailable"


@dataclass(slots=True)
class ValidationResult:
    status: ValidationStatus
    errors: list[str] = field(default_factory=list)
    language: str | None = None

    @property
    def is_valid(self) -> bool:
        """Return True if the result should be treated as "not a hard failure".

        VALID, PARSER_UNAVAILABLE, and TIMED_OUT are all fail-open.
        Only INVALID should block/warn.
        """
        return self.status is not ValidationStatus.INVALID


def _ext_is_validatable(path: str) -> bool:
    return Path(path).suffix.lower() in _VALIDATABLE_EXTS


def _get_language_from_ext(path: str) -> str | None:
    return _EXT_TO_LANGUAGE.get(Path(path).suffix.lower())


def _validate_via_native_backend(path: str, content: str) -> ValidationResult:
    """Attempt to validate using native backend's extract_syntax_diagnostics.

    bd-86: Native acceleration layer removed. Returns PARSER_UNAVAILABLE
    to trigger Python fallback validation.

    Interpretation:
    - PARSER_UNAVAILABLE is fail-open: validation won't block operations.
    """
    # bd-86: Native acceleration removed, always return unavailable
    return ValidationResult(status=ValidationStatus.PARSER_UNAVAILABLE)


def validate_file_sync(
    path: str,
    content: str,
    *,
    timeout_s: float = PARSER_TIMEOUT_S,
) -> ValidationResult:
    """Synchronously validate file content, failing open on any error.

    This is the main entrypoint. bd-50: Native acceleration removed,
    always returns PARSER_UNAVAILABLE to use Python fallback validation.
    """
    # bd-50: Native acceleration removed, parser unavailable
    return ValidationResult(status=ValidationStatus.PARSER_UNAVAILABLE)


async def validate_file_async(
    path: str,
    content: str,
    *,
    timeout_s: float = PARSER_TIMEOUT_S,
) -> ValidationResult:
    """Async variant that runs the sync validator in the default executor."""
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: validate_file_sync(path, content, timeout_s=timeout_s),
    )


def format_validation_errors_for_agent(result: ValidationResult) -> str | None:
    """Render a validation result as a short warning string for the agent.

    Returns None if the result is fine (valid, timed out, or parser-unavailable).
    """
    if result.is_valid:
        return None
    if not result.errors:
        return "⚠️ Syntax validation detected an issue but provided no details."
    lines = ["⚠️ Syntax validation found issues after your edit:"]
    for err in result.errors[:5]:  # cap at 5
        lines.append(f"  - {err}")
    if len(result.errors) > 5:
        lines.append(f"  ... and {len(result.errors) - 5} more")
    lines.append("Consider checking the file and fixing any syntax errors.")
    return "\n".join(lines)
