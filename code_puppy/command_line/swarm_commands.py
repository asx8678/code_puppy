"""Command handlers for swarm operations.

Provides slash command integration for Agent Swarm Consensus:
- /swarm <prompt> - Run swarm consensus on a task
- /swarm:enable - Enable automatic swarm mode
- /swarm:disable - Disable automatic swarm mode
- /swarm:status - Show swarm configuration
- /swarm:interactive - Launch TUI for visual swarm execution

Handlers follow the @register_command pattern for automatic discovery.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from code_puppy.command_line.command_registry import register_command
from code_puppy.messaging import emit_error, emit_info, emit_success, emit_warning

logger = logging.getLogger(__name__)

# Lazy imports to avoid circular dependencies
_orchestrator = None


def _get_orchestrator():
    """Get or create the swarm orchestrator lazily."""
    global _orchestrator
    if _orchestrator is None:
        from code_puppy.plugins.swarm_consensus.config import (
            get_consensus_threshold,
            get_default_swarm_size,
            get_swarm_timeout_seconds,
        )
        from code_puppy.plugins.swarm_consensus.models import SwarmConfig
        from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator

        config = SwarmConfig(
            swarm_size=get_default_swarm_size(),
            consensus_threshold=get_consensus_threshold(),
            timeout_seconds=get_swarm_timeout_seconds(),
        )
        _orchestrator = SwarmOrchestrator(config)
    return _orchestrator


# =============================================================================
# Command Handlers
# =============================================================================


@register_command(
    name="swarm",
    description="Run agent swarm consensus on a task",
    usage="/swarm <task>, /swarm:status, /swarm:enable, /swarm:disable",
    aliases=["swarm:status", "swarm:enable", "swarm:disable", "swarm:interactive"],
    category="advanced",
    detailed_help="""
Run multiple agents with different approaches and synthesize consensus.

Subcommands:
    /swarm <task>          - Run swarm on a task description
    /swarm:interactive     - Launch TUI for visual swarm execution
    /swarm:status          - Show current swarm configuration
    /swarm:enable          - Enable automatic swarm for critical tasks
    /swarm:disable         - Disable automatic swarm mode

