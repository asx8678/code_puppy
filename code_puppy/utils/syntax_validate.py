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
    """Attempt to validate using NativeBackend's extract_syntax_diagnostics.

    bd-93: Migrated from direct turbo_parse_bridge to NativeBackend for
    Elixir-first routing and unified acceleration access.

    Interpretation:
    - If NativeBackend returns diagnostics with error_count == 0, treat as VALID.
    - If diagnostics have errors, surface them as INVALID with markers.
    - If NativeBackend is unavailable, treat as PARSER_UNAVAILABLE.
    - Any exception is treated as PARSER_UNAVAILABLE (fail open).
    """
    try:
        from code_puppy.native_backend import NativeBackend
    except ImportError:
        return ValidationResult(status=ValidationStatus.PARSER_UNAVAILABLE)

    # bd-93: Check if PARSE capability is available via NativeBackend
    if not NativeBackend.is_available(NativeBackend.Capabilities.PARSE):
        return ValidationResult(status=ValidationStatus.PARSER_UNAVAILABLE)

    language = _get_language_from_ext(path)
    if language is None:
        return ValidationResult(status=ValidationStatus.PARSER_UNAVAILABLE)

    # bd-93: Check if the language is supported via NativeBackend
    if not NativeBackend.is_language_supported(language):
        return ValidationResult(status=ValidationStatus.PARSER_UNAVAILABLE)

    try:
        # bd-93: Use NativeBackend for syntax diagnostics (Elixir-first routing)
        result = NativeBackend.extract_syntax_diagnostics(content, language)

        # Check for backend unavailability in result
        if isinstance(result, dict) and result.get("error"):
            # Backend is available but couldn't parse this file
            # This could be a parser limitation, not syntax error
            error_msg = result.get("error", "")
            if "not available" in error_msg.lower() or "disabled" in error_msg.lower():
                return ValidationResult(status=ValidationStatus.PARSER_UNAVAILABLE)

        # Check for actual syntax errors
        if isinstance(result, dict):
            error_count = result.get("error_count", 0)
            if error_count == 0:
                return ValidationResult(
                    status=ValidationStatus.VALID, language=language
                )

            # Collect error messages from diagnostics
            diagnostics = result.get("diagnostics", [])
            errors: list[str] = []
            for diag in diagnostics:
                if isinstance(diag, dict) and diag.get("severity") in (
                    "error",
                    "ERROR",
                ):
                    line = diag.get("line", 0)
                    message = diag.get("message", "Unknown error")
                    col = diag.get("column", 0)
                    if line > 0:
                        errors.append(f"Line {line}:{col} - {message}")
                    else:
                        errors.append(message)

            # Deduplicate errors
            seen: set[str] = set()
            unique_errors: list[str] = []
            for err in errors:
                if err not in seen:
                    seen.add(err)
                    unique_errors.append(err)

            return ValidationResult(
                status=ValidationStatus.INVALID,
                errors=unique_errors if unique_errors else ["Syntax error detected"],
                language=language,
            )

        # Unexpected result format, fail open
        return ValidationResult(status=ValidationStatus.PARSER_UNAVAILABLE)

    except Exception as e:
        # Parser itself raised — treat as unavailable (fail open).
        logger.debug("syntax_validate: parser raised for %s: %s", path, e)
        return ValidationResult(status=ValidationStatus.PARSER_UNAVAILABLE)


def validate_file_sync(
    path: str,
    content: str,
    *,
    timeout_s: float = PARSER_TIMEOUT_S,
) -> ValidationResult:
    """Synchronously validate file content, failing open on any error.

    This is the main entrypoint. Returns within ``timeout_s`` wall-clock
    time (approximately; the underlying parser may not honor cancellation
    perfectly). Always returns — never raises.
    """
    if not _ext_is_validatable(path):
        return ValidationResult(status=ValidationStatus.PARSER_UNAVAILABLE)

    # bd-93: Run the parser in a thread with a timeout via NativeBackend
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_validate_via_native_backend, path, content)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            logger.debug(
                "syntax_validate: timed out after %.3fs for %s", timeout_s, path
            )
            return ValidationResult(status=ValidationStatus.TIMED_OUT)
        except Exception as e:
            # Belt-and-suspenders: fail open on ANY unexpected error
            logger.debug("syntax_validate: unexpected error for %s: %s", path, e)
            return ValidationResult(
                status=ValidationStatus.PARSER_UNAVAILABLE,
            )


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
