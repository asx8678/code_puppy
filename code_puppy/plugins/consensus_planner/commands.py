"""Command handlers for Consensus Planner operations.

Moved from code_puppy/command_line/consensus_planner_commands.py to follow
the plugin architecture. These handlers are invoked via the custom_command
callback in register_callbacks.py.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from code_puppy.messaging import emit_error, emit_info, emit_success, emit_warning

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from sync context, handling running event loops.

    Uses thread pool fallback when called from within an existing event loop
    (e.g., the Code Puppy REPL/TUI context).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


# =============================================================================
# Command Handlers
# =============================================================================


def handle_consensus_plan_command(command: str) -> bool:
    """Handle the /consensus_plan command.

    Args:
        command: The full command string

    Returns:
        True if handled
    """
    # Extract the task from the command
    parts = command.split(None, 1)
    if len(parts) < 2:
        emit_warning("Usage: /consensus_plan <task description>")
        emit_info("Example: /consensus_plan Design a caching system")
        return True

    task = parts[1].strip()
    if not task:
        emit_warning("Please provide a task description")
        return True

    emit_info(f"🎯 Creating consensus plan for: {task[:60]}...")

    try:
        result = _run_async(_run_consensus_plan(task))
        _display_consensus_plan(result)
        return True
    except Exception as e:
        logger.exception("Consensus plan failed")
        emit_error(f"Consensus planning failed: {e}")
        return True


def handle_compare_models_command(command: str) -> bool:
    """Handle the /compare_models command.

    Args:
        command: The full command string

    Returns:
        True if handled
    """
    parts = command.split(None, 1)
    if len(parts) < 2:
        emit_warning("Usage: /compare_models <task description>")
        emit_info("Example: /compare_models How should I refactor this?")
        return True

    task = parts[1].strip()
    if not task:
        emit_warning("Please provide a task description")
        return True

    emit_info(f"🤖 Comparing models for: {task[:60]}...")

    try:
        results = _run_async(_run_model_comparison(task))
        _display_model_comparison(results)
        return True
    except Exception as e:
        logger.exception("Model comparison failed")
        emit_error(f"Model comparison failed: {e}")
        return True


def handle_model_vote_command(command: str) -> bool:
    """Handle the /model_vote command.

    Args:
        command: The full command string

    Returns:
        True if handled
    """
    parts = command.split(None, 1)
    if len(parts) < 2:
        emit_warning("Usage: /model_vote <task description>")
        emit_info("Example: /model_vote Which model should handle this?")
        return True

    task = parts[1].strip()
    if not task:
        emit_warning("Please provide a task description")
        return True

    emit_info(f"🗳️ Running model vote for: {task[:60]}...")

    try:
        best_model = _run_async(_run_model_vote(task))
        emit_success(f"🎯 Consensus recommends: **{best_model}**")
        return True
    except Exception as e:
        logger.exception("Model vote failed")
        emit_error(f"Model vote failed: {e}")
        return True


# =============================================================================
# Subcommand Handlers
# =============================================================================


def handle_consensus_subcommands(command: str) -> bool:
    """Handle consensus planner subcommands.

    Args:
        command: The full command string

    Returns:
        True if handled
    """
    cmd_parts = command.split(":", 1)
    subcommand = cmd_parts[1] if len(cmd_parts) > 1 else "status"

    if subcommand == "enable":
        from code_puppy.config import set_config_value

        set_config_value("consensus_planner_enabled", "true")
        emit_success("✅ Consensus planner enabled")
        emit_info("Tasks will now use multi-model consensus when appropriate")
        return True

    if subcommand == "disable":
        from code_puppy.config import set_config_value

        set_config_value("consensus_planner_enabled", "false")
        emit_info("❌ Consensus planner disabled")
        emit_info("Tasks will use single model execution")
        return True

    if subcommand in ("config", "status"):
        _show_consensus_config()
        return True

    return True


def _show_consensus_config() -> None:
    """Display current consensus planner configuration."""
    from code_puppy.config import (
        get_consensus_planner_enabled,
        get_consensus_planner_swarm_size,
        get_consensus_planner_threshold,
        get_consensus_planner_timeout,
    )
    from code_puppy.plugins.consensus_planner.council_consensus import (
        _get_advisor_models,
        _get_leader_model,
    )

    enabled = get_consensus_planner_enabled()
    threshold = get_consensus_planner_threshold()
    swarm_size = get_consensus_planner_swarm_size()
    timeout = get_consensus_planner_timeout()

    leader = _get_leader_model()
    advisors = _get_advisor_models(exclude_leader=leader)

    status_emoji = "✅" if enabled else "❌"

    lines = [
        "## 🎯 Consensus Planner Configuration",
        "",
        f"{status_emoji} **Enabled**: {enabled}",
        f"🎯 **Complexity Threshold**: {threshold:.0%}",
        f"📊 **Swarm Size**: {swarm_size} agents",
        f"⏱️ **Timeout**: {timeout}s",
        "",
        "**Council Models**:",
        f"  👑 Leader: {leader}",
    ]
    if advisors:
        for model in advisors:
            lines.append(f"  📣 Advisor: {model}")
    else:
        lines.append("  ⚠️ No advisor models (pin models to agents to add advisors)")

    lines.extend([
        "",
        "### Commands",
        "- `/consensus_plan <task>` - Force plan with consensus",
        "- `/compare_models <task>` - Compare model outputs",
        "- `/model_vote <task>` - Get model recommendation",
        "- `/consensus:enable` - Enable consensus planner",
        "- `/consensus:disable` - Disable consensus planner",
        "",
        "### Configuration",
        "Set these via `/set <key> <value>`:",
        "- `consensus_council_leader`: leader model name",
        "- `consensus_planner_threshold`: 0.0-1.0 (default 0.7)",
        "- `consensus_planner_swarm_size`: 2-5 (default 3)",
        "- `consensus_planner_timeout`: 30-600 seconds (default 180)",
        "",
        "### How Models Are Selected",
        "- **Leader**: Model pinned to consensus-planner agent, or "
        "`consensus_council_leader` config",
        "- **Advisors**: All models pinned to any agent + your active model",
    ])

    emit_info("\n".join(lines))


# =============================================================================
# Async Execution Helpers
# =============================================================================


async def _run_consensus_plan(task: str) -> dict[str, Any]:
    """Run consensus planning asynchronously.

    Args:
        task: The task to plan for

    Returns:
        Plan result dictionary
    """
    from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

    agent = ConsensusPlannerAgent()
    plan = await agent.plan_with_consensus(task)

    return {
        "plan": plan,
        "stats": agent.get_execution_stats(),
    }


async def _run_model_comparison(task: str) -> list[Any]:
    """Run model comparison asynchronously.

    Args:
        task: The task to compare on

    Returns:
        List of comparison results
    """
    from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

    agent = ConsensusPlannerAgent()
    results = await agent.compare_model_approaches(task)

    return results


async def _run_model_vote(task: str) -> str:
    """Run model vote asynchronously.

    Args:
        task: The task to vote on

    Returns:
        Best model name
    """
    from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

    agent = ConsensusPlannerAgent()
    best_model = await agent.select_best_model(task)

    return best_model


# =============================================================================
# Display Functions
# =============================================================================


def _display_consensus_plan(result: dict[str, Any]) -> None:
    """Display a consensus plan result.

    Args:
        result: The plan result dictionary
    """
    plan = result.get("plan")
    stats = result.get("stats", {})

    if not plan:
        emit_warning("No plan was generated")
        return

    # Show plan
    emit_success("🎯 Consensus Plan Generated!")
    emit_info("")
    emit_info(plan.to_markdown())

    # Show stats
    if stats:
        emit_info("")
        emit_info(f"**Execution Stats**: {stats.get('total_executions', 0)} total, "
                  f"{stats.get('consensus_executions', 0)} via consensus")


def _display_model_comparison(results: list[Any]) -> None:
    """Display model comparison results.

    Args:
        results: List of model comparison results
    """
    if not results:
        emit_warning("No comparison results available")
        return

    emit_success("🤖 Model Comparison Results")
    emit_info("")

    # Sort by confidence
    sorted_results = sorted(results, key=lambda x: x.confidence, reverse=True)

    for i, result in enumerate(sorted_results, 1):
        # Emoji based on confidence
        if result.confidence >= 0.8:
            emoji = "🔥"
        elif result.confidence >= 0.6:
            emoji = "✅"
        else:
            emoji = "⚠️"

        emit_info(f"### {emoji} #{i} {result.model_name}")
        emit_info(f"**Confidence**: {result.confidence:.0%}")
        emit_info(f"**Time**: {result.execution_time_ms:.0f}ms")
        emit_info("")
        resp = result.response
        preview = resp[:500] + "..." if len(resp) > 500 else resp
        emit_info(preview)
        emit_info("")
        emit_info("---")
        emit_info("")

    # Summary
    if len(results) > 1:
        best = sorted_results[0]
        conf = f"({best.confidence:.0%} confidence)"
        emit_success(f"🏆 Best Model: {best.model_name} {conf}")


# =============================================================================
# Help Menu Integration
# =============================================================================


def get_consensus_planner_help() -> list[tuple[str, str]]:
    """Return help entries for consensus planner commands.

    Returns:
        List of (command, description) tuples
    """
    return [
        ("/consensus_plan <task>", "Create plan using multi-model consensus"),
        ("/compare_models <task>", "Run task on multiple models, compare results"),
        ("/model_vote <task>", "Get model recommendation via consensus"),
        ("/consensus:status", "Show consensus planner configuration"),
    ]
