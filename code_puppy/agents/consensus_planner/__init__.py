"""Consensus Planner Agent - Multi-model ensemble planning with swarm consensus.

A meta-agent that uses ensemble programming and multi-model consensus for
critical planning decisions. Can invoke any available model and uses
swarm debate to select the best approach.

Example:
    from code_puppy.agents.consensus_planner import ConsensusPlannerAgent

    agent = ConsensusPlannerAgent()
    plan = await agent.plan_with_consensus("Design a caching system")
    print(plan.to_markdown())
"""

from .agent import ConsensusPlannerAgent
from .models import ModelComparisonResult, Plan

__all__ = ["ConsensusPlannerAgent", "ModelComparisonResult", "Plan"]
