"""
Consensus Planner Plugin for Code Puppy.

A sophisticated meta-agent that uses multi-model ensemble programming
and swarm consensus for critical planning decisions.

This plugin provides:
- ConsensusPlannerAgent: Multi-model planning agent
- Auto-spawn integration: Automatic detection and consensus triggering
- Manual invocation tools: For agents to request consensus when needed
"""

from code_puppy.agents.consensus_planner import (
    ConsensusPlannerAgent,
    ModelComparisonResult,
    Plan,
)

# Auto-spawn functionality
from .auto_spawn import (
    AutoSpawnConfig,
    IssueDetectionResult,
    auto_spawn_consensus_planner,
    detect_issue_need_consensus,
    get_consensus_auto_spawn_enabled,
    get_consensus_auto_spawn_triggers,
    get_consensus_uncertainty_threshold,
    monitor_agent_execution,
    should_auto_spawn_consensus,
)

__all__ = [
    # Core classes
    "ConsensusPlannerAgent",
    "ModelComparisonResult",
    "Plan",
    # Auto-spawn
    "AutoSpawnConfig",
    "IssueDetectionResult",
    "auto_spawn_consensus_planner",
    "detect_issue_need_consensus",
    "get_consensus_auto_spawn_enabled",
    "get_consensus_auto_spawn_triggers",
    "get_consensus_uncertainty_threshold",
    "monitor_agent_execution",
    "should_auto_spawn_consensus",
]
