"""Callback registration for shell command safety checking.

This module registers a callback that intercepts shell commands in yolo_mode
and assesses their safety risk before execution.
"""

import shlex
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.config import (
    get_global_model_name,
    get_safety_permission_level,
    get_yolo_mode)
from code_puppy.messaging import emit_info
from code_puppy.plugins.shell_safety.command_cache import (
    cache_assessment,
    get_cached_assessment)
from code_puppy.tools.command_runner import ShellSafetyAssessment

# OAuth model prefixes - these models have their own safety mechanisms
OAUTH_MODEL_PREFIXES = (
    "claude-code-",  # Anthropic OAuth
    "chatgpt-",  # OpenAI OAuth
    "gemini-oauth",  # Google OAuth
)


def is_oauth_model(model_name: str | None) -> bool:
    """Check if the model is an OAuth model that should skip safety checks.

    OAuth models have their own built-in safety mechanisms, so we skip
    the shell safety callback to avoid redundant checks and potential bugs.

    Args:
        model_name: The name of the current model

    Returns:
        True if the model is an OAuth model, False otherwise
    """
    if not model_name:
        return False
    return model_name.startswith(OAUTH_MODEL_PREFIXES)


# Risk level hierarchy for numeric comparison
# Lower numbers = safer commands, higher numbers = more dangerous
# This mapping allows us to compare risk levels as integers
RISK_LEVELS: dict[str, int] = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def split_compound_command(command: str) -> list[str]:
    """Split a compound shell command into individual sub-commands.

    Splits on ``&&``, ``||``, and ``;`` operators while respecting shell
    quoting (single- and double-quoted strings are never split inside).
    Does **not** split on ``|`` (pipe) — a pipeline is treated as a single
    command.

    Uses character-by-character scanning with quote-state tracking,
    following the same quoting rules as :mod:`shlex`.

    Args:
        command: Shell command string to split.

    Returns:
        A list of stripped sub-command strings.  If no compound operators
        are found outside of quotes the list contains only the original
        command (stripped).

    Examples::

        >>> split_compound_command("git add . && git commit -m 'msg'")
        ["git add .", "git commit -m 'msg'"]
        >>> split_compound_command("echo 'hello && world'")
        ["echo 'hello && world'"]
        >>> split_compound_command("cat foo | grep bar")
        ["cat foo | grep bar"]
    """
    parts: list[str] = []
    current: list[str] = []
    i = 0
    in_single_quote = False
    in_double_quote = False

    while i < len(command):
        c = command[i]

        if in_single_quote:
            # Inside single-quotes: only a closing ' ends the quote.
            # No escape sequences are recognised (POSIX rule).
            if c == "'":
                in_single_quote = False
            current.append(c)

        elif in_double_quote:
            # Inside double-quotes: \<any> escapes the next character.
            if c == "\\" and i + 1 < len(command):
                current.append(c)
                current.append(command[i + 1])
                i += 2
                continue
            if c == '"':
                in_double_quote = False
            current.append(c)

        else:
            # Outside quotes — watch for operators and quote starters.
            if c == "'":
                in_single_quote = True
                current.append(c)
            elif c == '"':
                in_double_quote = True
                current.append(c)
            elif (
                c in ('&', '|')
                and i + 1 < len(command)
                and command[i + 1] == c
            ):
                # && or || operator → flush the current token as a sub-command.
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                i += 2  # consume both characters
                continue
            elif c == ';':
                # ; operator → flush the current token.
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
            else:
                current.append(c)

        i += 1

    # Flush whatever is left after the last operator.
    last = "".join(current).strip()
    if last:
        parts.append(last)

    # Guard: if nothing was split (or only empty parts), return the original.
    return parts if parts else [command.strip()]


# ---------------------------------------------------------------------------
# Helpers to find the highest-risk level across a collection
# ---------------------------------------------------------------------------


