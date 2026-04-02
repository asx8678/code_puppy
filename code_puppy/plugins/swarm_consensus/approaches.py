"""
Reasoning approaches for Agent Swarm Consensus.

Defines different cognitive perspectives that agents can adopt,
enabling diverse viewpoints on the same problem.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_puppy.agents.base_agent import BaseAgent

from .models import ApproachConfig

logger = logging.getLogger(__name__)


# =============================================================================
# Predefined Reasoning Approaches
# =============================================================================

APPROACH_THOROUGH = ApproachConfig(
    name="thorough",
    system_prompt_modifier="""
You are a meticulous, thorough analyst. Approach every problem with:
1. Careful step-by-step decomposition
2. Consideration of edge cases and preconditions
3. Verification of each logical step
4. Explicit acknowledgment of assumptions
5. Comprehensive coverage of all relevant factors

Your goal is completeness and correctness, not speed. Take your time
to ensure no detail is overlooked.
""".strip(),
    temperature_override=0.3,
    description="Detailed, step-by-step analysis with comprehensive coverage",
)

APPROACH_CREATIVE = ApproachConfig(
    name="creative",
    system_prompt_modifier="""
You are a creative, innovative thinker. Approach every problem with:
1. Willingness to question conventional assumptions
2. Exploration of unconventional or novel solutions
3. Cross-domain thinking - borrow ideas from other fields
4. "What if?" scenarios and thought experiments
5. Comfort with ambiguity and incomplete information

Don't be constrained by "how things are usually done." The best
solutions often come from unexpected directions.
""".strip(),
    temperature_override=0.8,
    description="Outside-the-box thinking and novel perspectives",
)

APPROACH_CRITICAL = ApproachConfig(
    name="critical",
    system_prompt_modifier="""
You are a skeptical, critical analyst playing devil's advocate. Your role:
1. Actively look for flaws, weaknesses, and failure modes
2. Question every assumption - "What could go wrong?"
3. Consider worst-case scenarios and unintended consequences
4. Demand evidence and clear reasoning for each claim
5. Identify hidden biases or premature conclusions

Your job is NOT to be negative, but to strengthen the solution by
finding its weak points before they become problems.
""".strip(),
    temperature_override=0.4,
    description="Devil's advocate, finding flaws and questioning assumptions",
)

APPROACH_PRAGMATIC = ApproachConfig(
    name="pragmatic",
    system_prompt_modifier="""
You are a pragmatic, implementation-focused engineer. Your perspective:
1. Prioritize solutions that can be implemented quickly and reliably
2. Consider maintenance burden and operational complexity
3. Favor proven patterns over experimental approaches
4. Think about the human cost - readability, onboarding, debugging
5. Accept "good enough" over perfect when it delivers value faster

Working code in production beats perfect code in theory.
""".strip(),
    temperature_override=0.5,
    description="Focus on practical implementation and delivery",
)

APPROACH_SECURITY = ApproachConfig(
    name="security",
    system_prompt_modifier="""
You are a security-focused reviewer with an adversarial mindset. Always:
1. Consider attack surfaces and trust boundaries
2. Look for injection risks, sanitization gaps, and escape hatches
3. Assume input is malicious until proven otherwise
4. Consider privilege escalation and authorization flaws
5. Evaluate data exposure and privacy implications

Security is not a feature you add later - it's a mindset that
should inform every decision.
""".strip(),
    temperature_override=0.3,
    description="Security-focused review with adversarial mindset",
)

APPROACH_PERFORMANCE = ApproachConfig(
    name="performance",
    system_prompt_modifier="""
You are a performance-optimization specialist. Your focus:
1. Algorithmic complexity and Big-O analysis
2. Resource usage patterns - memory, CPU, I/O
3. Scalability under load and large datasets
4. Caching opportunities and redundant work elimination
5. Tradeoffs between speed, memory, and maintainability

Premature optimization is bad, but informed optimization is essential.
Measure, don't guess.
""".strip(),
    temperature_override=0.4,
    description="Performance-optimized solutions and resource efficiency",
)

APPROACH_MINIMALIST = ApproachConfig(
    name="minimalist",
    system_prompt_modifier="""
You are a minimalist who values simplicity above all. Your philosophy:
1. The best code is no code - remove before adding
2. Fewer moving parts means fewer failure points
3. Simple solutions are easier to understand and maintain
4. Avoid cleverness - clarity beats elegance
5. Question every dependency and abstraction

