"""Auto-spawn integration for ConsensusPlanner.

Automatically triggers ConsensusPlanner when the main agent:
- Detects uncertainty markers
- Encounters errors or failures
- Faces complex architectural decisions
- Needs multi-perspective validation

This module provides:
- Issue detection patterns and scoring
- Automatic consensus spawning logic
- Response monitoring hooks
- Smart trigger management
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from code_puppy.messaging import emit_info, emit_warning

if TYPE_CHECKING:
    from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

logger = logging.getLogger(__name__)


# =============================================================================
# Issue Detection Patterns
# =============================================================================

# Uncertainty markers that suggest low confidence
UNCERTAINTY_PATTERNS = {
    "not sure": 0.7,
    "unclear": 0.7,
    "might be": 0.6,
    "could be": 0.6,
    "possibly": 0.6,
    "probably": 0.5,
    "i think": 0.5,
    "maybe": 0.6,
    "uncertain": 0.8,
    "don't know": 0.8,
    "not certain": 0.7,
    "hard to say": 0.7,
    "difficult to determine": 0.7,
    "ambiguous": 0.8,
}

# Error and failure patterns
ERROR_PATTERNS = {
    "error": 0.8,
    "failed": 0.9,
    "failure": 0.9,
    "exception": 0.9,
    "doesn't work": 0.8,
    "not working": 0.8,
    "broken": 0.8,
    "crash": 0.9,
    "bug": 0.7,
    "issue": 0.6,
    "problem": 0.6,
    "timeout": 0.7,
    "stuck": 0.7,
    "cannot": 0.6,
    "unable to": 0.7,
    "didn't work": 0.8,
}

# Complexity markers suggesting need for consensus
COMPLEXITY_PATTERNS = {
    "complex": 0.7,
    "architecture": 0.8,
    "architectural": 0.8,
    "architect": 0.8,  # Used as verb: "we need to architect this"
    "design pattern": 0.7,
    "refactor": 0.6,
    "restructure": 0.7,
    "strategy": 0.6,
    "approach": 0.5,
    "multiple ways": 0.6,
    "trade-off": 0.7,
    "tradeoff": 0.7,
    "optimization": 0.6,
    "performance": 0.6,
    "scalability": 0.7,
    "security": 0.8,
    "critical": 0.7,
    "high-stakes": 0.9,
    "important decision": 0.7,
}

# Self-correction patterns suggesting re-evaluation needed
SELF_CORRECTION_PATTERNS = {
    "wait": 0.6,
    "actually": 0.6,
    "on second thought": 0.8,
    "reconsider": 0.7,
    "rethink": 0.7,
    "let me check": 0.5,
    "i was wrong": 0.9,
    "correction": 0.8,
    "scratch that": 0.7,
    "never mind": 0.6,
    "hold on": 0.5,
}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class IssueDetectionResult:
    """Result of issue detection analysis.

    Attributes:
        needs_consensus: Whether consensus is recommended
        confidence_score: Calculated confidence (0.0-1.0, lower = needs consensus)
        trigger_type: Type of trigger that fired (uncertainty, error, complexity, etc.)
        matched_patterns: List of patterns that matched
        reason: Human-readable explanation
    """

    needs_consensus: bool
    confidence_score: float
    trigger_type: str = ""
    matched_patterns: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class AutoSpawnConfig:
    """Configuration for auto-spawn behavior.

    Attributes:
        enabled: Whether auto-spawn is enabled
        triggers: List of trigger types to enable
        uncertainty_threshold: Threshold below which to trigger consensus
        ask_before_spawn: Whether to ask user before auto-spawning
    """

    enabled: bool = True
    triggers: list[str] = field(default_factory=lambda: ["uncertainty", "error", "complexity"])
    uncertainty_threshold: float = 0.6
    ask_before_spawn: bool = True


# =============================================================================
# Detection Functions
# =============================================================================


def detect_issue_need_consensus(
    agent_response: str,
    context: dict[str, Any] | None = None,
) -> IssueDetectionResult:
    """Analyze agent response for uncertainty, errors, and complexity markers.

    Args:
        agent_response: The text response from the agent to analyze
        context: Optional context dictionary with additional info

    Returns:
        IssueDetectionResult with analysis results
    """
    context = context or {}
    response_lower = agent_response.lower()

    # Track matched patterns and scores
    all_matches: list[tuple[str, float, str]] = []  # (pattern, score, category)

    # Check uncertainty patterns
    for pattern, score in UNCERTAINTY_PATTERNS.items():
        if pattern in response_lower:
            all_matches.append((pattern, score, "uncertainty"))

    # Check error patterns
    for pattern, score in ERROR_PATTERNS.items():
        if pattern in response_lower:
            all_matches.append((pattern, score, "error"))

    # Check complexity patterns
    for pattern, score in COMPLEXITY_PATTERNS.items():
        if pattern in response_lower:
            all_matches.append((pattern, score, "complexity"))

    # Check self-correction patterns
    for pattern, score in SELF_CORRECTION_PATTERNS.items():
        if pattern in response_lower:
            all_matches.append((pattern, score, "self_correction"))

    if not all_matches:
        # No patterns matched - agent seems confident
        return IssueDetectionResult(
            needs_consensus=False,
            confidence_score=0.9,
            trigger_type="none",
            matched_patterns=[],
            reason="No uncertainty, error, or complexity markers detected",
        )

    # Calculate overall confidence (inverse of max pattern score)
    max_score = max(match[1] for match in all_matches)
    confidence_score = max(0.0, 1.0 - max_score)

    # Determine primary trigger type (highest scoring category)
    best_match = max(all_matches, key=lambda x: x[1])
    trigger_type = best_match[2]

    # Get all matched pattern names
    matched_patterns = sorted(set(match[0] for match in all_matches))

    # Build reason string
    reason = (
        f"Detected {trigger_type} markers: {', '.join(matched_patterns[:3])}"
        f" (confidence score: {confidence_score:.2f})"
    )

    return IssueDetectionResult(
        needs_consensus=confidence_score < 0.6,
        confidence_score=confidence_score,
        trigger_type=trigger_type,
        matched_patterns=matched_patterns,
        reason=reason,
    )


def should_auto_spawn_consensus(
    task: str,
    agent_history: list[dict[str, Any]] | None = None,
    config: AutoSpawnConfig | None = None,
) -> tuple[bool, str]:
    """Decide if current task needs consensus based on history and content.

    Args:
        task: The current task description
        agent_history: Optional list of previous agent interactions
        config: Optional auto-spawn configuration

    Returns:
        Tuple of (should_spawn, reason)
    """
    config = config or _get_default_config()

    if not config.enabled:
        return False, "Auto-spawn is disabled"

    # Check if any triggers are enabled
    if not config.triggers:
        return False, "No auto-spawn triggers enabled"

    task_lower = task.lower()

    # Check task complexity indicators
    complexity_score = 0.0
    matched_indicators: list[str] = []

    # Only check patterns for enabled trigger types
    if "complexity" in config.triggers:
        for pattern, score in COMPLEXITY_PATTERNS.items():
            if pattern in task_lower:
                complexity_score = max(complexity_score, score)
                matched_indicators.append(pattern)

    if "uncertainty" in config.triggers:
        for pattern, score in UNCERTAINTY_PATTERNS.items():
            if pattern in task_lower:
                complexity_score = max(complexity_score, score * 0.8)  # Slightly lower weight
                matched_indicators.append(pattern)

    # Check agent history for error patterns
    error_count = 0
    if agent_history and "error" in config.triggers:
        for interaction in agent_history[-5:]:  # Check last 5 interactions
            response = interaction.get("response", "").lower()
            for pattern, _ in ERROR_PATTERNS.items():
                if pattern in response:
                    error_count += 1
                    break

    # Determine if we need consensus
    needs_consensus = False
    reason_parts: list[str] = []

    if complexity_score >= config.uncertainty_threshold:
        needs_consensus = True
        reason_parts.append(
            f"complexity score {complexity_score:.2f} >= threshold {config.uncertainty_threshold}"
        )

    if error_count >= 2:
        needs_consensus = True
        reason_parts.append(f"detected {error_count} recent errors")

    if not needs_consensus:
        return False, f"Task complexity {complexity_score:.2f} below threshold {config.uncertainty_threshold}"

    return True, f"Auto-spawn triggered: {'; '.join(reason_parts)}"


async def auto_spawn_consensus_planner(
    task: str,
    reason: str,
    models: list[str] | None = None,
) -> dict[str, Any]:
    """Actually spawn the consensus planner and return results.

    Args:
        task: The task to get consensus on
        reason: Why consensus is being requested
        models: Optional list of specific models to use

    Returns:
        Dictionary with consensus results
    """
    from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

    emit_info(f"🎯 Auto-spawning ConsensusPlanner: {reason}")

    try:
        agent = ConsensusPlannerAgent()

        # Use plan_with_consensus for complex tasks
        plan = await agent.plan_with_consensus(task)

        return {
            "success": True,
            "plan": {
                "objective": plan.objective,
                "phases": plan.phases,
                "recommended_model": plan.recommended_model,
                "confidence": plan.confidence,
                "used_consensus": plan.used_consensus,
                "alternative_approaches": plan.alternative_approaches,
                "risks": plan.risks,
                "markdown": plan.to_markdown(),
            },
            "reason": reason,
            "agent_name": "consensus-planner",
        }

    except Exception as e:
        logger.exception("Failed to auto-spawn consensus planner")
        emit_warning(f"❌ Consensus planner auto-spawn failed: {e}")

        return {
            "success": False,
            "error": str(e),
            "reason": reason,
            "agent_name": "consensus-planner",
        }


def monitor_agent_execution(
    agent_name: str,
    response: str,
    context: dict[str, Any] | None = None,
) -> IssueDetectionResult | None:
    """Hook to monitor agent responses and detect when consensus might help.

    This function can be called from the agent_run_end hook to analyze
    agent responses and suggest when consensus planning might be beneficial.

    Args:
        agent_name: Name of the agent that produced the response
        response: The agent's response text
        context: Optional context with task info, success status, etc.

    Returns:
        IssueDetectionResult if consensus might help, None otherwise
    """
    context = context or {}

    # Only monitor main agents, not the consensus planner itself
    if agent_name in ("consensus-planner", "consensus_planner"):
        return None

    # Analyze the response
    result = detect_issue_need_consensus(response, context)

    if result.needs_consensus:
        logger.info(
            f"Consensus suggested for {agent_name}: {result.reason}"
        )
        emit_info(
            f"💡 {agent_name} response suggests consensus might help: {result.trigger_type}"
        )

    return result


# =============================================================================
# Configuration Helpers
# =============================================================================


def _get_default_config() -> AutoSpawnConfig:
    """Get default auto-spawn configuration from settings."""
    from code_puppy.config import get_value

    # Check if auto-spawn is enabled
    enabled_val = get_value("consensus_auto_spawn_enabled")
    enabled = enabled_val is None or enabled_val.lower() in ("1", "true", "yes", "on")

    # Get triggers
    triggers_val = get_value("consensus_auto_spawn_triggers")
    if triggers_val:
        triggers = [t.strip() for t in triggers_val.split(",") if t.strip()]
    else:
        triggers = ["uncertainty", "error", "complexity"]

    # Get threshold
    threshold_val = get_value("consensus_uncertainty_threshold")
    try:
        threshold = float(threshold_val) if threshold_val else 0.6
        threshold = max(0.0, min(1.0, threshold))
    except (ValueError, TypeError):
        threshold = 0.6

    # Check if we should ask before spawning
    ask_val = get_value("consensus_ask_before_spawn")
    ask_before = ask_val is None or ask_val.lower() in ("1", "true", "yes", "on")

    return AutoSpawnConfig(
        enabled=enabled,
        triggers=triggers,
        uncertainty_threshold=threshold,
        ask_before_spawn=ask_before,
    )


def get_consensus_auto_spawn_enabled() -> bool:
    """Check if consensus auto-spawn is enabled.

    Returns:
        True if auto-spawn is enabled, False otherwise.
    """
    return _get_default_config().enabled


def get_consensus_auto_spawn_triggers() -> list[str]:
    """Get list of enabled auto-spawn triggers.

    Returns:
        List of trigger types (uncertainty, error, complexity, self_correction)
    """
    return _get_default_config().triggers


def get_consensus_uncertainty_threshold() -> float:
    """Get the uncertainty threshold for auto-spawning.

    Returns:
        Float between 0.0 and 1.0 (default: 0.6)
    """
    return _get_default_config().uncertainty_threshold