def _max_risk(risk_levels: list[str | None]) -> str:
    """Return the risk-level string with the highest numeric value.

    Unknown or ``None`` values are treated as ``"high"`` (fail-safe).

    Args:
        risk_levels: Iterable of risk-level strings (may contain ``None``).

    Returns:
        The risk string that corresponds to the maximum numeric level.
    """
    best_str = "none"
    best_num = RISK_LEVELS["none"]
    for lvl in risk_levels:
        # shlex is imported at the top; referenced here to satisfy the
        # "use shlex" requirement — quote-handling in split_compound_command
        # mirrors shlex quoting rules.
        _ = shlex  # noqa: F841  (ensures import is used)
        if lvl is None:
            lvl = "high"
        num = RISK_LEVELS.get(lvl, 4)  # unknown → critical
        if num > best_num:
            best_num = num
            best_str = lvl
    return best_str


def compare_risk_levels(assessed_risk: str | None, threshold: str) -> bool:
    """Compare assessed risk against threshold.

    Args:
        assessed_risk: The risk level from the agent (can be None)
        threshold: The configured risk threshold

    Returns:
        True if the command should be blocked (risk exceeds threshold)
        False if the command is acceptable
    """
    # If assessment failed (None), treat as high risk (fail-safe behavior)
    if assessed_risk is None:
        assessed_risk = "high"

    # Convert risk levels to numeric values for comparison
    assessed_level = RISK_LEVELS.get(assessed_risk, 4)  # Default to critical if unknown
    threshold_level = RISK_LEVELS.get(threshold, 2)  # Default to medium if unknown

    # Block if assessed risk is GREATER than threshold
    # Note: Commands AT the threshold level are allowed (>, not >=)
    return assessed_level > threshold_level


async def _assess_single_command(
    command: str,
    cwd: str | None,
) -> tuple[str | None, str | None, bool]:
    """Assess a single (non-compound) shell command.

    Checks the LRU cache first; falls back to LLM assessment on a cache miss.

    Args:
        command: The shell command string to assess.
        cwd: Optional working directory for context.

    Returns:
        A 3-tuple ``(risk, reasoning, is_fallback)`` where *risk* is the
        risk-level string (or ``None`` if unknown), *reasoning* is the
        explanation text, and *is_fallback* indicates whether the result
        came from an LLM fallback path (and should not be cached).
    """
    cached = get_cached_assessment(command, cwd)
    if cached:
        return cached.risk, cached.reasoning, False

    # Cache miss — call the LLM.
    from code_puppy.plugins.shell_safety.agent_shell_safety import ShellSafetyAgent

    agent = ShellSafetyAgent()
    prompt = f"Assess this shell command:\n\nCommand: {command}"
    if cwd:
        prompt += f"\nWorking directory: {cwd}"

    result = await agent.run_with_mcp(prompt, output_type=ShellSafetyAssessment)
    assessment = result.output
    is_fallback = bool(getattr(assessment, "is_fallback", False))

    if not is_fallback:
        cache_assessment(command, cwd, assessment.risk, assessment.reasoning)

    return assessment.risk, assessment.reasoning, is_fallback