Examples:
    /swarm refactor this function to use async/await
    /swarm:interactive
    /swarm:status
    """,
)
def handle_swarm_command(command: str) -> bool:
    """Main handler for all /swarm commands.

    Args:
        command: The full command string

    Returns:
        True if handled, False otherwise
    """
    # Normalize the command
    cmd_parts = command.split(None, 1)
    cmd_base = cmd_parts[0] if cmd_parts else "/swarm"

    # Extract subcommand if present
    subcommand = ""
    if ":" in cmd_base:
        subcommand = cmd_base.split(":", 1)[1]

    # Route to appropriate handler
    if subcommand == "status":
        return _show_swarm_status()

    if subcommand == "enable":
        return _enable_swarm()

    if subcommand == "disable":
        return _disable_swarm()

    if subcommand == "interactive":
        return _run_swarm_interactive()

    if subcommand == "help":
        return _show_swarm_help()

    # Default: run swarm on the provided prompt
    prompt = cmd_parts[1] if len(cmd_parts) > 1 else ""
    if not prompt:
        emit_warning("Usage: /swarm <task description>")
        emit_info("Examples:")
        emit_info("  /swarm refactor this function")
        emit_info("  /swarm review this code for security issues")
        emit_info("  /swarm:interactive - for visual execution")
        return True

    return _run_swarm_text(prompt)


def _show_swarm_status() -> bool:
    """Display current swarm configuration."""
    try:
        from code_puppy.plugins.swarm_consensus.config import (
            get_consensus_threshold,
            get_default_swarm_size,
            get_swarm_enabled,
            get_swarm_timeout_seconds,
        )

        enabled = get_swarm_enabled()
        size = get_default_swarm_size()
        threshold = get_consensus_threshold()
        timeout = get_swarm_timeout_seconds()

        status_emoji = "✅" if enabled else "❌"

        lines = [
            "## 🤖 Agent Swarm Consensus Status",
            "",
            f"{status_emoji} **Enabled**: {enabled}",
            f"📊 **Swarm Size**: {size} agents",
            f"🎯 **Consensus Threshold**: {threshold:.0%}",
            f"⏱️ **Timeout**: {timeout}s",
            "",
            "### Available Approaches",
            "- thorough: Deep analysis with attention to edge cases",
            "- creative: Novel solutions and out-of-the-box thinking",
            "- critical: Security-focused, finds vulnerabilities",
            "- pragmatic: Balanced approach, practical solutions",
            "- security: Specialized security review",
            "- performance: Optimization-focused analysis",
            "- minimalist: Simple, clean solutions",
            "",
            "### Usage",
            "- `/swarm <task>` - Run consensus on a task",
            "- `/swarm:interactive` - Launch visual TUI",
            "- `/swarm:enable` - Auto-run on critical tasks",
            "- `/swarm:disable` - Disable auto mode",
        ]

        emit_info("\n".join(lines))
        return True

    except Exception as e:
        emit_error(f"Failed to get swarm status: {e}")
        return True


def _enable_swarm() -> bool:
    """Enable automatic swarm mode."""
    try:
        from code_puppy.plugins.swarm_consensus.config import set_swarm_enabled

        set_swarm_enabled(True)
        emit_success("✅ Swarm consensus mode enabled!")
        emit_info("Critical tasks will now use ensemble programming automatically.")
        return True

    except Exception as e:
        emit_error(f"Failed to enable swarm: {e}")
        return True


def _disable_swarm() -> bool:
    """Disable automatic swarm mode."""
    try:
        from code_puppy.plugins.swarm_consensus.config import set_swarm_enabled

        set_swarm_enabled(False)
        emit_success("❌ Swarm consensus mode disabled.")
        emit_info("Tasks will use single-agent execution.")
        return True

    except Exception as e:
        emit_error(f"Failed to disable swarm: {e}")
        return True


def _run_swarm_text(prompt: str) -> bool:
    """Run swarm and display text results.

    Args:
        prompt: The task prompt to run

    Returns:
        True (handled)
    """
    emit_info(f"🤖 Running swarm consensus for: {prompt[:60]}...")

    try:
        # Run swarm asynchronously, handling the case where an event loop
        # is already running (e.g., TUI/REPL context).
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already inside an async context — run in a separate thread
            # with its own event loop to avoid "asyncio.run() cannot be
            # called from a running event loop" crashes.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(asyncio.run, _execute_swarm_async(prompt)).result()
        else:
            result = asyncio.run(_execute_swarm_async(prompt))
        _display_swarm_result(result)
        return True

    except Exception as e:
        logger.exception("Swarm execution failed")
        emit_error(f"Swarm execution failed: {e}")
        return True


def _run_swarm_interactive(prompt: str = "") -> bool:
    """Launch TUI for visual swarm execution.

    Args:
        prompt: Optional initial prompt (user will be prompted if empty)

    Returns:
        True (handled)
    """
    from code_puppy.tools.command_runner import set_awaiting_user_input

    # Get prompt if not provided
    if not prompt:
        try:
            from prompt_toolkit import prompt as pt_prompt

            set_awaiting_user_input(True)
            prompt = pt_prompt("Enter task for swarm consensus: ")
            set_awaiting_user_input(False)

            if not prompt.strip():
                emit_warning("No prompt provided. Cancelling.")
                return True
        except (KeyboardInterrupt, EOFError):
            set_awaiting_user_input(False)
            return True
        except Exception as e:
            set_awaiting_user_input(False)
            emit_error(f"Failed to get prompt: {e}")
            return True

    # Launch TUI
    set_awaiting_user_input(True)
    try:
        from code_puppy.tui.screens.swarm_screen import run_swarm_screen

        result = asyncio.run(run_swarm_screen(prompt))

        if result and isinstance(result, dict):
            action = result.get("action")
            swarm_result = result.get("result")

            if action == "accept" and swarm_result:
                emit_success("✓ Consensus result accepted!")
                # Output the final answer
                emit_info("\n[bold]Final Answer:[/bold]")
                emit_info(swarm_result.final_answer)
            else:
                emit_info("Swarm execution cancelled.")
        else:
            emit_info("Swarm execution completed.")

    except Exception as e:
        emit_error(f"Interactive swarm failed: {e}")
        logger.exception("Interactive swarm error")

    finally:
        set_awaiting_user_input(False)

    return True


def _show_swarm_help() -> bool:
    """Show detailed help for swarm commands."""
    help_text = """## 🤖 Agent Swarm Consensus Help

**Ensemble programming with multiple AI perspectives**

