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
import re
from dataclasses import dataclass, field
from typing import Any

from code_puppy.config import (
    get_agent_pinned_model,
    get_all_agent_pinned_models,
    get_value,
)
from code_puppy.messaging import emit_info, emit_warning
from code_puppy.model_factory import ModelFactory, make_model_settings

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
) -> CouncilDecision:
    """Run council consensus: advisors advise, leader decides.

    Args:
        task: The task/question to get consensus on
        leader_model: The model that makes the final decision (default: planner's pinned model)
        context: Additional context
        skip_safeguards: If True, bypass safeguard checks (use with caution)

    Returns:
        CouncilDecision with leader's synthesis and advisor inputs
    """
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
        leader_model = _get_leader_model()

    # Step 2: Get all advisor models (pinned + active, excluding leader)
    advisor_models = _get_advisor_models(exclude_leader=leader_model)

    emit_info(f"🏛️ Council consensus: {len(advisor_models)} advisors + 1 leader ({leader_model})")

    # Step 3: Gather inputs from all advisors in parallel
    advisor_inputs = await _gather_advisor_inputs(task, advisor_models)

    # Step 4: Leader synthesizes all inputs and makes decision
    decision = await _leader_synthesize(task, leader_model, advisor_inputs)

    # Record usage
    if not skip_safeguards:
        record_council_run(len(advisor_inputs))

    return decision


def _get_leader_model() -> str:
    """Get the leader model for council consensus.

    Priority:
    1. Model pinned to consensus-planner agent
    2. Preferred consensus leader from config
    3. Default: claude-sonnet-4
    """
    # Check if consensus-planner has pinned model
    pinned = get_agent_pinned_model("consensus-planner")
    if pinned:
        return pinned

    # Check config for preferred leader
    leader = get_value("consensus_council_leader")
    if leader:
        return leader

    # Default
    return "claude-sonnet-4"


def _get_advisor_models(exclude_leader: str | None = None) -> list[str]:
    """Get all advisor models: pinned + active.

    Args:
        exclude_leader: Don't include this model (it's the leader)

    Returns:
        List of unique model names to use as advisors
    """
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

    return list(models)


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
) -> list[AdvisorInput]:
    """Gather inputs from all advisor models in parallel."""
    semaphore = asyncio.Semaphore(2)  # Respect MAX_PARALLEL_AGENTS

    async def get_input(model_name: str) -> AdvisorInput | None:
        async with semaphore:
            try:
                start = asyncio.get_event_loop().time()

                agent = await _create_simple_agent(model_name)

                prompt = f"""As an advisor, analyze this task and provide your recommendation:

TASK: {task}

Respond in this exact format:
ANALYSIS: [Your analysis and recommendation in 2-3 sentences]
CONFIDENCE: [0-100]%
CONCERNS: [Any concerns or caveats, or "None"]"""

                result = await agent.run(prompt)
                response = result.output

                elapsed = (asyncio.get_event_loop().time() - start) * 1000

                confidence = _estimate_confidence(response)

                return AdvisorInput(
                    model_name=model_name,
                    response=response,
                    confidence=confidence,
                    execution_time_ms=elapsed,
                )
            except Exception as e:
                logger.warning(f"Advisor {model_name} failed: {e}")
                return None

    tasks = [get_input(m) for m in advisor_models]
    results = await asyncio.gather(*tasks)

    return [r for r in results if r is not None]


async def _leader_synthesize(
    task: str,
    leader_model: str,
    advisor_inputs: list[AdvisorInput],
) -> CouncilDecision:
    """Have the leader synthesize all advisor inputs into a final decision."""

    # Calculate agreement ratio before building prompt
    agreement_ratio = _calculate_agreement_ratio(advisor_inputs)

    # Build the synthesis prompt with agreement info
    synthesis_prompt = _build_synthesis_prompt(task, advisor_inputs, agreement_ratio)

    try:
        agent = await _create_simple_agent(
            leader_model,
            instructions="You are the leader of a council of AI advisors. Synthesize their inputs into a clear, decisive final decision.",
        )
        start = asyncio.get_event_loop().time()

        result = await agent.run(synthesis_prompt)
        response = result.output
        elapsed = (asyncio.get_event_loop().time() - start) * 1000

        # Parse leader's response
        decision, rationale = _parse_leader_response(response)

        # Calculate overall confidence
        avg_advisor_conf = (
            sum(a.confidence for a in advisor_inputs) / len(advisor_inputs)
            if advisor_inputs
            else 0.5
        )
        leader_conf = _estimate_confidence(response)
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

    except Exception as e:
        logger.exception(f"Leader {leader_model} failed")
        emit_warning(f"Leader synthesis failed: {e}")

        return CouncilDecision(
            leader_model=leader_model,
            decision="Error: Leader failed to synthesize",
            synthesis_rationale=str(e),
            confidence=0.0,
            advisor_inputs=advisor_inputs,
        )


