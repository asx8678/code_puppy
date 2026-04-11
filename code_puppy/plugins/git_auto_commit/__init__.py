"""Git Auto Commit (GAC) Plugin - Safe automated git operations.

This plugin provides automated git commit functionality with strict safety guards
to ensure git mutations only occur in safe, interactive, main-agent contexts.

The context guard module provides hard-fail protection against:
- Sub-agent execution contexts (sub-agents cannot perform git mutations)
- Non-interactive terminals (user confirmation requires TTY)
- Nested agent contexts (depth > 1 is blocked)

Example:
    >>> from code_puppy.plugins.git_auto_commit import check_gac_context
    >>> check_gac_context()  # Raises GACContextError in unsafe contexts

    >>> from code_puppy.plugins.git_auto_commit import is_gac_safe
    >>> is_safe, reason = is_gac_safe()
    >>> if not is_safe:
    ...     print(f"Cannot auto-commit: {reason}")
"""

from code_puppy.plugins.git_auto_commit.context_guard import (
    GACContextError,
    REASON_NON_INTERACTIVE,
    REASON_NESTED_AGENT,
    REASON_SUBAGENT,
    check_gac_context,
    is_gac_safe,
    require_interactive_context,
)

__all__ = [
    "GACContextError",
    "REASON_SUBAGENT",
    "REASON_NON_INTERACTIVE",
    "REASON_NESTED_AGENT",
    "check_gac_context",
    "is_gac_safe",
    "require_interactive_context",
]
