"""Helper functions for council consensus pattern.

Pure utility functions for confidence estimation, agreement calculation,
prompt building, and response parsing. No state, just functions.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .council_consensus import AdvisorInput


def estimate_confidence(response: str) -> float:
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
    elif (
        "medium confidence" in response_lower
        or "moderately confident" in response_lower
    ):
        return 0.7
    elif "low confidence" in response_lower or "not confident" in response_lower:
        return 0.4

    # Check for uncertainty markers
    uncertain = ["not sure", "unclear", "might be", "could be", "maybe", "uncertain"]
    if any(m in response_lower for m in uncertain):
        return 0.5

    return 0.7  # Default


def calculate_agreement_ratio(advisor_inputs: list[AdvisorInput]) -> float:
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


def build_synthesis_prompt(
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
        lines.append(
            f"AGREEMENT LEVEL: HIGH ({agreement_ratio:.0%}) — Advisors largely agree."
        )
    elif agreement_ratio >= 0.4:
        lines.append(
            f"AGREEMENT: MEDIUM ({agreement_ratio:.0%}) — "
            "Advisors partially agree."
        )
    else:
        lines.append(
            f"AGREEMENT: LOW ({agreement_ratio:.0%}) — "
            "Advisors significantly disagree."
        )
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
        "SYNTHESIS RATIONALE: [Explain how you weighed the advisors' inputs, "
        "why you agree/disagree with certain points, and how you arrived at "
        "your decision]",
        "",
        "CONFIDENCE: [0-100]%",
    ])

    return "\n".join(lines)


def parse_leader_response(response: str) -> tuple[str, str]:
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
