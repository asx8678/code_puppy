"""Callback registration for shell command safety checking.

This module registers a callback that intercepts shell commands in yolo_mode,
or in non-interactive sub-agent runs, and assesses their safety risk before
execution.
"""

from __future__ import annotations

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
from code_puppy.tools.subagent_context import is_subagent

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

# A *single* unavailable assessment is treated leniently (assume HIGH risk and
# honour the permission level) so a transient model hiccup doesn't make the
# shell unusable. But an assessor that is *persistently* down would otherwise
# let every command through unchecked whenever the permission level is
# high/critical. Once non-interactive assessment failures pile up past this
# threshold we stop trusting the threshold override and hard-block until a real
# verdict succeeds again. Reset to 0 on the next successful assessment.
_MAX_CONSECUTIVE_UNAVAILABLE = 3
_consecutive_unavailable = 0


def _reset_unavailable_streak() -> None:
    """Record that the assessor produced a real verdict (clears the failure streak)."""
    global _consecutive_unavailable
    _consecutive_unavailable = 0


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


def _block_command(
    risk: str | None, reasoning: str | None, threshold: str
) -> dict[str, Any]:
    """Build the rejection payload for a command that exceeds the threshold.

    Shared by the cached, freshly-assessed, and assessment-failure paths so the
    block message and override hint stay consistent. The override hint points at
    the real escape hatches: raising ``safety_permission_level`` (now honoured
    even when the assessment fails) or turning ``yolo_mode`` off to approve
    commands manually. (The old hint, ``/set yolo_mode true``, was a no-op — yolo
    is what activates this check in the first place.)
    """
    risk_display = risk or "unknown"
    concise_reason = reasoning or "No reasoning provided"
    # Map an unknown/None risk onto a valid level for the /set suggestion.
    suggested_level = risk_display if risk_display in RISK_LEVELS else "high"
    error_msg = (
        f"🛑 Command blocked (risk {risk_display.upper()} > permission {threshold.upper()}).\n"
        f"Reason: {concise_reason}\n"
        f"Override: /set safety_permission_level {suggested_level} (or higher), "
        f"or /set yolo_mode false to approve commands manually."
    )
    emit_info(error_msg)
    return {
        "blocked": True,
        "risk": risk,
        "reasoning": reasoning,
        "error_message": error_msg,
    }


def _can_prompt() -> bool:
    """Whether we can ask the user to approve a command interactively.

    Delegates to the shared :func:`code_puppy.tools.common.can_prompt_user`
    helper (interactive TTY **and** not a sub-agent) so the rule stays in sync
    with the confirmation gate in command_runner and the other safety plugins.
    """
    from code_puppy.tools.common import can_prompt_user

    return can_prompt_user()


async def _handle_unavailable_assessment(
    command: str, reason: str, threshold: str
) -> dict[str, Any] | None:
    """Decide what to do when the assessor could not produce a verdict.

    A *failed* assessment is not the same as a genuine high-risk verdict, so we
    don't hard-block every command — that's what made the shell unusable
    whenever the assessor model was unavailable (e.g. a model that rejects the
    forced ``tool_choice`` used for structured output). Instead:

    * Interactive TTY  -> ask the user to approve/reject this one command.
    * Non-interactive  -> assume HIGH risk but honour the permission level, so
      raising ``safety_permission_level`` remains a real override.
    """
    if _can_prompt():
        try:
            from rich.text import Text

            from code_puppy.tools.common import get_user_approval_async

            content = Text()
            content.append(
                "⚠️  Couldn't assess this command's safety automatically.\n",
                style="bold yellow",
            )
            content.append(f"Reason: {reason}\n\n", style="dim")
            content.append("$ ", style="bold green")
            content.append(command, style="bold white")
            content.append(
                "\n\nApprove to run it anyway, or reject to skip.",
                style="yellow",
            )
            confirmed, feedback = await get_user_approval_async(
                title="Shell Safety — assessment unavailable 🛡️",
                content=content,
                border_style="yellow",
            )
            if confirmed:
                emit_info("⚠️  Command approved manually (safety check unavailable).")
                return None
            return {
                "blocked": True,
                "risk": "high",
                "reasoning": f"{reason} (rejected by user)",
                "error_message": (
                    "🛑 Command skipped — safety assessment was unavailable and "
                    f"you rejected it.\nReason: {reason}\n"
                    + (f"Feedback: {feedback}" if feedback else "")
                ),
            }
        except Exception:
            # If prompting itself fails, fall through to the threshold policy.
            pass

    # Non-interactive (or prompt failed): assume HIGH risk, honour threshold.
    global _consecutive_unavailable
    _consecutive_unavailable += 1

    # An assessor that keeps failing can't be trusted to gate anything. Once the
    # streak crosses the limit, stop honouring the permission-level override and
    # hard-block regardless of threshold until a real verdict comes back.
    if _consecutive_unavailable >= _MAX_CONSECUTIVE_UNAVAILABLE:
        error_msg = (
            f"🛑 Command blocked. The shell safety assessor has been unavailable "
            f"{_consecutive_unavailable} times in a row, so the "
            f"{threshold.upper()} permission override is no longer trusted.\n"
            f"Reason: {reason}\n"
            f"Fix the assessor model (or run the command directly in your terminal) "
            f"to proceed."
        )
        emit_info(error_msg)
        return {
            "blocked": True,
            "risk": "high",
            "reasoning": f"{reason} (assessor persistently unavailable)",
            "error_message": error_msg,
        }

    if compare_risk_levels("high", threshold):
        return _block_command("high", reason, threshold)
    emit_info(
        f"⚠️ Shell safety assessment unavailable ({reason}); allowing because the "
        f"permission level is {threshold.upper()}."
    )
    return None


