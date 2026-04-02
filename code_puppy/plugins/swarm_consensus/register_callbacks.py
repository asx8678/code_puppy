"""
Plugin registration for Agent Swarm Consensus.

Registers the swarm consensus feature with Code Puppy's callback system:
- /swarm slash command for manual invocation
- invoke_agent hook for automatic swarm on critical tasks
- run_swarm_consensus tool for programmatic access
- Help menu integration
- Command handler integration via swarm_commands module
"""

import logging
from typing import Any

from code_puppy.callbacks import register_callback

from .config import (
    get_consensus_threshold,
    get_default_swarm_size,
    get_swarm_enabled,
    get_swarm_timeout_seconds,
    set_swarm_enabled,
)
from .models import SwarmConfig
from .orchestrator import SwarmOrchestrator

logger = logging.getLogger(__name__)

# Global orchestrator instance (lazy initialized)
_orchestrator: SwarmOrchestrator | None = None


def _get_orchestrator() -> SwarmOrchestrator:
    """Get or create the swarm orchestrator."""
    global _orchestrator
    if _orchestrator is None:
        config = SwarmConfig(
            swarm_size=get_default_swarm_size(),
            consensus_threshold=get_consensus_threshold(),
            timeout_seconds=get_swarm_timeout_seconds(),
        )
        _orchestrator = SwarmOrchestrator(config)
    return _orchestrator


# =============================================================================
# Slash Command Handler
# =============================================================================


async def _handle_swarm_command(command: str, name: str) -> str | bool | None:
    """Handle the /swarm slash command.

    Commands:
        /swarm <prompt> - Run swarm consensus on a task
        /swarm:enable - Enable automatic swarm mode
        /swarm:disable - Disable automatic swarm mode
        /swarm:status - Show swarm configuration

    Args:
        command: The full command text
        name: The command name

    Returns:
        Response string, True if handled, or None if not our command.

    Note:
        This is an async callback. The callback system's ``_trigger_callbacks_sync``
        detects whether a loop is already running and handles both contexts:
        - Running loop → schedules as a Task via ``asyncio.ensure_future``
        - No loop      → executes via ``asyncio.run``
    """
    parts = command.split(None, 1)
    if not parts:
        return None

    subcommand = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    # Handle subcommands (these are synchronous, no await needed)
    if subcommand in ("enable", ":enable"):
        set_swarm_enabled(True)
        return "✅ Swarm consensus mode enabled. Critical tasks will use ensemble programming."

    if subcommand in ("disable", ":disable"):
        set_swarm_enabled(False)
        return "❌ Swarm consensus mode disabled."

    if subcommand in ("status", ":status"):
        return _format_status()

    # Default: run swarm on the provided prompt
    if subcommand == "swarm" or not subcommand.startswith(":"):
        prompt = args or subcommand
        if not prompt:
            return "Usage: /swarm <task description> or /swarm:status"

        try:
            result = await _run_swarm_for_command(prompt)
            return _format_swarm_result(result)

        except Exception as e:
            logger.exception("Swarm command failed")
            return f"❌ Swarm execution failed: {e}"

    return None  # Not our command


def _format_status() -> str:
    """Format swarm status for display."""
    enabled = get_swarm_enabled()
    size = get_default_swarm_size()
    threshold = get_consensus_threshold()
    timeout = get_swarm_timeout_seconds()

    status_emoji = "✅" if enabled else "❌"

    return f"""## 🤖 Agent Swarm Consensus Status

{status_emoji} **Enabled**: {enabled}
📊 **Swarm Size**: {size} agents
🎯 **Consensus Threshold**: {threshold:.0%}
⏱️ **Timeout**: {timeout}s

### Available Approaches
- thorough, creative, critical, pragmatic
- security, performance, minimalist

Use `/swarm <task>` to run consensus manually.
Use `/swarm:enable` to auto-run on critical tasks.
"""


async def _run_swarm_for_command(prompt: str) -> Any:
    """Run swarm execution for a slash command."""
    orchestrator = _get_orchestrator()
    return await orchestrator.execute_swarm(
        task_prompt=prompt,
        task_type="default",
    )