### Commands
- `/swarm <task>` - Run swarm consensus on a task
- `/swarm:interactive` - Launch visual TUI with real-time updates
- `/swarm:status` - Show current configuration
- `/swarm:enable` - Enable automatic swarm for critical tasks
- `/swarm:disable` - Disable automatic swarm mode

### How It Works
1. Spawns multiple agents with different reasoning approaches
2. Each agent analyzes the task from their perspective
3. Confidence scores calculated for each response
4. Consensus detection finds agreement between agents
5. Final answer synthesized from best contributions

### Approaches
- **thorough**: Deep analysis, edge cases, comprehensive
- **creative**: Novel solutions, out-of-the-box thinking
- **critical**: Security focus, finds vulnerabilities
- **pragmatic**: Balanced, practical, maintainable
- **security**: Specialized security review
- **performance**: Optimization focus
- **minimalist**: Simple, clean, elegant

### Use Cases
- Code review and refactoring decisions
- Architecture and design choices
- Security vulnerability analysis
- Complex bug investigation
- Critical code paths
"""
    emit_info(help_text)
    return True


# =============================================================================
# Async Execution Helper
# =============================================================================


async def _execute_swarm_async(prompt: str, task_type: str = "default") -> Any:
    """Execute swarm asynchronously.

    Args:
        prompt: Task prompt
        task_type: Type of task

    Returns:
        SwarmResult
    """
    orchestrator = _get_orchestrator()
    return await orchestrator.execute_swarm(
        task_prompt=prompt,
        task_type=task_type,
    )


# =============================================================================
# Result Display
# =============================================================================


def _display_swarm_result(result) -> None:
    """Display swarm result to the user.

    Args:
        result: SwarmResult to display
    """
    from rich.text import Text

    # Header
    if result.consensus_reached:
        emit_success("🎯 Consensus reached!")
    else:
        emit_warning("⚠️ No consensus reached - showing best synthesis")

    # Stats
    avg_conf = result.get_average_confidence()
    agreement = result.get_agreement_ratio()

    emit_info(f"Average Confidence: {avg_conf:.0%}")
    emit_info(f"Agreement Ratio: {agreement:.0%}")

    if result.execution_stats:
        total_time = result.execution_stats.get("total_time_ms", 0)
        successful = result.execution_stats.get("successful_runs", 0)
        total = len(result.individual_results)
        emit_info(f"Execution Time: {total_time:.0f}ms")
        emit_info(f"Success Rate: {successful}/{total} agents")

    emit_info("")

    # Final answer
    emit_info(Text.from_markup("[bold cyan]Final Answer:[/bold cyan]"))
    emit_info(result.final_answer)

    # Individual contributions (collapsed in text mode)
    if result.individual_results:
        emit_info("")
        emit_info(Text.from_markup("[dim]Agent Contributions:[/dim]"))
        for agent_result in result.individual_results:
            emoji = "🔥" if agent_result.confidence_score >= 0.8 else "✅"
            if agent_result.confidence_score < 0.4:
                emoji = "⚠️"

            emit_info(
                f"{emoji} {agent_result.agent_name} ({agent_result.approach_used}): "
                f"{agent_result.confidence_score:.0%}"
            )


# =============================================================================
# Custom Command Hook (for callback system)
# =============================================================================


def handle_swarm_custom_command(command: str, name: str) -> str | bool | None:
    """Handle swarm commands via the callback system.

    This function is registered via the custom_command hook to handle
    /swarm commands when they come through the plugin system.

    Args:
        command: Full command string
        name: Command name

    Returns:
        Response string, True if handled, or None if not our command
    """
    # Only handle swarm-related commands
    if not name.startswith("swarm"):
        return None

    # Reconstruct full command and delegate to main handler
    full_command = command if command.startswith("/") else f"/{command}"
    result = handle_swarm_command(full_command)

    # Convert bool result to expected callback format
    if result:
        return True
    return None


def get_swarm_help_entries() -> list[tuple[str, str]]:
    """Return help entries for swarm commands.

    Returns:
        List of (command, description) tuples
    """
    return [
        ("/swarm <task>", "Run agent swarm consensus on a task"),
        ("/swarm:interactive", "Launch visual TUI for swarm execution"),
        ("/swarm:status", "Show swarm configuration"),
        ("/swarm:enable", "Enable automatic swarm mode"),
        ("/swarm:disable", "Disable automatic swarm mode"),
    ]
