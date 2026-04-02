"""
Agent Swarm Consensus - Ensemble Programming for Code Puppy.

This plugin extends Pack Leader to enable ensemble programming with multiple AI agents
deploying different reasoning approaches to reach consensus on complex tasks.

Usage:
    from code_puppy.plugins.swarm_consensus import SwarmConfig, SwarmOrchestrator

    config = SwarmConfig(swarm_size=3, consensus_threshold=0.7)
    orchestrator = SwarmOrchestrator(config)
    result = await orchestrator.execute_swarm(task_prompt="Refactor this function...")
"""

from .models import (
    AgentResult,
    ApproachConfig,
    SwarmConfig,
    SwarmResult,
)
from .approaches import (
    APPROACHES,
    apply_approach,
    get_approaches_for_task,
)
from .config import (
    get_consensus_threshold,
    get_default_swarm_size,
    get_swarm_enabled,
    get_swarm_timeout_seconds,
    set_swarm_enabled,
)
from .scoring import (
    aggregate_confidences,
    calculate_confidence,
    score_by_certainty_markers,
    score_by_consistency,
)
from .consensus import (
    detect_consensus,
    generate_debate_transcript,
    identify_points_of_agreement,
    identify_points_of_disagreement,
    synthesize_results,
)
from .orchestrator import SwarmOrchestrator

__all__ = [
    # Models
    "AgentResult",
    "ApproachConfig",
    "SwarmConfig",
    "SwarmResult",
    # Approaches
    "APPROACHES",
    "apply_approach",
    "get_approaches_for_task",
    # Config
    "get_consensus_threshold",
    "get_default_swarm_size",
    "get_swarm_enabled",
    "get_swarm_timeout_seconds",
    "set_swarm_enabled",
    # Scoring
    "aggregate_confidences",
    "calculate_confidence",
    "score_by_certainty_markers",
    "score_by_consistency",
    # Consensus
    "detect_consensus",
    "generate_debate_transcript",
    "identify_points_of_agreement",
    "identify_points_of_disagreement",
    "synthesize_results",
    # Orchestrator
    "SwarmOrchestrator",
]

__version__ = "0.1.0"