def _build_synthesis_prompt(
    task: str,
    advisor_inputs: list[AdvisorInput],
    agreement_ratio: float = 0.0,
) -> str:
    """Build prompt for leader to synthesize advisor inputs."""
    lines = [
        f"TASK: {task}",
        "",
    ]

    # Agreement summary
    if agreement_ratio >= 0.7:
        lines.append(f"AGREEMENT LEVEL: HIGH ({agreement_ratio:.0%}) — Advisors largely agree.")
    elif agreement_ratio >= 0.4:
        lines.append(f"AGREEMENT LEVEL: MEDIUM ({agreement_ratio:.0%}) — Advisors partially agree.")
    else:
        lines.append(f"AGREEMENT LEVEL: LOW ({agreement_ratio:.0%}) — Advisors significantly disagree.")
    lines.append("")

    lines.append("ADVISOR INPUTS:")
    lines.append("")

    for i, advisor in enumerate(advisor_inputs, 1):
        lines.extend([
            f"--- Advisor {i}: {advisor.model_name} ---",
            f"Confidence: {advisor.confidence:.0%}",
            f"Opinion: {advisor.response}",
            "",
        ])

    lines.extend([
        "YOUR ROLE:",
        "1. Review all advisor opinions",
        "2. Identify points of agreement and disagreement",
        "3. Weigh the advisors' confidence levels",
        "4. Make a FINAL DECISION that represents the best synthesis",
        "",
        "OUTPUT FORMAT:",
        "FINAL DECISION: [Your clear, decisive recommendation]",
        "",
        "SYNTHESIS RATIONALE: [Explain how you weighed the advisors' inputs, why you agree/disagree with certain points, and how you arrived at your decision]",
        "",
        "CONFIDENCE: [0-100]%",
    ])

    return "\n".join(lines)


def _parse_leader_response(response: str) -> tuple[str, str]:
    """Parse leader's response into decision and rationale."""
    decision = response
    rationale = "No separate rationale provided"

    # Try to extract sections
    if "FINAL DECISION:" in response:
        parts = response.split("FINAL DECISION:", 1)[1]
        if "SYNTHESIS RATIONALE:" in parts:
            decision, rationale = parts.split("SYNTHESIS RATIONALE:", 1)
        else:
            decision = parts

    return decision.strip(), rationale.strip()


def _estimate_confidence(response: str) -> float:
    """Estimate confidence from response text.

    First tries to parse structured CONFIDENCE: XX% format.
    Falls back to keyword matching.
    """
    # Try structured format first: CONFIDENCE: 85% or CONFIDENCE: 0.85
    match = re.search(r"CONFIDENCE:\s*(\d{1,3})\s*%", response, re.IGNORECASE)
    if match:
        value = int(match.group(1))
        return max(0.0, min(1.0, value / 100.0))

    # Try decimal format: CONFIDENCE: 0.85
    match = re.search(r"CONFIDENCE:\s*(0?\.\d+|1\.0)", response, re.IGNORECASE)
    if match:
        return max(0.0, min(1.0, float(match.group(1))))

    # Keyword fallback
    response_lower = response.lower()

    if "high confidence" in response_lower or "very confident" in response_lower:
        return 0.9
    elif "medium confidence" in response_lower or "moderately confident" in response_lower:
        return 0.7
    elif "low confidence" in response_lower or "not confident" in response_lower:
        return 0.4

    # Check for uncertainty markers
    uncertain = ["not sure", "unclear", "might be", "could be", "maybe", "uncertain"]
    if any(m in response_lower for m in uncertain):
        return 0.5

    return 0.7  # Default


def _calculate_agreement_ratio(advisor_inputs: list[AdvisorInput]) -> float:
    """Calculate how much advisors agree with each other.

    Uses word overlap similarity between all pairs of advisor responses.

    Returns:
        Agreement ratio from 0.0 (total disagreement) to 1.0 (total agreement)
    """
    if len(advisor_inputs) < 2:
        return 1.0  # Single advisor trivially agrees with itself

    from code_puppy.agents.consensus_planner.utils import calculate_text_similarity

    pair_scores = []
    for i in range(len(advisor_inputs)):
        for j in range(i + 1, len(advisor_inputs)):
            similarity = calculate_text_similarity(
                advisor_inputs[i].response,
                advisor_inputs[j].response,
            )
            pair_scores.append(similarity)

    return sum(pair_scores) / len(pair_scores) if pair_scores else 0.0


# Configuration helpers


def get_council_leader_model() -> str:
    """Get configured leader model for council consensus."""
    return _get_leader_model()


def get_council_advisor_models() -> list[str]:
    """Get all advisor models (pinned + active)."""
    return _get_advisor_models()
