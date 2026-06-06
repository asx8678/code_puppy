"""Callback registration for the force push guard plugin.

Hooks into the run_shell_command phase to intercept git force push
commands and prompt the user for approval before allowing them through.
Returns {"blocked": True} to deny, None to allow.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

from code_puppy.callbacks import register_callback
from code_puppy.config import get_yolo_mode
from code_puppy.messaging import emit_info, emit_warning
from code_puppy.plugins.force_push_guard.detector import detect_force_push


async def force_push_guard_callback(
    context: Any, command: str, cwd: str | None = None, timeout: int = 60
) -> dict[str, Any] | None:
    """Intercept shell commands containing git force push operations.

    When a force push is detected the response depends on context:

    - **Interactive + yolo_mode**: prompt the user with a red danger panel,
      because yolo bypasses the normal per-command confirmation gate in
      ``run_shell_command``.
    - **Interactive + not yolo**: ``run_shell_command`` already prompts for
      every command, so warn about the force push and defer approval to that
      single gate instead of double-prompting.
    - **Non-interactive (CI, sub-agent, piped)**: hard-block with an error.

    Sub-agents never reach the interactive branches because ``can_prompt_user``
    returns False for them — they go straight to the hard-block.

    This runs on *every* shell command, but the heavy lifting (regex matching)
    is gated behind a cheap "push" substring check inside ``detect_force_push()``.

    Args:
        context: Execution context (unused).
        command: The shell command about to run.
        cwd: Working directory (unused).
        timeout: Command timeout (unused).

    Returns:
        None if the command is safe to proceed or user approved it.
        Dict with blocked=True if a force push was detected and rejected.
    """
    match = detect_force_push(command)
    if match is None:
        return None

    from code_puppy.tools.common import can_prompt_user

    if can_prompt_user():
        if get_yolo_mode():
            return await _prompt_user_approval(command, match)
        # Non-yolo: run_shell_command will prompt for this command anyway. Warn
        # loudly but let that single gate collect the decision (no double prompt).
        emit_warning(
            f"⚠️  Force push detected ({match.pattern_name}): {match.description}"
        )
        return None

    # --- Non-interactive (or sub-agent): hard-block ---
    return _block_command(command, match)


async def _prompt_user_approval(command: str, match: Any) -> dict[str, Any] | None:
    """Show an interactive approval prompt for the detected force push.

    Args:
        command: The original shell command.
        match: The ForcePushMatch from the detector.

    Returns:
        None if user approves, Dict with blocked=True if rejected.
    """
    from code_puppy.tools.common import get_user_approval_async

    panel_content = Text()
    panel_content.append("⚠️  Force push detected: ", style="bold yellow")
    panel_content.append(match.pattern_name, style="bold red")
    panel_content.append("\n", style="")
    panel_content.append(f"  {match.description}", style="dim")
    panel_content.append("\n\n", style="")
    panel_content.append("$ ", style="bold green")
    panel_content.append(command, style="bold white")
    panel_content.append(
        "\n\nForce pushing rewrites remote history and can destroy others' work.",
        style="yellow",
    )

    confirmed, user_feedback = await get_user_approval_async(
        title="Force Push Guard 🛡️",
        content=panel_content,
        border_style="red",
    )

    if confirmed:
        emit_info("⚠️  Force push approved — proceeding with caution.")
        return None  # Allow the command through

    # Rejected
    reason = user_feedback or "User rejected force push"
    return {
        "blocked": True,
        "reasoning": f"Force push rejected: {match.pattern_name} — {reason}",
        "error_message": (
            f"🛑 Force push rejected. Detected {match.pattern_name} "
            f"in command:\n  {command}\n"
            f"  {match.description}\n"
            f"Feedback: {reason}"
        ),
    }


def _block_command(command: str, match: Any) -> dict[str, Any]:
    """Hard-block a force push in non-interactive contexts.

    Args:
        command: The original shell command.
        match: The ForcePushMatch from the detector.

    Returns:
        Dict with blocked=True and a descriptive error.
    """
    error_message = (
        f"🛑 Force push blocked! Detected {match.pattern_name} "
        f"in command:\n  {command}\n"
        f"  {match.description}\n\n"
        f"Force pushing rewrites remote history and can destroy others' work.\n"
        f"If you *really* need to force push, use the exact command directly\n"
        f"in your terminal (outside code puppy) after double-checking the target branch."
    )

    emit_warning(error_message)

    return {
        "blocked": True,
        "reasoning": f"Force push detected: {match.pattern_name} — {match.description}",
        "error_message": error_message,
    }


def register() -> None:
    """Register the force push guard callback."""
    register_callback("run_shell_command", force_push_guard_callback)


# Auto-register when this module is imported
register()
