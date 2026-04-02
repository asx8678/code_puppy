"""Safeguards to prevent abuse of Council Consensus.

Council Consensus is expensive (multiple API calls, latency, tokens).
These safeguards ensure it's only used when genuinely needed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from code_puppy.config import get_value, set_config_value
from code_puppy.messaging import get_message_bus

logger = logging.getLogger(__name__)

# =============================================================================
# Usage Tracking
# =============================================================================


@dataclass
class CouncilUsageStats:
    """Track council consensus usage to prevent abuse."""

    session_count: int = 0
    hour_count: int = 0
    last_hour_reset: float = field(default_factory=time.time)
    total_tokens_estimate: int = 0
    last_run_time: float = 0

    def record_run(self, advisor_count: int, estimated_tokens: int = 2000) -> None:
        """Record a council consensus run."""
        now = time.time()
        self.session_count += 1
        self.total_tokens_estimate += estimated_tokens * (advisor_count + 1)
        self.last_run_time = now

        # Reset hourly counter if needed
        if now - self.last_hour_reset > 3600:
            self.hour_count = 0
            self.last_hour_reset = now
        self.hour_count += 1


# Global usage tracker
_usage_tracker = CouncilUsageStats()

# =============================================================================
# Safeguard Checks
# =============================================================================


@dataclass
class CouncilGuardResult:
    """Result of safeguard checks."""

    allowed: bool
    reason: str
    confidence_score: float
    recommendation: str
    estimated_cost: str
    suggested_action: str


async def should_use_council(
    task: str,
    context: dict[str, Any] | None = None,
    skip_confirm: bool = False,
) -> CouncilGuardResult:
    """Comprehensive check if council consensus should be used.

    Performs multiple checks:
    1. Usage limits (per session, per hour)
    2. Task complexity analysis
    3. Recent run check (don't run too frequently)
    4. Pre-flight confidence check with single model
    5. High-stakes detection

    Args:
        task: The task to evaluate
        context: Additional context
        skip_confirm: If True, skip user confirmation (for automation)

    Returns:
        CouncilGuardResult with allow/deny and explanation
    """
    context = context or {}

    # Check 1: Usage limits
    limit_check = _check_usage_limits()
    if not limit_check.allowed:
        return limit_check

    # Check 2: Task complexity - is this worth council?
    complexity_check = _check_task_complexity(task)
    if not complexity_check.allowed:
        return complexity_check

    # Check 3: Recent runs - don't spam
    recency_check = _check_recency()
    if not recency_check.allowed:
        return recency_check

    # Check 4: Pre-flight confidence - is single model confident?
    confidence_check = await _check_single_model_confidence(task)
    if not confidence_check.allowed:
        return confidence_check

    # Check 5: High-stakes detection
    stakes_check = _check_high_stakes(task, context)

    # Combine all scores
    overall_score = _calculate_overall_score(
        [
            complexity_check.confidence_score,
            confidence_check.confidence_score,
            stakes_check.confidence_score,
        ]
    )

    # Get threshold from config
    threshold = _get_council_threshold()

    if overall_score < threshold:
        return CouncilGuardResult(
            allowed=False,
            reason=f"Overall score {overall_score:.2f} below threshold {threshold:.2f}",
            confidence_score=overall_score,
            recommendation="Use single model or standard consensus",
            estimated_cost=_estimate_cost(context.get("advisor_count", 3)),
            suggested_action="Run with standard agent",
        )

    # Check 6: User confirmation (unless skipped)
    if not skip_confirm and _should_ask_confirmation():
        advisor_count = context.get("advisor_count", 3)
        cost = _estimate_cost(advisor_count)

        confirmed = await _request_user_confirmation(
            f"🤔 Council Consensus Recommended\n\n"
            f"This will use {advisor_count} advisor models + 1 leader.\n"
            f"Estimated cost: ~{cost}\n"
            f"Reason: {stakes_check.reason}\n\n"
            f"Use council consensus for this task?",
            options=["Yes", "No", "Always", "Never"],
        )

        if confirmed == "No":
            return CouncilGuardResult(
                allowed=False,
                reason="User declined council consensus",
                confidence_score=overall_score,
                recommendation="Use single model",
                estimated_cost=cost,
                suggested_action="Proceed with single model",
            )
        elif confirmed == "Never":
            _set_user_preference("council_confirm", "never")
        elif confirmed == "Always":
            _set_user_preference("council_confirm", "always")

    # All checks passed
    return CouncilGuardResult(
        allowed=True,
        reason=f"All safeguards passed (score: {overall_score:.2f})",
        confidence_score=overall_score,
        recommendation="Proceed with council consensus",
        estimated_cost=_estimate_cost(context.get("advisor_count", 3)),
        suggested_action="Run council consensus",
    )


def _check_usage_limits() -> CouncilGuardResult:
    """Check if usage limits are exceeded."""
    global _usage_tracker

    max_per_session = int(get_value("council_max_per_session") or "10")
    max_per_hour = int(get_value("council_max_per_hour") or "20")

    if _usage_tracker.session_count >= max_per_session:
        return CouncilGuardResult(
            allowed=False,
            reason=f"Session limit reached ({max_per_session} runs)",
            confidence_score=0.0,
            recommendation="Use single model for remaining tasks",
            estimated_cost="N/A",
            suggested_action="Contact admin to increase limits or wait for new session",
        )

    if _usage_tracker.hour_count >= max_per_hour:
        return CouncilGuardResult(
            allowed=False,
            reason=f"Hourly limit reached ({max_per_hour} runs)",
            confidence_score=0.0,
            recommendation="Wait or use single model",
            estimated_cost="N/A",
            suggested_action=(
                f"Try again in "
                f"{int(3600 - (time.time() - _usage_tracker.last_hour_reset))}s"
            ),
        )

    return CouncilGuardResult(
        allowed=True,
        reason="Within usage limits",
        confidence_score=1.0,
        recommendation="Proceed",
        estimated_cost="",
        suggested_action="",
    )


def _check_task_complexity(task: str) -> CouncilGuardResult:
    """Analyze task complexity to determine if council is warranted."""
    task_lower = task.lower()

    # High-value keywords that warrant council
    high_value = {
        "architecture": 0.9,
        "architect": 0.9,
        "security": 0.95,
        "vulnerability": 0.95,
        "refactor": 0.6,
        "redesign": 0.7,
        "strategy": 0.7,
        "roadmap": 0.7,
        "migration": 0.8,
        "database": 0.6,
        "performance": 0.6,
        "optimization": 0.6,
    }

    # Low-value keywords - probably not worth council
    low_value = {
        "fix typo": 0.1,
        "documentation": 0.2,
        "readme": 0.1,
        "comment": 0.2,
        "format": 0.1,
        "lint": 0.1,
    }

    score = 0.5  # Default middle
    matched_high = []
    matched_low = []

    for keyword, value in high_value.items():
        if keyword in task_lower:
            score = max(score, value)
            matched_high.append(keyword)

    for keyword, value in low_value.items():
        if keyword in task_lower:
            score = min(score, value)
            matched_low.append(keyword)

    # If low-value keywords dominate, deny
    if matched_low and not matched_high:
        return CouncilGuardResult(
            allowed=False,
            reason=f"Task appears simple ({', '.join(matched_low)})",
            confidence_score=score,
            recommendation="Use single model",
            estimated_cost="",
            suggested_action="Standard agent can handle this",
        )

    # If high-value keywords present, boost score
    if matched_high:
        score = max(score, 0.7)

    return CouncilGuardResult(
        allowed=True,
        reason=f"Complexity score: {score:.2f}"
        + (f" ({', '.join(matched_high)})" if matched_high else ""),
        confidence_score=score,
        recommendation=(
            "Proceed with evaluation" if score > 0.6 else "Consider single model"
        ),
        estimated_cost="",
        suggested_action="",
    )


def _check_recency() -> CouncilGuardResult:
    """Check if we ran council too recently."""
    global _usage_tracker

    min_interval = int(get_value("council_min_interval_seconds") or "30")
    time_since_last = time.time() - _usage_tracker.last_run_time

    if _usage_tracker.last_run_time > 0 and time_since_last < min_interval:
        return CouncilGuardResult(
            allowed=False,
            reason=f"Council ran {int(time_since_last)}s ago (min: {min_interval}s)",
            confidence_score=0.0,
            recommendation="Wait or use single model",
            estimated_cost="",
            suggested_action=f"Wait {int(min_interval - time_since_last)} seconds",
        )

    return CouncilGuardResult(
        allowed=True,
        reason="Sufficient time since last run",
        confidence_score=1.0,
        recommendation="Proceed",
        estimated_cost="",
        suggested_action="",
    )


async def _check_single_model_confidence(task: str) -> CouncilGuardResult:
    """Quick check with single model to see if it's confident.

    If single model is already confident (>0.8), council may not be needed.
    """
    try:
        from pydantic_ai import Agent

        from code_puppy.model_factory import ModelFactory, make_model_settings

        # Use a fast model for pre-check
        model_name = get_value("council_preflight_model")
        if not model_name:
            try:
                from code_puppy.plugins.consensus_planner.council_consensus import (
                    _get_default_fallback_model,
                )
                model_name = _get_default_fallback_model()
            except RuntimeError:
                return CouncilGuardResult(
                    allowed=True,
                    reason="Pre-flight check skipped: no fallback model available",
                    confidence_score=0.5,
                    recommendation="Proceed with caution",
                    estimated_cost="",
                    suggested_action="",
                )
        models_config = ModelFactory.load_config()
        model = ModelFactory.get_model(model_name, models_config)
        model_settings = make_model_settings(model_name)

        agent = Agent(
            model=model,
            output_type=str,
            retries=1,
            model_settings=model_settings,
        )

        prompt = f"""Quickly assess this task. Respond with ONLY:
CONFIDENCE: high/medium/low
REASON: one sentence

Task: {task}"""

        result = await agent.run(prompt)
        response_lower = result.output.lower()

        if "high" in response_lower:
            return CouncilGuardResult(
                allowed=False,
                reason="Single model has high confidence",
                confidence_score=0.9,
                recommendation="Single model can handle this",
                estimated_cost="",
                suggested_action="Use standard agent",
            )
        elif "medium" in response_lower:
            return CouncilGuardResult(
                allowed=True,
                reason="Single model has medium confidence - council may help",
                confidence_score=0.6,
                recommendation="Consider council",
                estimated_cost="",
                suggested_action="",
            )
        else:  # low
            return CouncilGuardResult(
                allowed=True,
                reason="Single model has low confidence - council recommended",
                confidence_score=0.3,
                recommendation="Use council consensus",
                estimated_cost="",
                suggested_action="",
            )

    except Exception as e:
        logger.warning(f"Pre-flight check failed: {e}")
        # If check fails, allow council but with lower confidence
        return CouncilGuardResult(
            allowed=True,
            reason="Pre-flight check failed, allowing council",
            confidence_score=0.5,
            recommendation="Proceed with caution",
            estimated_cost="",
            suggested_action="",
        )


def _check_high_stakes(task: str, context: dict) -> CouncilGuardResult:
    """Check if this is a high-stakes situation."""
    task_lower = task.lower()

    # High-stakes patterns
    high_stakes = [
        "production",
        "deploy",
        "release",
        "security",
        "auth",
        "password",
        "encrypt",
        "payment",
        "billing",
        "user data",
        "database migration",
        "breaking change",
        "api change",
    ]

    stakes_score = 0.5
    matched = []

    for pattern in high_stakes:
        if pattern in task_lower:
            stakes_score = min(1.0, stakes_score + 0.2)
            matched.append(pattern)

    if matched:
        return CouncilGuardResult(
            allowed=True,
            reason=f"High-stakes task detected: {', '.join(matched[:3])}",
            confidence_score=stakes_score,
            recommendation="Council consensus strongly recommended",
            estimated_cost="",
            suggested_action="Proceed with council",
        )

    return CouncilGuardResult(
        allowed=True,
        reason="Standard stakes",
        confidence_score=0.5,
        recommendation="Evaluate normally",
        estimated_cost="",
        suggested_action="",
    )


def _calculate_overall_score(scores: list[float]) -> float:
    """Calculate overall confidence score from multiple checks."""
    if not scores:
        return 0.5
    # Weighted average (can be tuned)
    weights = [0.3, 0.4, 0.3]  # complexity, confidence, stakes
    weighted = sum(s * w for s, w in zip(scores, weights))
    return weighted


def _get_council_threshold() -> float:
    """Get threshold from config."""
    try:
        return float(get_value("council_threshold") or "0.65")
    except (ValueError, TypeError):
        return 0.65


def _estimate_cost(advisor_count: int) -> str:
    """Estimate cost of running council."""
    # Rough estimates
    tokens_per_call = 2000  # Input + output
    cost_per_1k = 0.015  # Average across models
    total_tokens = tokens_per_call * (advisor_count + 1)  # +1 for leader
    cost = (total_tokens / 1000) * cost_per_1k
    return f"~${cost:.3f} ({total_tokens} tokens)"


def _should_ask_confirmation() -> bool:
    """Check if we should ask user for confirmation."""
    pref = get_value("council_confirm")
    if pref == "always":
        return False
    if pref == "never":
        return False
    return True  # Default: ask


async def _request_user_confirmation(
    description: str,
    options: list[str] | None = None,
) -> str:
    """Request confirmation from user via message bus.

    Args:
        description: The description to show
        options: List of options (default: ["Yes", "No"])

    Returns:
        Selected option string
    """
    options = options or ["Yes", "No"]
    bus = get_message_bus()

    try:
        # Use request_selection for multiple options
        if len(options) > 2:
            idx, selected = await bus.request_selection(
                prompt_text=description,
                options=options,
                allow_cancel=True,
            )
            if idx == -1:
                return "No"  # Cancelled
            return selected
        else:
            # Use request_confirmation for yes/no
            confirmed, _ = await bus.request_confirmation(
                title="Council Consensus Confirmation",
                description=description,
                options=options,
                allow_feedback=False,
            )
            return "Yes" if confirmed else "No"
    except Exception as e:
        logger.warning(f"User confirmation failed: {e}")
        # Default to No on error (safe fallback)
        return "No"


def _set_user_preference(key: str, value: str) -> None:
    """Set user preference."""
    set_config_value(key, value)


# =============================================================================
# Public API
# =============================================================================


def get_council_usage_stats() -> dict[str, Any]:
    """Get current usage statistics."""
    global _usage_tracker
    return {
        "session_count": _usage_tracker.session_count,
        "hour_count": _usage_tracker.hour_count,
        "total_tokens_estimate": _usage_tracker.total_tokens_estimate,
        "last_run_ago_seconds": (
            int(time.time() - _usage_tracker.last_run_time)
            if _usage_tracker.last_run_time
            else None
        ),
    }


def record_council_run(advisor_count: int) -> None:
    """Record that council was run."""
    global _usage_tracker
    _usage_tracker.record_run(advisor_count)


def reset_council_stats() -> None:
    """Reset usage statistics (for testing)."""
    global _usage_tracker
    _usage_tracker = CouncilUsageStats()
