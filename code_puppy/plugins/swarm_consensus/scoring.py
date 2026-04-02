"""
Confidence scoring algorithms for Agent Swarm Consensus.

Provides multiple methods for scoring agent confidence, from
linguistic analysis of responses to cross-agent consistency checks.
"""

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import AgentResult

logger = logging.getLogger(__name__)


# =============================================================================
# Certainty Markers
# =============================================================================

# Phrases that indicate high certainty
HIGH_CONFIDENCE_MARKERS = [
    "definitely",
    "certainly",
    "absolutely",
    "clearly",
    "without doubt",
    "must",
    "will",
    "always",
    "proven",
    "established",
    "optimal",
    "best solution",
    "correct approach",
    "strongly recommend",
]

# Phrases that indicate uncertainty
LOW_CONFIDENCE_MARKERS = [
    "maybe",
    "perhaps",
    "possibly",
    "might",
    "could",
    "uncertain",
    "unclear",
    "not sure",
    "depends",
    "consider",
    "alternative",
    "one option",
    "potential",
    "suggest",
    "would recommend",
    "tentative",
    "preliminary",
]

# Hedge words that reduce certainty
HEDGE_WORDS = [
    "somewhat",
    "relatively",
    "fairly",
    "quite",
    "rather",
    "pretty",
    "kind of",
    "sort of",
    "more or less",
    "roughly",
    "approximately",
]


def calculate_confidence(result: "AgentResult") -> float:
    """Calculate overall confidence score for an agent result.

    Combines multiple scoring methods:
    1. Linguistic certainty markers in the response
    2. Presence of clear structure and reasoning
    3. Absence of hedging language

    Args:
        result: The agent result to score

    Returns:
        float: Confidence score between 0.0 and 1.0
    """
    text = result.response_text.lower()

    # Base score from certainty markers
    certainty_score = score_by_certainty_markers(text)

    # Bonus for structured, thorough responses
    structure_score = score_by_structure(text)

    # Penalty for excessive hedging
    hedge_penalty = score_hedging_penalty(text)

    # Weighted combination
    confidence = (certainty_score * 0.5) + (structure_score * 0.3) - (hedge_penalty * 0.2)

    # Normalize to 0-1 range
    confidence = max(0.0, min(1.0, confidence))

    # Boost slightly for thorough, lengthy responses (up to a point)
    length_factor = min(len(result.response_text) / 2000, 0.1)
    confidence = min(1.0, confidence + length_factor)

    return round(confidence, 3)


def score_by_certainty_markers(response_text: str) -> float:
    """Score confidence based on linguistic markers.

    Analyzes the text for phrases indicating certainty vs uncertainty.

    Args:
        response_text: The agent's response text

    Returns:
        float: Score between 0.0 and 1.0
    """
    text = response_text.lower()

    # Count high confidence markers
    high_count = sum(1 for marker in HIGH_CONFIDENCE_MARKERS if marker in text)

    # Count low confidence markers
    low_count = sum(1 for marker in LOW_CONFIDENCE_MARKERS if marker in text)

    # Normalize by text length (roughly)
    text_length = len(text.split())
    if text_length == 0:
        return 0.5

    # Calculate ratio
    high_density = high_count / max(text_length / 100, 1)
    low_density = low_count / max(text_length / 100, 1)

    # Base score starts at neutral 0.5
    score = 0.5
    score += high_density * 0.3
    score -= low_density * 0.3

    # Check for explicit confidence statements
    confidence_pattern = r"(?:confidence| certainty):?\s*(\d+)%"
    match = re.search(confidence_pattern, text, re.IGNORECASE)
    if match:
        # Blend explicit confidence with calculated score
        explicit = int(match.group(1)) / 100
        score = (score * 0.3) + (explicit * 0.7)

    return max(0.0, min(1.0, score))


def score_by_structure(response_text: str) -> float:
    """Score based on structural quality indicators.

    Well-structured responses tend to be more confident and reliable.

    Args:
        response_text: The agent's response

    Returns:
        float: Structure score between 0.0 and 1.0
    """
    score = 0.0
    text = response_text

    # Has numbered or bulleted lists
    if re.search(r"(^|\n)\s*[\d\-\*]+[\.\)]?\s+", text, re.MULTILINE):
        score += 0.2

    # Has clear sections with headers
    if re.search(r"(^|\n)(#+\s+|\*\*?[^:]+:\s*\*\*?)", text, re.MULTILINE):
        score += 0.2

    # Has code blocks (for technical tasks)
    if "```" in text:
        score += 0.2

    # Reasonable length (not too short, not too long)
    word_count = len(text.split())
    if 100 <= word_count <= 2000:
        score += 0.2
    elif word_count > 100:
        score += 0.1

    # Has explicit reasoning steps
    reasoning_indicators = ["because", "therefore", "thus", "consequently", "since", "as a result"]
    reasoning_count = sum(1 for indicator in reasoning_indicators if indicator in text.lower())
    if reasoning_count >= 2:
        score += 0.2

    return min(1.0, score)