Complexity is the enemy. Fight it ruthlessly.
""".strip(),
    temperature_override=0.4,
    description="Simplicity-first, minimal solutions",
)

# Collection of all predefined approaches
APPROACHES: list[ApproachConfig] = [
    APPROACH_THOROUGH,
    APPROACH_CREATIVE,
    APPROACH_CRITICAL,
    APPROACH_PRAGMATIC,
    APPROACH_SECURITY,
    APPROACH_PERFORMANCE,
    APPROACH_MINIMALIST,
]

# Map of approach names to configs for quick lookup
APPROACH_MAP: dict[str, ApproachConfig] = {a.name: a for a in APPROACHES}


# =============================================================================
# Task Type Mappings
# =============================================================================

TASK_APPROACH_MAPPING: dict[str, list[str]] = {
    "refactor": ["thorough", "pragmatic", "critical", "minimalist"],
    "security_review": ["security", "critical", "thorough"],
    "feature_design": ["creative", "pragmatic", "thorough"],
    "bug_fix": ["thorough", "pragmatic", "critical"],
    "performance_optimize": ["performance", "pragmatic", "minimalist"],
    "code_review": ["critical", "security", "pragmatic", "thorough"],
    "architecture": ["creative", "pragmatic", "performance", "security"],
    "testing": ["thorough", "critical", "security"],
    "default": ["thorough", "creative", "pragmatic"],
}


def get_approach_by_name(name: str) -> ApproachConfig | None:
    """Get an approach configuration by name.

    Args:
        name: The approach name (e.g., "thorough", "creative")

    Returns:
        ApproachConfig if found, None otherwise
    """
    return APPROACH_MAP.get(name)


def get_approaches_for_task(task_type: str, swarm_size: int = 3) -> list[ApproachConfig]:
    """Select appropriate approaches for a given task type.

    Args:
        task_type: Type of task (e.g., "refactor", "security_review")
        swarm_size: Number of approaches needed

    Returns:
        List of ApproachConfig objects for this task
    """
    approach_names = TASK_APPROACH_MAPPING.get(task_type, TASK_APPROACH_MAPPING["default"])

    # Get unique approaches up to swarm_size
    selected: list[ApproachConfig] = []
    for name in approach_names:
        if len(selected) >= swarm_size:
            break
        approach = get_approach_by_name(name)
        if approach and approach not in selected:
            selected.append(approach)

    # Fill remaining slots with default approaches if needed
    defaults = [
        APPROACH_THOROUGH,
        APPROACH_PRAGMATIC,
        APPROACH_CREATIVE,
        APPROACH_CRITICAL,
    ]
    for default in defaults:
        if len(selected) >= swarm_size:
            break
        if default not in selected:
            selected.append(default)

    return selected[:swarm_size]


def apply_approach(agent: "BaseAgent", approach: ApproachConfig) -> None:
    """Apply a reasoning approach to an agent.

    Modifies the agent's configuration to adopt the specified
    reasoning approach.

    Args:
        agent: The agent to configure
        approach: The approach configuration to apply
    """
    try:
        # Store original system prompt if not already saved
        if not hasattr(agent, "_original_system_prompt"):
            agent._original_system_prompt = getattr(agent, "system_prompt", "")

        # Modify system prompt with approach modifier
        original = agent._original_system_prompt
        modifier = approach.system_prompt_modifier

        # Combine prompts - approach modifier comes first to establish mindset
        new_prompt = f"{modifier}\n\n---\n\n{original}"
        agent.system_prompt = new_prompt

        # Apply temperature override if specified
        if approach.temperature_override is not None:
            if hasattr(agent, "temperature"):
                agent._original_temperature = getattr(agent, "temperature")
                agent.temperature = approach.temperature_override
            elif hasattr(agent, "config") and hasattr(agent.config, "temperature"):
                if not hasattr(agent.config, "_original_temperature"):
                    agent.config._original_temperature = agent.config.temperature
                agent.config.temperature = approach.temperature_override

        # Tag the agent with its approach
        agent._swarm_approach = approach.name

        logger.debug(f"Applied approach '{approach.name}' to agent {getattr(agent, 'name', 'unknown')}")

    except Exception as e:
        logger.warning(f"Failed to apply approach '{approach.name}': {e}")


def reset_agent_approach(agent: "BaseAgent") -> None:
    """Reset an agent to its original configuration.

    Restores the original system prompt and temperature after
    a swarm execution.

    Args:
        agent: The agent to reset
    """
    try:
        if hasattr(agent, "_original_system_prompt"):
            agent.system_prompt = agent._original_system_prompt
            delattr(agent, "_original_system_prompt")

        if hasattr(agent, "_original_temperature"):
            agent.temperature = agent._original_temperature
            delattr(agent, "_original_temperature")
        elif hasattr(agent, "config") and hasattr(agent.config, "_original_temperature"):
            agent.config.temperature = agent.config._original_temperature
            delattr(agent.config, "_original_temperature")

        if hasattr(agent, "_swarm_approach"):
            delattr(agent, "_swarm_approach")

    except Exception as e:
        logger.warning(f"Failed to reset agent approach: {e}")


def get_approach_description_summary() -> str:
    """Get a summary of all available approaches for help text."""
    lines = ["Available reasoning approaches:"]
    for approach in APPROACHES:
        lines.append(f"  • {approach.name}: {approach.description}")
    return "\n".join(lines)
