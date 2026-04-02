"""
Plugin registration for Consensus Planner.

Registers the consensus planner with Code Puppy's callback system:
- /consensus_plan slash command for plan creation
- /compare_models slash command for model comparison
- /model_vote slash command for model selection
- Agent registration for the ConsensusPlannerAgent
- Tool registration for programmatic access
- Help menu integration
- Auto-spawn integration for automatic consensus triggering
"""

import asyncio
import logging
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.config import get_value
from code_puppy.messaging import emit_info

# Import council config helpers for re-export
from code_puppy.plugins.consensus_planner.council_config import (
    get_council_consensus_enabled,
    get_council_safeguard_config,
    get_council_usage_stats,
    reset_council_usage_stats,
    set_council_leader_model,
    set_council_safeguard_config,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Registration
# =============================================================================


def _register_consensus_tools() -> list[dict[str, Any]]:
    """Register consensus planner tools.

    Returns:
        List of tool registration dictionaries
    """
    from pydantic_ai import RunContext
    tools = []
    def _register_plan_with_consensus(agent):
        @agent.tool
        async def plan_with_consensus(
            context: RunContext,
            task: str,
            force_consensus: bool = False,
        ) -> dict[str, Any]:
            """Create an execution plan using multi-model consensus.

            Args:
                task: The task to create a plan for
                force_consensus: If True, always use consensus (ignore complexity check)

            Returns:
                dict: Plan details including phases, recommendations, and confidence
            """
            from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

            agent = ConsensusPlannerAgent()

            if force_consensus:
                # Override the complexity check
                plan = await agent._create_plan_with_consensus(task, {"forced": True})
            else:
                plan = await agent.plan_with_consensus(task)

            return {
                "objective": plan.objective,
                "phases": plan.phases,
                "recommended_model": plan.recommended_model,
                "confidence": plan.confidence,
                "used_consensus": plan.used_consensus,
                "alternative_approaches": plan.alternative_approaches,
                "risks": plan.risks,
                "markdown": plan.to_markdown(),
            }

    def _register_select_model_for_task(agent):
        @agent.tool
        async def select_model_for_task(
            context: RunContext,
            task: str,
        ) -> dict[str, Any]:
            """Select the best model for a specific task using consensus.

            Args:
                task: The task description

            Returns:
                dict: Recommended model and comparison results
            """
            from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

            agent = ConsensusPlannerAgent()
            best_model = await agent.select_best_model(task)

            # Also run comparison for detailed results
            comparison = await agent.compare_model_approaches(task)

            return {
                "recommended_model": best_model,
                "comparison": [
                    {
                        "model": r.model_name,
                        "confidence": r.confidence,
                        "response": r.response[:200] + "..." if len(r.response) > 200 else r.response,
                    }
                    for r in comparison
                ],
            }

    def _register_compare_model_approaches(agent):
        @agent.tool
        async def compare_model_approaches(
            context: RunContext,
            task: str,
            models: list[str] | None = None,
        ) -> dict[str, Any]:
            """Compare how different models approach the same task.

            Args:
                task: The task to compare on
                models: Optional list of model names (uses defaults if None)

            Returns:
                dict: Comparison results for each model
            """
            from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

            agent = ConsensusPlannerAgent()
            results = await agent.compare_model_approaches(task, models)

            return {
                "task": task,
                "models_compared": len(results),
                "results": [
                    {
                        "model": r.model_name,
                        "confidence": r.confidence,
                        "execution_time_ms": r.execution_time_ms,
                        "response": r.response,
                    }
                    for r in results
                ],
                "best_model": max(results, key=lambda x: x.confidence).model_name if results else None,
            }

    tools.extend([
        {"name": "plan_with_consensus", "register_func": _register_plan_with_consensus},
        {"name": "select_model_for_task", "register_func": _register_select_model_for_task},
        {"name": "compare_model_approaches", "register_func": _register_compare_model_approaches},
    ])
    def _register_get_second_opinion(agent):
        @agent.tool
        async def get_second_opinion(
            context: RunContext,
            task: str,
            reason: str = "Uncertain about best approach",
            models: list[str] | None = None,
        ) -> dict[str, Any]:
            """Get a second opinion from multiple AI models when you're uncertain or stuck.

            Sends the task to multiple AI models (advisors), collects their opinions,
            and has a leader model synthesize a final decision. Use for architecture,
            security, or complex trade-off decisions.

            Args:
                task: The task to get consensus on
                reason: Why consensus is being requested
                models: Optional list of specific models to use

            Returns:
                dict: Consensus results including plan and recommendations
            """
            from code_puppy.plugins.consensus_planner.auto_spawn import auto_spawn_consensus_planner

            return await auto_spawn_consensus_planner(task, reason, models)
    def _register_auto_spawn_consensus(agent):
        @agent.tool
        async def auto_spawn_consensus(
            context: RunContext,
            task: str,
            trigger_context: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """Auto-spawn consensus when issues are detected.

            Args:
                task: The task to analyze and potentially get consensus on
                trigger_context: Optional context about what triggered the spawn

            Returns:
                dict: Consensus results or status if not triggered
            """
            from code_puppy.plugins.consensus_planner.auto_spawn import (
                auto_spawn_consensus_planner,
                should_auto_spawn_consensus,
            )

            should_spawn, reason = should_auto_spawn_consensus(task, None)

            if not should_spawn:
                return {
                    "success": False,
                    "spawned": False,
                    "reason": reason,
                    "message": "Auto-spawn not triggered",
                }

            full_reason = f"Auto-detected: {reason}"
            if trigger_context:
                full_reason += f" | Context: {trigger_context.get('trigger_type', 'unknown')}"

            return await auto_spawn_consensus_planner(task, full_reason)
    def _register_check_response_confidence(agent):
        @agent.tool
        async def check_response_confidence(
            context: RunContext,
            agent_response: str,
            analysis_context: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """Analyze text for uncertainty, error, or complexity markers that suggest getting a second opinion would help.

            Returns a confidence score and whether a second opinion is recommended.

            Args:
                agent_response: The response text to analyze
                analysis_context: Optional context dictionary

            Returns:
                dict: Analysis results with needs_consensus flag and details
            """
            from code_puppy.plugins.consensus_planner.auto_spawn import detect_issue_need_consensus

            result = detect_issue_need_consensus(agent_response, analysis_context)

            return {
                "needs_consensus": result.needs_consensus,
                "confidence_score": result.confidence_score,
                "trigger_type": result.trigger_type,
                "matched_patterns": result.matched_patterns,
                "reason": result.reason,
            }
    def _register_run_council_consensus(agent):
        @agent.tool
        async def run_council_consensus(
            context: RunContext,
            task: str,
            leader_model: str | None = None,
            skip_safeguards: bool = False,
        ) -> dict[str, Any]:
            """Run council consensus: advisors advise, leader decides.

            Uses all pinned models + active model as advisors.
            Uses the planner's pinned model (or specified) as leader.

            Args:
                task: The task to get consensus on
                leader_model: Optional override for leader model
                skip_safeguards: Bypass safeguards (use with caution)

            Returns:
                dict with decision, rationale, and advisor inputs
            """
            from code_puppy.plugins.consensus_planner.council_consensus import (
                run_council_consensus as run_council,
            )

            result = await run_council(task, leader_model, skip_safeguards=skip_safeguards)

            return {
                "success": result.leader_model != "blocked",
                "leader_model": result.leader_model,
                "decision": result.decision,
                "synthesis_rationale": result.synthesis_rationale,
                "confidence": result.confidence,
                "advisor_count": len(result.advisor_inputs),
                "advisor_models": [a.model_name for a in result.advisor_inputs],
                "dissenting_opinions": result.dissenting_opinions,
                "markdown": result.to_markdown(),
            }
    def _register_should_i_get_second_opinion(agent):
        @agent.tool
        async def should_i_get_second_opinion(
            context: RunContext,
            task: str,
        ) -> dict[str, Any]:
            """Check if getting a second opinion is appropriate and cost-effective for this task.

            Runs safeguard checks (usage limits, task complexity, cost estimate)
            without actually invoking the council. Call this before get_second_opinion.

            Args:
                task: The task to evaluate

            Returns:
                dict with readiness assessment
            """
            from code_puppy.plugins.consensus_planner.council_safeguards import (
                should_use_council,
                get_council_usage_stats,
            )
            result = await should_use_council(task, skip_confirm=True)
            stats = get_council_usage_stats()
            return {
                "should_use_council": result.allowed,
                "reason": result.reason,
                "confidence_score": result.confidence_score,
                "recommendation": result.recommendation,
                "estimated_cost": result.estimated_cost,
                "suggested_action": result.suggested_action,
                "usage_stats": stats,
            }
    tools.extend([
        {"name": "get_second_opinion", "register_func": _register_get_second_opinion},
        {"name": "auto_spawn_consensus", "register_func": _register_auto_spawn_consensus},
        {"name": "check_response_confidence", "register_func": _register_check_response_confidence},
        {"name": "run_council_consensus", "register_func": _register_run_council_consensus},
        {"name": "should_i_get_second_opinion", "register_func": _register_should_i_get_second_opinion},
    ])
    return tools

# =============================================================================
# Auto-Spawn Hook (monitor agent responses)
# =============================================================================


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Hook to monitor agent runs and auto-trigger consensus when needed.

    This hook analyzes agent responses after each run and can:
    - Detect uncertainty markers suggesting low confidence
    - Identify error patterns that might benefit from consensus
    - Suggest consensus planning for complex issues

    Args:
        agent_name: Name of the agent that finished
        model_name: Name of the model that was used
        session_id: Optional session identifier
        success: Whether the run completed successfully
        error: Exception if the run failed, None otherwise
        response_text: The final text response from the agent
        metadata: Optional dict with additional context
    """
    # Skip if no response to analyze
    if not response_text:
        return

    # Skip monitoring for consensus planner itself (avoid recursion)
    if agent_name in ("consensus-planner", "consensus_planner"):
        return

    # Only monitor main agents
    if agent_name not in ("code-puppy", "code_puppy"):
        return

    try:
        from code_puppy.plugins.consensus_planner.auto_spawn import (
            AutoSpawnConfig,
            detect_issue_need_consensus,
            get_consensus_auto_spawn_enabled,
        )

        # Check if auto-spawn is enabled
        if not get_consensus_auto_spawn_enabled():
            return

        # Build context for analysis
        context = {
            "agent_name": agent_name,
            "model_name": model_name,
            "success": success,
            "error": str(error) if error else None,
            "session_id": session_id,
        }
        if metadata:
            context.update(metadata)

        # Detect if consensus might help
        result = detect_issue_need_consensus(response_text, context)

        if result.needs_consensus:
            logger.info(
                f"Auto-spawn candidate detected for {agent_name}: {result.reason}"
            )
            # Emit a visible suggestion so the user knows consensus is available.
            # We suggest but don't auto-spawn to respect user flow.
            task_hint = metadata.get("task", "")[:60] if metadata else ""
            trigger_label = result.trigger_type.replace("_", " ")
            emit_info(
                f"💡 Detected **{trigger_label}** in {agent_name} response "
                f"(confidence: {result.confidence_score:.0%}). "
                f"Consider running: `/consensus_plan {task_hint}`"
            )

    except Exception as e:
        # Don't let monitoring break the main flow
        logger.debug(f"Consensus monitoring hook failed: {e}")


# =============================================================================
# Agent Registration
# =============================================================================


def _register_consensus_agent() -> list[dict[str, Any]]:
    """Register the ConsensusPlannerAgent.

    Returns:
        List of agent registration dictionaries
    """
    from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

    return [
        {
            "name": "consensus-planner",
            "class": ConsensusPlannerAgent,
        }
    ]


# =============================================================================
# Slash Command Handler
# =============================================================================


def _handle_consensus_command(command: str, name: str) -> str | bool | None:
    """Handle consensus planner slash commands.

    Args:
        command: The full command text
        name: The command name

    Returns:
        Response string, True if handled, or None if not our command
    """
    # Map of commands we handle
    consensus_commands = {
        "consensus_plan",
        "consensus",
        "compare_models",
        "model_compare",
        "multi_model",
        "model_vote",
        "select_model",
        "best_model",
        "consensus:status",
        "consensus:enable",
        "consensus:disable",
        "consensus:config",
    }

    if name not in consensus_commands:
        return None

    # Import and delegate to command handlers
    try:
        from code_puppy.command_line.consensus_planner_commands import (
            handle_compare_models_command,
            handle_consensus_plan_command,
            handle_consensus_subcommands,
            handle_model_vote_command,
        )

        if name in ("consensus_plan", "consensus"):
            return handle_consensus_plan_command(command)
        if name in ("compare_models", "model_compare", "multi_model"):
            return handle_compare_models_command(command)
        if name in ("model_vote", "select_model", "best_model"):
            return handle_model_vote_command(command)
        if name.startswith("consensus:"):
            return handle_consensus_subcommands(command)

    except Exception as e:
        logger.exception(f"Consensus command handler failed for {name}")
        return f"❌ Command failed: {e}"

    return None


# =============================================================================
# Help Menu Integration
# =============================================================================


def _get_consensus_help() -> list[tuple[str, str]]:
    """Return help entries for consensus planner commands."""
    return [
        ("/consensus_plan <task>", "Create plan using multi-model consensus"),
        ("/compare_models <task>", "Run task on multiple models, compare results"),
        ("/model_vote <task>", "Get model recommendation via consensus"),
        ("/consensus:status", "Show consensus planner configuration"),
        ("get_second_opinion()", "Tool: Get a second opinion from multiple AI models"),
        ("check_response_confidence()", "Tool: Check if response shows uncertainty"),
    ]


# =============================================================================
# Config Helpers (re-exported from council_config)
# =============================================================================

# These are re-exported from council_config.py:
# - get_council_consensus_enabled()
# - set_council_leader_model()
# - get_council_usage_stats()
# - reset_council_usage_stats()
# - get_council_safeguard_config()
# - set_council_safeguard_config()


# =============================================================================
# Model Config Hook (for preferred models integration)
# =============================================================================


def _on_load_models_config() -> dict[str, Any] | None:
    """Hook to add consensus planner metadata to model config loading.

    This allows the consensus planner to have first-class knowledge
    of which models are available for consensus operations.
    """
    from code_puppy.config import get_preferred_consensus_models

    return {
        "consensus_planner": {
            "preferred_models": get_preferred_consensus_models(),
        }
    }


# =============================================================================
# Startup Hook (for initialization)
# =============================================================================


def _on_startup() -> None:
    """Initialize the consensus planner on startup."""
    from code_puppy.config import get_consensus_planner_enabled

    if get_consensus_planner_enabled():
        logger.debug("Consensus planner initialized (enabled)")
    else:
        logger.debug("Consensus planner initialized (disabled)")


# =============================================================================
# Plugin Registration
# =============================================================================


def _register() -> None:
    """Register all consensus planner callbacks."""
    try:
        # Register tools
        register_callback("register_tools", _register_consensus_tools)
        logger.debug("Registered consensus planner tools")

        # Register agent
        register_callback("register_agents", _register_consensus_agent)
        logger.debug("Registered consensus-planner agent")

        # Register slash commands
        register_callback("custom_command", _handle_consensus_command)
        logger.debug("Registered consensus planner slash commands")

        # Register help menu
        register_callback("custom_command_help", _get_consensus_help)
        logger.debug("Registered consensus planner help entries")

        # Register startup hook
        register_callback("startup", _on_startup)
        logger.debug("Registered consensus planner startup hook")

        # Register auto-spawn monitoring hook
        register_callback("agent_run_end", _on_agent_run_end)
        logger.debug("Registered consensus planner auto-spawn monitoring")

        logger.info("Consensus Planner plugin registered successfully")

    except Exception as e:
        logger.warning(f"Failed to register consensus planner plugin: {e}")


# Register on module load
_register()