def score_hedging_penalty(response_text: str) -> float:
    """Calculate penalty for hedging/uncertain language.

    Args:
        response_text: The agent's response

    Returns:
        float: Penalty between 0.0 and 1.0 (to be subtracted)
    """
    text = response_text.lower()

    hedge_count = sum(1 for hedge in HEDGE_WORDS if hedge in text)
    text_length = len(text.split())

    if text_length == 0:
        return 0.0

    # Penalty increases with hedge density
    hedge_density = hedge_count / max(text_length / 100, 1)
    return min(0.5, hedge_density * 0.2)


def score_by_consistency(results: list["AgentResult"]) -> dict[str, float]:
    """Score agents based on consistency with the group.

    Agents whose responses align with the majority get higher scores.

    Args:
        results: List of agent results

    Returns:
        dict: Map of agent_name -> consistency score
    """
    if len(results) < 2:
        return {r.agent_name: 1.0 for r in results}

    scores: dict[str, float] = {}

    # Calculate pairwise similarity matrix
    similarities: dict[tuple[str, str], float] = {}
    for i, r1 in enumerate(results):
        for r2 in results[i + 1 :]:
            sim = _calculate_text_similarity(r1.response_text, r2.response_text)
            similarities[(r1.agent_name, r2.agent_name)] = sim
            similarities[(r2.agent_name, r1.agent_name)] = sim

    # Score each agent by average similarity to others
    for result in results:
        other_sims = [
            similarities[(result.agent_name, other.agent_name)]
            for other in results
            if other.agent_name != result.agent_name
        ]
        avg_similarity = sum(other_sims) / len(other_sims) if other_sims else 0.5
        scores[result.agent_name] = round(avg_similarity, 3)

    return scores


def _calculate_text_similarity(text1: str, text2: str) -> float:
    """Calculate simple text similarity score.

    Uses a combination of word overlap and structural similarity.
    This is a lightweight alternative to embeddings.

    Args:
        text1: First text
        text2: Second text

    Returns:
        float: Similarity between 0.0 and 1.0
    """
    # Normalize texts
    t1 = text1.lower().strip()
    t2 = text2.lower().strip()

    # Exact match
    if t1 == t2:
        return 1.0

    # Word set overlap (Jaccard-ish)
    words1 = set(t1.split())
    words2 = set(t2.split())

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    jaccard = len(intersection) / len(union)

    # Length similarity
    len1, len2 = len(t1), len(t2)
    length_sim = 1.0 - abs(len1 - len2) / max(len1, len2, 1)

    # Combined score
    return (jaccard * 0.7) + (length_sim * 0.3)


def aggregate_confidences(scores: list[float], method: str = "mean") -> float:
    """Aggregate multiple confidence scores into a single value.

    Args:
        scores: List of confidence scores
        method: Aggregation method - "mean", "median", "min", "max", "weighted"

    Returns:
        float: Aggregated confidence score
    """
    if not scores:
        return 0.0

    if method == "mean":
        return sum(scores) / len(scores)

    elif method == "median":
        sorted_scores = sorted(scores)
        n = len(sorted_scores)
        mid = n // 2
        if n % 2 == 0:
            return (sorted_scores[mid - 1] + sorted_scores[mid]) / 2
        return sorted_scores[mid]

    elif method == "min":
        return min(scores)

    elif method == "max":
        return max(scores)

    elif method == "weighted":
        # Weight by rank (higher scores get more weight)
        sorted_scores = sorted(scores, reverse=True)
        weights = [len(sorted_scores) - i for i in range(len(sorted_scores))]
        total_weight = sum(weights)
        weighted_sum = sum(s * w for s, w in zip(sorted_scores, weights))
        return weighted_sum / total_weight if total_weight > 0 else 0.0

    else:
        return sum(scores) / len(scores)


def confidence_tier(confidence: float) -> str:
    """Classify confidence into a descriptive tier.

    Args:
        confidence: Confidence score (0.0-1.0)

    Returns:
        str: Tier description
    """
    if confidence >= 0.9:
        return "very_high"
    elif confidence >= 0.75:
        return "high"
    elif confidence >= 0.6:
        return "moderate"
    elif confidence >= 0.4:
        return "low"
    else:
        return "very_low"


def format_confidence_report(results: list["AgentResult"]) -> str:
    """Generate a formatted confidence report for display.

    Args:
        results: Agent results to report on

    Returns:
        str: Formatted report
    """
    lines = ["## Agent Confidence Scores", ""]

    for result in results:
        tier = confidence_tier(result.confidence_score)
        tier_emoji = {
            "very_high": "🔥",
            "high": "✅",
            "moderate": "⚠️",
            "low": "❓",
            "very_low": "🚨",
        }.get(tier, "❓")

        lines.append(
            f"{tier_emoji} **{result.agent_name}** "
            f"({result.approach_used}): {result.confidence_score:.2f}"
        )

    # Add aggregate
    scores = [r.confidence_score for r in results]
    avg = aggregate_confidences(scores, "mean")
    lines.append(f"\n**Average Confidence**: {avg:.2f}")

    return "\n".join(lines)