async def shell_safety_callback(
    context: Any, command: str, cwd: str | None = None, timeout: int = 60
) -> dict[str, Any] | None:
    """Callback to assess shell command safety before execution.

    This callback is active when yolo_mode is True. It also runs for sub-agents
    because they cannot prompt for manual command approval.

    Args:
        context: The execution context
        command: The shell command to execute
        cwd: Optional working directory
        timeout: Command timeout (unused here)

    Returns:
        None if command is safe to proceed
        Dict with rejection info if command should be blocked
    """
    # Skip safety checks for OAuth models - they have their own safety mechanisms
    current_model = get_global_model_name()
    if is_oauth_model(current_model):
        return None

    # Main-agent non-yolo commands are reviewed manually. Sub-agents cannot
    # prompt, so route them through the safety assessor instead of silently
    # bypassing review.
    yolo_mode = get_yolo_mode()
    if not yolo_mode and not is_subagent():
        return None

    # Get configured risk threshold
    threshold = get_safety_permission_level()

    # Obtain a risk verdict. Only the cache lookup + LLM call can fail in ways
    # that mean "we have no verdict" — those route to the unavailable handler
    # (interactive approval, or threshold policy) rather than a blind block.
    try:
        # Check cache first (fast path - no LLM call)
        cached = get_cached_assessment(command, cwd)

        if cached:
            # Got a cached result - check against threshold
            if compare_risk_levels(cached.risk, threshold):
                return _block_command(cached.risk, cached.reasoning, threshold)
            # Cached result is within threshold - allow silently
            return None

        # Cache miss - need LLM assessment
        # Import here to avoid circular imports
        from code_puppy.plugins.shell_safety.agent_shell_safety import ShellSafetyAgent

        # Create agent and assess command
        agent = ShellSafetyAgent()

        # Build the assessment prompt with optional cwd context
        prompt = f"Assess this shell command:\n\nCommand: {command}"
        if cwd:
            prompt += f"\nWorking directory: {cwd}"

        # Run async assessment with structured output type
        result = await agent.run_with_mcp(prompt, output_type=ShellSafetyAssessment)
    except Exception as e:
        # The assessor itself failed (model or cache error).
        return await _handle_unavailable_assessment(
            command, f"Safety assessment error: {str(e)}", threshold
        )

    # ``run_with_mcp`` swallows model-call failures and returns None (see
    # agents/_runtime.run_with_mcp), so ``result`` — and therefore
    # ``result.output`` — can be missing. A missing verdict is *unavailable*,
    # not a genuine high-risk verdict, so don't crash and don't hard-block.
    assessment = getattr(result, "output", None)
    if assessment is None:
        return await _handle_unavailable_assessment(
            command,
            "Safety assessment unavailable (the assessor returned no result — "
            "usually a failed or unsupported model call).",
            threshold,
        )

    # A real verdict came back — the assessor is healthy again, so clear any
    # accumulated unavailable-streak that may have built up.
    _reset_unavailable_streak()

    # Cache the result for future use, but only if it's a real assessment.
    # Caching is best-effort: a cache-write failure must never block a command.
    if not getattr(assessment, "is_fallback", False):
        try:
            cache_assessment(command, cwd, assessment.risk, assessment.reasoning)
        except Exception:
            pass

    # Check if risk exceeds threshold (commands at threshold are allowed)
    if compare_risk_levels(assessment.risk, threshold):
        return _block_command(assessment.risk, assessment.reasoning, threshold)

    # Command is within acceptable risk threshold - remain silent
    return None  # Allow command to proceed


def register():
    """Register the shell safety callback."""
    register_callback("run_shell_command", shell_safety_callback)


# Auto-register the callback when this module is imported
register()
