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
)
from .models import SwarmConfig
from .orchestrator import SwarmOrchestrator

logger = logging.getLogger(__name__)


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
        # NOTE: There is no async _handle_swarm_command registered here.
        # The sync handle_swarm_custom_command from swarm_commands.py (registered
        # below) is the active /swarm handler. It delegates to _run_swarm_text()
        # with ThreadPoolExecutor support.
        # See code_puppy-6fn / code_puppy-8w6 for the deduplication rationale.

        # Register agent invocation hook
        register_callback("invoke_agent", _on_invoke_agent)
        logger.debug("Registered invoke_agent hook")

        # Register help menu
        register_callback("custom_command_help", _get_swarm_help)
        logger.debug("Registered help menu entries")

        # Import and register command handlers (for @register_command integration)
        try:
            from code_puppy.command_line.swarm_commands import (
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
