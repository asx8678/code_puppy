"""Adversarial Planning Agents.

This module provides all agents for the adversarial planning system:

- APResearcherAgent: Phase 0A - Evidence Discovery
- APPlannerAAgent: Phase 1 - Conservative Planner  
- APPlannerBAgent: Phase 1 - Contrarian Planner
- APReviewerAgent: Phase 2 - Adversarial Reviewer
- APArbiterAgent: Phase 4/6 - Synthesis & Decision
- APRedTeamAgent: Phase 5 - Stress Test (Deep mode)

All agents extend BaseAdversarialAgent which provides:
- Structured JSON output enforcement
- Shared rules from prompts/shared_rules.py
- Evidence-labeling requirements
- Role-based tool restrictions

Usage:
    from code_puppy.plugins.adversarial_planning.agents import (
        APResearcherAgent,
        APPlannerAAgent,
        get_adversarial_agents,
    )
    
    # Get agent definitions for registration
    agents = get_adversarial_agents()
"""

from .base_adversarial_agent import BaseAdversarialAgent
from .ap_researcher import APResearcherAgent
from .ap_planner_a import APPlannerAAgent
from .ap_planner_b import APPlannerBAgent
from .ap_reviewer import APReviewerAgent
from .ap_arbiter import APArbiterAgent
from .ap_red_team import APRedTeamAgent

__all__ = [
    # Base class
    "BaseAdversarialAgent",
    # Agent classes
    "APResearcherAgent",
    "APPlannerAAgent",
    "APPlannerBAgent",
    "APReviewerAgent",
    "APArbiterAgent",
    "APRedTeamAgent",
    # Registry functions
    "get_adversarial_agents",
    "get_role_prompt",
]


def get_adversarial_agents() -> list[dict]:
    """Return agent definitions for registration with the agent manager.
    
    Returns:
        List of agent definition dicts with 'name' and 'class' keys.
        These are used by the agent manager to register agents.
        
    Example:
        >>> agents = get_adversarial_agents()
        >>> len(agents)
        6
        >>> agents[0]['name']
        'ap-researcher'
    """
    return [
        {"name": "ap-researcher", "class": APResearcherAgent},
        {"name": "ap-planner-a", "class": APPlannerAAgent},
        {"name": "ap-planner-b", "class": APPlannerBAgent},
        {"name": "ap-reviewer", "class": APReviewerAgent},
        {"name": "ap-arbiter", "class": APArbiterAgent},
        {"name": "ap-red-team", "class": APRedTeamAgent},
    ]


def get_role_prompt(role_name: str) -> str:
    """Get the system prompt for a specific adversarial planning role.
    
    Args:
        role_name: One of: researcher, planner-a, planner-b, 
                          reviewer, arbiter, red-team
    
    Returns:
        Complete system prompt string for the role, or empty string
        if role not found.
        
    Example:
        >>> prompt = get_role_prompt("researcher")
        >>> "PHASE 0A" in prompt
        True
        >>> get_role_prompt("unknown")
        ''
    """
    # Import here to avoid circular imports at module load time
    from ..prompts import (
        researcher,
        planner_a,
        planner_b,
        reviewer,
        arbiter,
        red_team,
    )
    
    prompt_map = {
        "researcher": researcher.get_researcher_prompt,
        "planner-a": planner_a.get_planner_a_prompt,
        "planner-b": planner_b.get_planner_b_prompt,
        "reviewer": reviewer.get_reviewer_prompt,
        "arbiter": arbiter.get_arbiter_prompt,
        "red-team": red_team.get_red_team_prompt,
    }
    
    getter = prompt_map.get(role_name)
    if getter:
        return getter()
    return ""
