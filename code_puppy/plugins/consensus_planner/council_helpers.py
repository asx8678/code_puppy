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


def extract_advisor_summary(response: str) -> dict[str, str]:
    """Extract structured fields from an advisor response.

    Parses ANALYSIS:/CONFIDENCE:/CONCERNS: format into a compact dict.
    Falls back to truncating raw response if parsing fails.

    Args:
        response: Raw advisor response text

    Returns:
        dict with keys: recommendation, confidence_raw, concerns
    """
    result = {
        "recommendation": "",
        "confidence_raw": "",
        "concerns": "",
    }

    # Try structured extraction
    analysis_match = re.search(
        r"ANALYSIS:\s*(.+?)(?=\nCONFIDENCE:|\nCONCERNS:|\Z)",
        response,
        re.IGNORECASE | re.DOTALL,
    )
    confidence_match = re.search(
        r"CONFIDENCE:\s*(.+?)(?=\nANALYSIS:|\nCONCERNS:|\Z)",
        response,
        re.IGNORECASE | re.DOTALL,
    )
    concerns_match = re.search(
        r"CONCERNS:\s*(.+?)(?=\nANALYSIS:|\nCONFIDENCE:|\Z)",
        response,
        re.IGNORECASE | re.DOTALL,
    )

    if analysis_match:
        result["recommendation"] = analysis_match.group(1).strip()
    else:
        # Fallback: first 200 chars of raw response
        result["recommendation"] = response.strip()[:200]

    if confidence_match:
        result["confidence_raw"] = confidence_match.group(1).strip()

    if concerns_match:
        concern_text = concerns_match.group(1).strip()
        if concern_text.lower() not in ("none", "none.", "n/a", ""):
            result["concerns"] = concern_text

    return result


def calculate_agreement_ratio(advisor_inputs: list[AdvisorInput]) -> float:
    """Calculate how much advisors agree with each other.

    Uses a blend of:
    - Word overlap on extracted recommendations (not raw bloat)
    - Confidence proximity (similar confidence = more agreement)

    Returns:
        Agreement ratio from 0.0 (total disagreement) to 1.0 (total agreement)
    """
    if len(advisor_inputs) < 2:
        return 1.0  # Single advisor trivially agrees with itself

    # Extract just the recommendation text for comparison
    summaries = [
        extract_advisor_summary(a.response)["recommendation"]
        for a in advisor_inputs
    ]

    from code_puppy.agents.consensus_planner.utils import calculate_text_similarity

    text_scores = []
    conf_scores = []
    for i in range(len(advisor_inputs)):
        for j in range(i + 1, len(advisor_inputs)):
            text_scores.append(
                calculate_text_similarity(summaries[i], summaries[j])
            )
            # Confidence proximity: 1.0 when identical, 0.0 when 1.0 apart
            conf_diff = abs(
                advisor_inputs[i].confidence - advisor_inputs[j].confidence
            )
            conf_scores.append(1.0 - conf_diff)

    avg_text = sum(text_scores) / len(text_scores) if text_scores else 0.0
    avg_conf = sum(conf_scores) / len(conf_scores) if conf_scores else 0.0

    # Blend: 70% text similarity, 30% confidence proximity
    return avg_text * 0.7 + avg_conf * 0.3


def build_synthesis_prompt(
    task: str,
    advisor_inputs: list[AdvisorInput],
    agreement_ratio: float = 0.0,
) -> str:
    """Build a compact synthesis prompt for the leader.

    Feeds only stripped summaries so the leader context stays small.
    """
    lines = [
        f"TASK: {task}",
        "",
    ]

    # Agreement summary — one line
    if agreement_ratio >= 0.7:
        lines.append(f"AGREEMENT: HIGH ({agreement_ratio:.0%})")
    elif agreement_ratio >= 0.4:
        lines.append(f"AGREEMENT: MEDIUM ({agreement_ratio:.0%})")
    else:
        lines.append(f"AGREEMENT: LOW ({agreement_ratio:.0%})")
    lines.append("")

    lines.append(f"ADVISORS ({len(advisor_inputs)}):")
    lines.append("")

    for i, advisor in enumerate(advisor_inputs, 1):
        summary = extract_advisor_summary(advisor.response)
        lines.append(f"[{i}] {advisor.model_name} ({advisor.confidence:.0%}):")
        lines.append(f"  {summary['recommendation']}")
        if summary["concerns"]:
            lines.append(f"  ⚠ {summary['concerns']}")
        lines.append("")

    lines.extend([
        "Synthesize these inputs into ONE clear decision.",
        "",
        "FINAL DECISION: [your recommendation]",
        "SYNTHESIS RATIONALE: [why, 2-3 sentences]",
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