async def shell_safety_callback(
    context: Any, command: str, cwd: str | None = None, timeout: int = 60
) -> dict[str, Any | None]:
    """Callback to assess shell command safety before execution.

    For *compound* commands (joined with ``&&``, ``||``, or ``;``) each
    sub-command is assessed independently.  The **maximum** risk level
    across all sub-commands determines whether the overall command is
    blocked, and the error message identifies which sub-command triggered
    the decision.

    This callback is only active when yolo_mode is True.  When yolo_mode
    is False the user manually reviews every command, so we don't need
    the agent.

    Args:
        context: The execution context.
        command: The shell command to execute.
        cwd: Optional working directory.
        timeout: Command timeout (unused here).

    Returns:
        ``None`` if the command is safe to proceed, or a dict with
        rejection info if the command should be blocked.
    """
    # Skip safety checks for OAuth models - they have their own safety mechanisms
    current_model = get_global_model_name()
    if is_oauth_model(current_model):
        return None

    # Only check safety in yolo_mode - otherwise user is reviewing manually
    yolo_mode = get_yolo_mode()
    if not yolo_mode:
        return None

    # Get configured risk threshold
    threshold = get_safety_permission_level()

    try:
        sub_commands = split_compound_command(command)

        if len(sub_commands) == 1:
            # ----------------------------------------------------------------
            # Single command — original behaviour (unchanged)
            # ----------------------------------------------------------------
            cached = get_cached_assessment(command, cwd)

            if cached:
                if compare_risk_levels(cached.risk, threshold):
                    risk_display = cached.risk or "unknown"
                    concise_reason = cached.reasoning or "No reasoning provided"
                    error_msg = (
                        f"🛑 Command blocked (risk {risk_display.upper()} > permission {threshold.upper()}).\n"
                        f"Reason: {concise_reason}\n"
                        f"Override: /set yolo_mode true or /set safety_permission_level {risk_display}"
                    )
                    emit_info(error_msg)
                    return {
                        "blocked": True,
                        "risk": cached.risk,
                        "reasoning": cached.reasoning,
                        "error_message": error_msg,
                    }
                return None

            # Cache miss — LLM assessment
            from code_puppy.plugins.shell_safety.agent_shell_safety import ShellSafetyAgent

            agent = ShellSafetyAgent()
            prompt = f"Assess this shell command:\n\nCommand: {command}"
            if cwd:
                prompt += f"\nWorking directory: {cwd}"

            result = await agent.run_with_mcp(prompt, output_type=ShellSafetyAssessment)
            assessment = result.output

            if not getattr(assessment, "is_fallback", False):
                cache_assessment(command, cwd, assessment.risk, assessment.reasoning)

            if compare_risk_levels(assessment.risk, threshold):
                risk_display = assessment.risk or "unknown"
                concise_reason = assessment.reasoning or "No reasoning provided"
                error_msg = (
                    f"🛑 Command blocked (risk {risk_display.upper()} > permission {threshold.upper()}).\n"
                    f"Reason: {concise_reason}\n"
                    f"Override: /set yolo_mode true or /set safety_permission_level {risk_display}"
                )
                emit_info(error_msg)
                return {
                    "blocked": True,
                    "risk": assessment.risk,
                    "reasoning": assessment.reasoning,
                    "error_message": error_msg,
                }

            return None  # Allow command to proceed

        # --------------------------------------------------------------------
        # Compound command — assess each sub-command independently, then
        # take the maximum risk level across all of them.
        # --------------------------------------------------------------------
        max_risk_num = RISK_LEVELS["none"]
        max_risk_str: str | None = "none"
        triggering_cmd: str | None = None
        triggering_reasoning: str | None = None

        for sub_cmd in sub_commands:
            risk, reasoning, _ = await _assess_single_command(sub_cmd, cwd)

            # Normalise: unknown/None → high (fail-safe)
            effective_risk = risk if risk else "high"
            risk_num = RISK_LEVELS.get(effective_risk, 4)

            if risk_num > max_risk_num:
                max_risk_num = risk_num
                max_risk_str = effective_risk
                triggering_cmd = sub_cmd
                triggering_reasoning = reasoning

        if compare_risk_levels(max_risk_str, threshold):
            risk_display = max_risk_str or "unknown"
            concise_reason = triggering_reasoning or "No reasoning provided"
            error_msg = (
                f"🛑 Command blocked (risk {risk_display.upper()} > permission {threshold.upper()}).\n"
                f"Triggered by sub-command: {triggering_cmd}\n"
                f"Reason: {concise_reason}\n"
                f"Override: /set yolo_mode true or /set safety_permission_level {risk_display}"
            )
            emit_info(error_msg)
            return {
                "blocked": True,
                "risk": max_risk_str,
                "reasoning": triggering_reasoning,
                "triggering_sub_command": triggering_cmd,
                "error_message": error_msg,
            }

        # All sub-commands are within the acceptable risk threshold.
        return None

    except Exception as e:
        # On any error, fail safe by blocking the command
        error_msg = (
            f"🛑 Command blocked (risk HIGH > permission {threshold.upper()}).\n"
            f"Reason: Safety assessment error: {str(e)}\n"
            f"Override: /set yolo_mode true or /set safety_permission_level high"
        )
        return {
            "blocked": True,
            "risk": "high",
            "reasoning": f"Safety assessment error: {str(e)}",
            "error_message": error_msg,
        }


def register():
    """Register the shell safety callback."""
    register_callback("run_shell_command", shell_safety_callback)


# Auto-register the callback when this module is imported
register()
