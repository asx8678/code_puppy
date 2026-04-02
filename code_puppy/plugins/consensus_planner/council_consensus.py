"""Council with Leader consensus pattern.

Advisors: All pinned models + active model provide input
Leader: The planner's pinned model makes the final decision

This creates a hierarchical consensus where:
1. Multiple advisors (council) give their analysis/opinions
2. One leader synthesizes all inputs and makes the final decision
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from code_puppy.config import (
    get_agent_pinned_model,
    get_all_agent_pinned_models,
    get_value,
)
from code_puppy.messaging import emit_info, emit_warning
from code_puppy.model_factory import ModelFactory, make_model_settings

from .council_helpers import (
    build_synthesis_prompt,
    calculate_agreement_ratio,
    estimate_confidence,
    parse_leader_response,
)

logger = logging.getLogger(__name__)


@dataclass
class AdvisorInput:
    """Input from a single advisor model."""

    model_name: str
    response: str
    confidence: float
    execution_time_ms: float
    is_leader: bool = False


@dataclass
class CouncilDecision:
    """Final decision from the leader model."""

    leader_model: str
    decision: str
    synthesis_rationale: str
    confidence: float
    advisor_inputs: list[AdvisorInput]
    dissenting_opinions: list[str] = field(default_factory=list)
    agreement_ratio: float = 0.0

    def to_markdown(self) -> str:
        """Format as markdown report."""
        lines = [
            "# Council Decision Report",
            "",
            f"**Leader Model**: {self.leader_model}",
            f"**Confidence**: {self.confidence:.0%}",
            f"**Agreement Ratio**: {self.agreement_ratio:.0%}",
            "",
            "## Final Decision",
            "",
            f"{self.decision}",
            "",
            "## Synthesis Rationale",
            "",
            f"{self.synthesis_rationale}",
            "",
            f"## Advisor Inputs ({len(self.advisor_inputs)})",
            "",
        ]
        for advisor in self.advisor_inputs:
            if not advisor.is_leader:
                lines.extend([
                    f"### {advisor.model_name}",
                    f"- Confidence: {advisor.confidence:.0%}",
                    f"- Response: {advisor.response[:200]}...",
                    "",
                ])

        if self.dissenting_opinions:
            lines.extend([
                "## Dissenting Opinions",
                "",
            ])
            for dissent in self.dissenting_opinions:
                lines.append(f"- {dissent}")

        return "\n".join(lines)


async def run_council_consensus(
    task: str,
    leader_model: str | None = None,
    context: dict[str, Any] | None = None,
    skip_safeguards: bool = False,
    advisor_models_override: list[str] | None = None,
    timeout: float = 170.0,
) -> CouncilDecision:
    """Run council consensus: advisors advise, leader decides.

    Args:
        task: The task/question to get consensus on
        leader_model: The model that makes the final decision
            (default: planner's pinned model)
        context: Additional context
        skip_safeguards: If True, bypass safeguard checks (use with caution)
        advisor_models_override: Optional list of advisor models to use
            instead of auto-discovered
        timeout: Total time budget in seconds (default 170 to fit within
            180s outer wrapper)

    Returns:
        CouncilDecision with leader's synthesis and advisor inputs
    """
    # Calculate time budgets: 60% for advisors, 35% for leader, 5% overhead
    advisor_budget = timeout * 0.6
    leader_budget = timeout * 0.35

    # Run safeguards first (unless skipped)
    if not skip_safeguards:
        from .council_safeguards import should_use_council, record_council_run

        guard_result = await should_use_council(task, context, skip_confirm=False)

        if not guard_result.allowed:
            logger.info(f"Council blocked: {guard_result.reason}")
            emit_warning(f"⚠️ Council consensus not recommended: {guard_result.reason}")
            emit_info(f"💡 {guard_result.suggested_action}")

            # Return a "blocked" decision
            return CouncilDecision(
                leader_model=leader_model or "blocked",
                decision=f"Council consensus blocked: {guard_result.reason}",
                synthesis_rationale=guard_result.recommendation,
                confidence=0.0,
                advisor_inputs=[],
            )

        emit_info(f"✅ Safeguards passed: {guard_result.reason}")

    # Step 1: Determine leader model
    if leader_model is None:
        try:
            leader_model = _get_leader_model()
        except RuntimeError as e:
            logger.warning(f"No leader model available: {e}")
            return CouncilDecision(
                leader_model="unavailable",
                decision=f"Council consensus unavailable: {e}",
                synthesis_rationale="No models configured. Check models.json.",
                confidence=0.0,
                advisor_inputs=[],
            )

    # Step 2: Get all advisor models (pinned + active, excluding leader)
    advisor_models = _get_advisor_models(exclude_leader=leader_model)

    # Allow override of advisor models (e.g., from get_second_opinion models param)
    if advisor_models_override:
        advisor_models = advisor_models_override

    emit_info(
        f"🏛️ Council: {len(advisor_models)} advisors + 1 leader ({leader_model})"
    )

    # Step 3: Gather inputs from all advisors in parallel
    advisor_inputs = await _gather_advisor_inputs(
        task, advisor_models, timeout=advisor_budget
    )

    # Step 4: Leader synthesizes all inputs and makes decision
    decision = await _leader_synthesize(
        task, leader_model, advisor_inputs, timeout=leader_budget
    )

    # Record usage
    if not skip_safeguards:
        record_council_run(len(advisor_inputs))

    return decision


def _get_default_fallback_model() -> str:
    """Get a safe fallback model that actually exists in configuration.

    Resolution order:
    1. Currently active/session model (if it exists in config)
    2. First model in models.json
    3. Raises RuntimeError if no models available
    """
    active = get_value("active_model") or get_value("model")
    try:
        models_config = ModelFactory.load_config()
        if active and active in models_config:
            return active
        if models_config:
            return next(iter(models_config))
    except Exception:
        logger.debug(
            "Failed to load model config for fallback resolution", exc_info=True
        )

    raise RuntimeError(
        "No models available for consensus. "
        "Check your models.json configuration."
    )


def _get_leader_model() -> str:
    """Get the leader model for council consensus.

    Priority:
    1. Model pinned to consensus-planner agent
    2. Preferred consensus leader from config
    3. Active/session model or first model from models.json
    """
    # Check if consensus-planner has pinned model
    pinned = get_agent_pinned_model("consensus-planner")
    if pinned:
        return pinned

    # Check config for preferred leader
    leader = get_value("consensus_council_leader")
    if leader:
        return leader

    # Dynamic fallback
    return _get_default_fallback_model()


def _get_advisor_models(exclude_leader: str | None = None) -> list[str]:
    """Get all advisor models: pinned + active, validated against config.

    Only returns models that actually exist in the models configuration.
    Caps at MAX_ADVISORS to prevent excessive API calls and rate limiting.

    Args:
        exclude_leader: Don't include this model (it's the leader)

    Returns:
        List of unique, validated model names to use as advisors
    """
    MAX_ADVISORS = 5  # Cap to prevent rate limiting and excessive cost

    models = set()

    # Get all pinned models from all agents
    pinned = get_all_agent_pinned_models()
    for agent_name, model_name in pinned.items():
        if model_name and model_name != exclude_leader:
            models.add(model_name)

    # Get currently active model
    active = get_value("active_model") or get_value("model")
    if active and active != exclude_leader:
        models.add(active)

    # Validate models exist in configuration
    try:
        models_config = ModelFactory.load_config()
        validated = [m for m in models if m in models_config]
    except Exception as e:
        logger.warning(f"Failed to validate advisor models: {e}")
        validated = list(models)

    # Cap the number of advisors
    if len(validated) > MAX_ADVISORS:
        logger.info(
            f"Capping advisors from {len(validated)} to {MAX_ADVISORS}"
        )
        validated = validated[:MAX_ADVISORS]

    return validated


async def _create_simple_agent(model_name: str, instructions: str = "") -> Any:
    """Create a simple pydantic-ai Agent for one-shot model calls.

    Args:
        model_name: Name of the model to use
        instructions: System instructions for the agent

    Returns:
        A configured pydantic-ai Agent ready to run
    """
    from pydantic_ai import Agent

    models_config = ModelFactory.load_config()
    model = ModelFactory.get_model(model_name, models_config)
    model_settings = make_model_settings(model_name)

    return Agent(
        model=model,
        instructions=instructions,
        output_type=str,
        retries=1,
        model_settings=model_settings,
    )


async def _gather_advisor_inputs(
    task: str,
    advisor_models: list[str],
    timeout: float = 100.0,
) -> list[AdvisorInput]:
    """Gather inputs from all advisor models in parallel.

    Args:
        task: The task to analyze
        advisor_models: List of model names to use as advisors
        timeout: Overall time budget for the advisor phase

    Returns:
        List of AdvisorInput from successful advisors
    """
    semaphore = asyncio.Semaphore(2)  # Respect MAX_PARALLEL_AGENTS
    emit_info(f"⏳ Querying {len(advisor_models)} advisor models...")

    async def get_input(model_name: str) -> AdvisorInput | None:
        async with semaphore:
            try:
                start = asyncio.get_event_loop().time()

                agent = await _create_simple_agent(
                    model_name,
                    instructions=(
                        "You are an AI advisor providing analysis and recommendations."
                    ),
                )

                # Individual advisor timeout scales with overall budget
                advisor_timeout = min(60, timeout / max(1, len(advisor_models)))

                prompt = (
                    "As an advisor, analyze this task and provide your "
                    "recommendation:\n"
                    f"\nTASK: {task}\n"
                    "\nRespond in this exact format:\n"
                    "ANALYSIS: [Your analysis and recommendation in 2-3 sentences]\n"
                    "CONFIDENCE: [0-100]%\n"
                    'CONCERNS: [Any concerns or caveats, or "None"]'
                )

                result = await asyncio.wait_for(
                    agent.run(prompt), timeout=advisor_timeout
                )
                response = result.output

                elapsed = (asyncio.get_event_loop().time() - start) * 1000

                confidence = estimate_confidence(response)

                emit_info(f"  ✅ {model_name} responded ({elapsed/1000:.1f}s)")

                return AdvisorInput(
                    model_name=model_name,
                    response=response,
                    confidence=confidence,
                    execution_time_ms=elapsed,
                )
            except asyncio.TimeoutError:
                emit_info(f"  ⚠️ {model_name} timed out")
                logger.warning(f"Advisor {model_name} timed out")
                return None
            except Exception as e:
                emit_info(f"  ❌ {model_name} failed: {e}")
                logger.warning(f"Advisor {model_name} failed: {e}")
                return None

    # Create tasks for all advisors
    tasks = [asyncio.create_task(get_input(m)) for m in advisor_models]

    # Wait with overall timeout, collecting partial results
    try:
        done, pending = await asyncio.wait(tasks, timeout=timeout)
    except Exception:
        done = set()
        pending = set(tasks)

    # Cancel any still-pending tasks
    for task_obj in pending:
        task_obj.cancel()

    # Collect results from completed tasks
    advisor_inputs = []
    for task_obj in done:
        try:
            result = task_obj.result()
            if result is not None:
                advisor_inputs.append(result)
        except Exception:
            pass

    success_count = len(advisor_inputs)
    total = len(advisor_models)
    if pending:
        pending_count = len(pending)
        emit_warning(f"📊 {success_count}/{total} advisors ({pending_count} timed out)")
    else:
        emit_info(f"📊 {success_count}/{total} advisors responded")

    return advisor_inputs


async def _leader_synthesize(
    task: str,
    leader_model: str,
    advisor_inputs: list[AdvisorInput],
    timeout: float = 80.0,
) -> CouncilDecision:
    """Have the leader synthesize all advisor inputs into a final decision.

    Args:
        task: The task to synthesize
        leader_model: The model to use as leader
        advisor_inputs: List of advisor inputs to synthesize
        timeout: Maximum time to wait for leader synthesis

    Returns:
        CouncilDecision with leader's synthesis
    """
    # Calculate agreement ratio before building prompt
    agreement_ratio = calculate_agreement_ratio(advisor_inputs)

    # Build the synthesis prompt with agreement info
    synthesis_prompt = build_synthesis_prompt(task, advisor_inputs, agreement_ratio)

    emit_info(
        f"🎯 Leader ({leader_model}) synthesizing {len(advisor_inputs)} inputs..."
    )

    try:
        agent = await _create_simple_agent(
            leader_model,
            instructions=(
                "You are the leader of a council of AI advisors. "
                "Synthesize their inputs into a clear, decisive final decision."
            ),
        )
        start = asyncio.get_event_loop().time()

        result = await asyncio.wait_for(
            agent.run(synthesis_prompt), timeout=timeout
        )
        response = result.output
        elapsed = (asyncio.get_event_loop().time() - start) * 1000

        emit_info(f"✅ Leader synthesis complete ({elapsed/1000:.1f}s)")

        # Parse leader's response
        decision, rationale = parse_leader_response(response)

        # Calculate overall confidence
        avg_advisor_conf = (
            sum(a.confidence for a in advisor_inputs) / len(advisor_inputs)
            if advisor_inputs
            else 0.5
        )
        leader_conf = estimate_confidence(response)
        overall_conf = (avg_advisor_conf + leader_conf) / 2

        # Find dissenting opinions (low confidence advisors)
        dissent = [
            f"{a.model_name} had concerns: {a.response[:100]}..."
            for a in advisor_inputs
            if a.confidence < 0.5
        ]

        return CouncilDecision(
            leader_model=leader_model,
            decision=decision,
            synthesis_rationale=rationale,
            confidence=overall_conf,
            advisor_inputs=advisor_inputs,
            dissenting_opinions=dissent,
            agreement_ratio=agreement_ratio,
        )

    except asyncio.TimeoutError:
        logger.warning(f"Leader {leader_model} timed out after {timeout}s")
        emit_warning(f"⚠️ Leader synthesis timed out after {timeout:.0f}s")

        return CouncilDecision(
            leader_model=leader_model,
            decision="Error: Leader synthesis timed out",
            synthesis_rationale=f"Leader timed out after {timeout} seconds",
            confidence=0.0,
            advisor_inputs=advisor_inputs,
        )

    except Exception as e:
        logger.exception(f"Leader {leader_model} failed")
        emit_warning(f"⚠️ Leader synthesis failed: {e}")

        return CouncilDecision(
            leader_model=leader_model,
            decision="Error: Leader failed to synthesize",
            synthesis_rationale=str(e),
            confidence=0.0,
            advisor_inputs=advisor_inputs,
        )


def get_council_leader_model() -> str:
    """Get configured leader model for council consensus."""
    return _get_leader_model()


def get_council_advisor_models() -> list[str]:
    """Get all advisor models (pinned + active)."""
    return _get_advisor_models()