def _format_swarm_result(result: Any) -> str:
    """Format swarm result for display."""
    lines = [
        "# 🤖 Agent Swarm Consensus Result",
        "",
        f"**Consensus Reached**: {'✅ Yes' if result.consensus_reached else '⚠️ No'}",
        f"**Average Confidence**: {result.get_average_confidence():.2f}",
        "",
        "## Final Answer",
        result.final_answer,
        "",
    ]

    if result.individual_results:
        lines.extend(["## Agent Contributions", ""])
        for agent_result in result.individual_results:
            emoji = "🔥" if agent_result.confidence_score >= 0.8 else "✅"
            lines.append(
                f"{emoji} **{agent_result.agent_name}** "
                f"({agent_result.approach_used}): {agent_result.confidence_score:.2f}"
            )

    return "\n".join(lines)


# =============================================================================
# Invoke Agent Hook
# =============================================================================


def _on_invoke_agent(*args: Any, **kwargs: Any) -> None:
    """Hook called when an agent is invoked.

    If swarm mode is enabled and this looks like a critical task,
    we could optionally intercept and use swarm. For now, this is
    a placeholder for future auto-swarm functionality.
    """
    if not get_swarm_enabled():
        return

    # Currently we just log that swarm is available
    # Future: auto-detect critical tasks and use swarm
    logger.debug("Swarm mode enabled - agent invocation logged")


# =============================================================================
# Tool Registration
# =============================================================================


def _register_swarm_tool() -> dict[str, Any]:
    """Register the run_swarm_consensus tool."""

    async def run_swarm_consensus(
        task_prompt: str,
        task_type: str = "default",
        swarm_size: int | None = None,
        consensus_threshold: float | None = None,
    ) -> dict[str, Any]:
        """Run swarm consensus on a task.

        Args:
            task_prompt: The task to solve
            task_type: Type of task (refactor, security_review, etc.)
            swarm_size: Override default swarm size
            consensus_threshold: Override consensus threshold

        Returns:
            dict: Swarm result with consensus and final answer
        """
        config = SwarmConfig(
            swarm_size=swarm_size or get_default_swarm_size(),
            consensus_threshold=consensus_threshold or get_consensus_threshold(),
            timeout_seconds=get_swarm_timeout_seconds(),
        )

        orchestrator = SwarmOrchestrator(config)
        result = await orchestrator.execute_swarm(
            task_prompt=task_prompt,
            task_type=task_type,
        )

        return {
            "consensus_reached": result.consensus_reached,
            "final_answer": result.final_answer,
            "confidence_scores": result.confidence_scores,
            "execution_stats": result.execution_stats,
            "debate_transcript": result.debate_transcript if result.debate_transcript else None,
        }

    return {
        "name": "run_swarm_consensus",
        "register_func": run_swarm_consensus,
    }


# =============================================================================
# Help Menu Integration
# =============================================================================


def _get_swarm_help() -> list[tuple[str, str]]:
    """Return help entries for swarm commands."""
    return [
        ("/swarm <task>", "Run agent swarm consensus on a task"),
        ("/swarm:enable", "Enable automatic swarm mode"),
        ("/swarm:disable", "Disable automatic swarm mode"),
        ("/swarm:status", "Show swarm configuration"),
    ]


# =============================================================================
# Plugin Registration
# =============================================================================


def _register() -> None:
    """Register all swarm consensus callbacks."""
    try:
        # Register slash command via callback system
        register_callback("custom_command", _handle_swarm_command)
        logger.debug("Registered /swarm command handler via custom_command hook")

        # Register agent invocation hook
        register_callback("invoke_agent", _on_invoke_agent)
        logger.debug("Registered invoke_agent hook")

        # Register help menu
        register_callback("custom_command_help", _get_swarm_help)
        logger.debug("Registered help menu entries")

        # Import and register command handlers (for @register_command integration)
        try:
            from code_puppy.command_line.swarm_commands import (
                get_swarm_help_entries,
                handle_swarm_custom_command,
            )

            # Register with command callback system for additional integration
            register_callback("custom_command", handle_swarm_custom_command)
            logger.debug("Registered swarm command handlers from swarm_commands module")
        except ImportError as e:
            logger.debug(f"swarm_commands module not available: {e}")

        logger.info("Agent Swarm Consensus plugin registered successfully")

    except Exception as e:
        logger.warning(f"Failed to register swarm consensus plugin: {e}")


# Register on module load
_register()
