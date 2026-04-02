"""Utility functions for the Consensus Planner Agent."""

from __future__ import annotations

import re
from typing import Any

# Complexity keywords that indicate a task might need consensus
COMPLEXITY_KEYWORDS = {
    "architecture": 0.8,
    "design": 0.7,
    "refactor": 0.6,
    "security": 0.9,
    "review": 0.5,
    "audit": 0.8,
    "performance": 0.6,
    "optimize": 0.6,
    "strategy": 0.7,
    "planning": 0.6,
    "critical": 0.9,
    "important": 0.6,
    "complex": 0.7,
    "difficult": 0.6,
    "challenging": 0.6,
    "multi-step": 0.5,
    "integration": 0.6,
    "migration": 0.8,
    "upgrade": 0.5,
}

# Uncertainty markers that suggest we need consensus
UNCERTAINTY_MARKERS = [
    "not sure",
    "unclear",
    "ambiguous",
    "might be",
    "could be",
    "maybe",
    "possibly",
    "alternatively",
    "on the other hand",
    "trade-off",
    "balance between",
]


def analyze_task_complexity(task: str) -> dict[str, Any]:
    """Quick analysis of task complexity.

    Args:
        task: The task description

    Returns:
        Dictionary with complexity analysis
    """
    task_lower = task.lower()

    # Score complexity
    complexity_score = 0.0
    matched_keywords = []

    for keyword, weight in COMPLEXITY_KEYWORDS.items():
        count = task_lower.count(keyword)
        if count > 0:
            complexity_score = max(complexity_score, weight * min(count, 2))
            matched_keywords.extend([keyword] * count)

    # Detect uncertainty
    uncertainty_count = sum(task_lower.count(m) for m in UNCERTAINTY_MARKERS)

    return {
        "complexity_score": min(complexity_score, 1.0),
        "matched_keywords": list(set(matched_keywords)),
        "uncertainty_detected": uncertainty_count > 0,
        "task_length": len(task),
        "estimated_phases": max(1, int(complexity_score * 3)),
    }


def estimate_confidence_from_response(response: str) -> float:
    """Estimate confidence from response text.

    Args:
        response: The model response text

    Returns:
        Estimated confidence score (0.0-1.0)
    """
    response_lower = response.lower()

    # High confidence indicators
    high_conf = ["high confidence", "strongly recommend", "definitely", "clearly"]
    medium_conf = ["medium confidence", "reasonably", "likely", "probably"]
    low_conf = ["low confidence", "uncertain", "not sure", "might", "could"]

    high_count = sum(1 for h in high_conf if h in response_lower)
    medium_count = sum(1 for m in medium_conf if m in response_lower)
    low_count = sum(1 for low in low_conf if low in response_lower)

    # Calculate weighted score
    score = 0.5  # Default
    score += high_count * 0.15
    score += medium_count * 0.05
    score -= low_count * 0.15

    return max(0.0, min(1.0, score))


def calculate_text_similarity(text1: str, text2: str) -> float:
    """Calculate simple text similarity using word overlap.

    Args:
        text1: First text
        text2: Second text

    Returns:
        Similarity score (0.0-1.0)
    """
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union) if union else 0.0


def extract_phases_from_response(response: str) -> list[dict[str, Any]]:
    """Extract structured phases from a response.

    Args:
        response: The response text to parse

    Returns:
        List of phase dictionaries
    """
    phases = []

    # Look for patterns like "Phase 1:", "### Phase 1", "1. Phase Name"
    phase_pattern = r"(?:Phase\s+(\d+)[.:]|###\s+(?:Phase\s+)?(\d+)[.:]|(\d+)[.])\s*(.+?)(?=\n|$)"
    matches = list(re.finditer(phase_pattern, response, re.IGNORECASE))

    if matches:
        for i, match in enumerate(matches):
            phase_name = match.group(4).strip()

            # Extract description until next phase or end
            start_pos = match.end()
            if i + 1 < len(matches):
                end_pos = matches[i + 1].start()
            else:
                end_pos = len(response)

            description = response[start_pos:end_pos].strip()

            # Extract tasks (bullet points)
            tasks = re.findall(r"[-*]\s*(.+?)(?=\n|$)", description)

            phases.append({
                "name": phase_name,
                "description": description[:500],  # Limit description length
                "tasks": tasks[:10],  # Limit number of tasks
            })

    return phases
