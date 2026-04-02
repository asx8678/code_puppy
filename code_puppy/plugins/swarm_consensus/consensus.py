"""
Consensus detection and synthesis for Agent Swarm Consensus.

Handles the core logic of determining when agents agree,
synthesizing their responses, and identifying points of
agreement and disagreement.
"""

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import AgentResult

logger = logging.getLogger(__name__)


def detect_consensus(results: list["AgentResult"], threshold: float) -> tuple[bool, str]:
    """Detect whether the swarm has reached consensus.

    Analyzes agent responses to determine if they agree
    sufficiently to declare a consensus winner.

    Args:
        results: List of agent results
        threshold: Minimum agreement ratio (0.0-1.0)

    Returns:
        tuple: (consensus_reached, winning_answer)
    """
    if not results:
        return False, ""

    if len(results) == 1:
        return True, results[0].response_text

    # Group responses by similarity
    groups = _group_similar_responses(results)

    # Find the largest group
    largest_group = max(groups, key=lambda g: len(g))
    agreement_ratio = len(largest_group) / len(results)

    consensus_reached = agreement_ratio >= threshold

    # Synthesize the winning answer from the largest group
    if consensus_reached:
        winning_answer = synthesize_results(largest_group)
    else:
        # No clear consensus - synthesize from all results with weighting
        winning_answer = synthesize_results(results)

    return consensus_reached, winning_answer


def _group_similar_responses(results: list["AgentResult"]) -> list[list["AgentResult"]]:
    """Group results by response similarity.

    Uses a simple similarity threshold to cluster responses.

    Args:
        results: Agent results to group

    Returns:
        list: Groups of similar results
    """
    if not results:
        return []

    groups: list[list["AgentResult"]] = []
    ungrouped = list(results)

    SIMILARITY_THRESHOLD = 0.6

    while ungrouped:
        # Start a new group with the first ungrouped result
        seed = ungrouped.pop(0)
        group = [seed]

        # Find similar results
        similar_indices = []
        for i, candidate in enumerate(ungrouped):
            if _responses_similar(seed.response_text, candidate.response_text, SIMILARITY_THRESHOLD):
                group.append(candidate)
                similar_indices.append(i)

        # Remove grouped items from ungrouped (in reverse order to preserve indices)
        for i in reversed(similar_indices):
            ungrouped.pop(i)

        groups.append(group)

    return groups


def _responses_similar(text1: str, text2: str, threshold: float = 0.6) -> bool:
    """Check if two responses are similar enough to be considered the same.

    Args:
        text1: First response
        text2: Second response
        threshold: Similarity threshold (0.0-1.0)

    Returns:
        bool: True if responses are similar
    """
    # Normalize
    t1 = text1.strip().lower()
    t2 = text2.strip().lower()

    # Exact match
    if t1 == t2:
        return True

    # Extract code blocks (they matter more)
    code1 = _extract_code_blocks(text1)
    code2 = _extract_code_blocks(text2)

    # If both have code, code similarity matters more
    if code1 and code2:
        code_sim = _calculate_similarity("\n".join(code1), "\n".join(code2))
        if code_sim >= threshold:
            return True

    # Overall text similarity
    text_sim = _calculate_similarity(t1, t2)
    return text_sim >= threshold


def _extract_code_blocks(text: str) -> list[str]:
    """Extract code blocks from markdown text."""
    pattern = r"```[\w]*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    return matches


