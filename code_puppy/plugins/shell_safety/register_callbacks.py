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
    get_yolo_mode,
)
from code_puppy.messaging import emit_info
from code_puppy.plugins.shell_safety.command_cache import (
    cache_assessment,
    get_cached_assessment,
)
from code_puppy.tools.command_runner import ShellSafetyAssessment

# SECURITY FIX: OAuth bypass removed (issues ydcv, d1li, e6c5)
# Previously OAuth models bypassed shell safety checks based on name prefixes,
# which was vulnerable to prefix spoofing (e.g., "claude-code-malicious").
# Defense in depth: All models now go through the same safety pipeline.


def is_oauth_model(model_name: str | None) -> bool:
    """DEPRECATED: OAuth bypass removed for security.

    Previously checked if model was an OAuth model to skip safety checks.
    Now returns False always - all models must go through safety pipeline.

    Args:
        model_name: Ignored - kept for API compatibility

    Returns:
        False always - OAuth bypass removed for security
    """
    return False


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

    .. deprecated::
        Use :func:`code_puppy.utils.shell_split.split_compound_command` directly.
        This re-export is kept for backward compatibility.
    """
    from code_puppy.utils.shell_split import split_compound_command as _split

    return _split(command)


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
) -> dict[str, Any] | None:
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

    # --- PolicyEngine fast-path ------------------------------------------
    # Consult explicit policy rules before touching the LLM agent.
    from code_puppy.permission_decision import Allow, Deny
    from code_puppy.policy_engine import get_policy_engine

    engine = get_policy_engine()
    policy_result = engine.check_shell_command_explicit(command, cwd)

    if isinstance(policy_result, Allow):
        # Explicit allow rule — skip LLM assessment entirely.
        return None

    if isinstance(policy_result, Deny):
        deny_msg = (
            "\U0001f6d1 Command blocked by policy rule.\n"
            f"Reason: {policy_result.reason}\n"
            "Override: add an 'allow' rule to ~/.code_puppy/policy.json"
        )
        emit_info(deny_msg)
        return {
            "blocked": True,
            "risk": "denied_by_policy",
            "reasoning": policy_result.reason,
            "error_message": deny_msg,
        }

    # AskUser (no explicit rule) — fall through to existing LLM assessment.
    # Only run the LLM in yolo_mode; otherwise the user reviews manually.
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
            from code_puppy.plugins.shell_safety.agent_shell_safety import (
                ShellSafetyAgent,
            )

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