def _calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two texts.

    Uses word overlap and structural comparison.

    Args:
        text1: First text
        text2: Second text

    Returns:
        float: Similarity score (0.0-1.0)
    """
    words1 = set(text1.split())
    words2 = set(text2.split())

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union) if union else 0.0


def synthesize_results(results: list["AgentResult"]) -> str:
    """Synthesize a final answer from multiple agent results.

    Combines the best elements from each response, weighted by
    confidence scores.

    Args:
        results: Agent results to synthesize

    Returns:
        str: Synthesized answer
    """
    if not results:
        return ""

    if len(results) == 1:
        return results[0].response_text

    # Sort by confidence (highest first)
    sorted_results = sorted(results, key=lambda r: r.confidence_score, reverse=True)

    # Get the highest confidence response as base
    base = sorted_results[0]
    synthesis = base.response_text

    # If there's strong agreement, return the best answer
    if len(sorted_results) >= 2:
        sim = _calculate_similarity(base.response_text, sorted_results[1].response_text)
        if sim >= 0.7:
            return _enhance_with_unique_elements(base, sorted_results[1:])

    # Build synthesis from multiple perspectives
    parts = [
        f"## Synthesized Solution (based on {len(results)} agent perspectives)",
        "",
        "### Primary Approach",
        base.response_text,
        "",
    ]

    # Add alternative perspectives if they differ significantly
    alternatives = []
    for result in sorted_results[1:]:
        sim = _calculate_similarity(base.response_text, result.response_text)
        if sim < 0.6:  # Different enough to mention
            alternatives.append(result)

    if alternatives:
        parts.extend(["### Alternative Perspectives", ""])
        for alt in alternatives[:2]:  # Limit to top 2 alternatives
            parts.extend([
                f"**{alt.agent_name}** ({alt.approach_used}):",
                alt.response_text,
                "",
            ])

    parts.extend([
        "---",
        "",
        f"*Consensus confidence: {base.confidence_score:.2f}*",
    ])

    return "\n".join(parts)


def _enhance_with_unique_elements(base_result: "AgentResult", others: list["AgentResult"]) -> str:
    """Enhance base result with unique elements from other results.

    Args:
        base_result: Primary result to enhance
        others: Other results to pull from

    Returns:
        str: Enhanced result
    """
    base_text = base_result.response_text

    # Extract unique code blocks from others
    base_code = set(_extract_code_blocks(base_text))
    all_code: list[str] = []

    for result in others:
        for block in _extract_code_blocks(result.response_text):
            if block not in base_code:
                all_code.append(block)

    if not all_code:
        return base_text

    # Append additional code blocks with attribution
    enhanced = [base_text, "", "### Additional Implementation Details", ""]

    for i, block in enumerate(all_code[:3], 1):  # Limit to 3 additional blocks
        enhanced.extend([
            f"#### Alternative Implementation {i}",
            "```",
            block,
            "```",
            "",
        ])

    return "\n".join(enhanced)


def generate_debate_transcript(results: list["AgentResult"]) -> str:
    """Generate a transcript of the agent "debate".

    Creates a readable summary of different agent perspectives
    and their points of agreement/disagreement.

    Args:
        results: Agent results

    Returns:
        str: Formatted debate transcript
    """
    if not results:
        return "No debate transcript available."

    lines = [
        "# 🤖 Agent Swarm Debate Transcript",
        "",
        f"*Session with {len(results)} participating agents*",
        "",
    ]

    # Individual positions
    lines.extend(["## Individual Positions", ""])
    for result in results:
        confidence_emoji = "🔥" if result.confidence_score >= 0.8 else "✅" if result.confidence_score >= 0.6 else "⚠️"
        lines.extend([
            f"### {result.agent_name} ({result.approach_used}) {confidence_emoji}",
            f"**Confidence**: {result.confidence_score:.2f}",
            "",
            result.response_text[:500] + ("..." if len(result.response_text) > 500 else ""),
            "",
            "---",
            "",
        ])

    # Points of agreement
    agreements = identify_points_of_agreement(results)
    if agreements:
        lines.extend(["## ✅ Points of Agreement", ""])
        for point in agreements:
            lines.append(f"- {point}")
        lines.append("")

    # Points of disagreement
    disagreements = identify_points_of_disagreement(results)
    if disagreements:
        lines.extend(["## ⚠️ Points of Disagreement", ""])
        for topic, stances in disagreements:
            lines.append(f"**{topic}**:")
            for stance in stances:
                lines.append(f"  - {stance}")
            lines.append("")

    # Consensus summary
    consensus, winning = detect_consensus(results, 0.7)
    lines.extend([
        "## 📊 Consensus Summary",
        "",
        f"**Consensus Reached**: {'Yes ✅' if consensus else 'No ❌'}",
        "",
    ])

    return "\n".join(lines)


def identify_points_of_agreement(results: list["AgentResult"]) -> list[str]:
    """Identify common points of agreement across agents.

    Args:
        results: Agent results to analyze

    Returns:
        list: Points of agreement as strings
    """
    if len(results) < 2:
        return ["Single agent - no comparison possible."]

    agreements: list[str] = []

    # Check for common recommendations (simple keyword extraction)
    all_text = " ".join(r.response_text.lower() for r in results)

    # Look for common action verbs
    action_patterns = [
        r"(?:use|implement|apply|add|remove|refactor|extract)\s+(?:the\s+)?(\w+)",
        r"(?:should|must|recommend)\s+(?:to\s+)?(\w+)",
    ]

    common_terms: set[str] = set()
    for pattern in action_patterns:
        matches = re.findall(pattern, all_text)
        common_terms.update(matches)

    # Filter to terms that appear in majority of responses
    majority = len(results) // 2 + 1
    for term in common_terms:
        count = sum(1 for r in results if term in r.response_text.lower())
        if count >= majority:
            agreements.append(f"Use of '{term}'")

    # Check for common code patterns (extract function names, etc.)
    code_blocks = []
    for r in results:
        code_blocks.extend(_extract_code_blocks(r.response_text))

    if code_blocks:
        # Look for common function/class names
        def_pattern = r"(?:def|class)\s+(\w+)"
        all_defs: set[str] = set()
        for code in code_blocks:
            matches = re.findall(def_pattern, code)
            all_defs.update(matches)

        for name in all_defs:
            count = sum(1 for code in code_blocks if name in code)
            if count >= majority:
                agreements.append(f"Implementation of '{name}'")

    return agreements if agreements else ["General alignment on approach"]


def identify_points_of_disagreement(results: list["AgentResult"]) -> list[tuple[str, list[str]]]:
    """Identify areas where agents disagree.

    Args:
        results: Agent results to analyze

    Returns:
        list: Tuples of (topic, list_of_stances)
    """
    if len(results) < 2:
        return []

    disagreements: list[tuple[str, list[str]]] = []

    # Simple heuristic: look for different recommendations
    approach_names = set(r.approach_used for r in results)
    if len(approach_names) > 1:
        stances = [f"{r.agent_name}: {r.approach_used} perspective" for r in results]
        disagreements.append(("Reasoning approach", stances))

    # Check for different confidence levels
    confidences = [r.confidence_score for r in results]
    if max(confidences) - min(confidences) > 0.3:
        stances = [
            f"{r.agent_name}: {r.confidence_score:.2f} confidence"
            for r in sorted(results, key=lambda x: x.confidence_score, reverse=True)
        ]
        disagreements.append(("Confidence levels", stances))

    # Look for explicit disagreement markers in text
    disagreement_keywords = ["however", "but", "instead", "alternative", "disagree", "unlike"]
    for keyword in disagreement_keywords:
        agents_using = [r.agent_name for r in results if keyword in r.response_text.lower()]
        if agents_using:
            # This indicates they may be countering another view
            pass  # Could expand this analysis

    return disagreements
