"""Tool registration for adversarial planning.

Registers tools specific to the adversarial planning plugin.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_adversarial_tools() -> list[dict[str, Any]]:
    """Get adversarial planning specific tools.
    
    Returns:
        List of tool registration dictionaries.
        Each dict has:
            - name: str
            - register_func: callable that registers the tool
    """
    return [
        {"name": "adversarial_plan", "register_func": register_adversarial_plan_tool},
    ]


def register_adversarial_plan_tool(agent: Any) -> None:
    """Register the adversarial_plan tool with an agent."""
    @agent.tool
    async def adversarial_plan(
        context: Any,
        task: str,
        mode: str = "auto",
        success_criteria: list[str] | None = None,
        hard_constraints: list[str] | None = None,
    ) -> dict:
        """Run adversarial planning for a complex task.
        
        Creates competing plans from independent planners,
        subjects them to adversarial review, synthesizes
        the best elements, and produces an executable plan.
        
        Args:
            task: The task/problem to plan
            mode: auto | standard | deep
            success_criteria: List of success criteria
            hard_constraints: List of hard constraints
            
        Returns:
            Full planning session with verdict and execution plan
        """
        from .orchestrator import AdversarialPlanningOrchestrator
        from .models import AdversarialPlanConfig, WorkspaceContext
        from .commands import register_session, unregister_session
        import os

        config = AdversarialPlanConfig(
            mode=mode,
            context=WorkspaceContext(
                workspace=os.getcwd(),
            ),
            task=task,
            success_criteria=success_criteria or [],
            hard_constraints=hard_constraints or [],
        )

        orchestrator = AdversarialPlanningOrchestrator(config)

        register_session(orchestrator)
        try:
            session = await orchestrator.run()
            return session.model_dump()
        finally:
            unregister_session(orchestrator.session_id)


# Additional tools for future implementation

def tool_evidence_add(
    session_id: str,
    evidence_class: str,
    claim: str,
    source_kind: str,
    source_locator: str,
    confidence: int = 50
) -> dict[str, Any]:
    """Add evidence to a planning session.
    
    TODO(code_puppy-792): Implement evidence tool
    """
    raise NotImplementedError("Evidence tool not yet implemented")


def tool_session_export(session_id: str, format: str = "json") -> str:
    """Export a planning session to file.
    
    TODO(code_puppy-792): Implement export tool
    """
    raise NotImplementedError("Export tool not yet implemented")


def tool_plan_diff(session_a: str, session_b: str) -> dict[str, Any]:
    """Compare two planning sessions/plans.
    
    TODO(code_puppy-792): Implement diff tool
    """
    raise NotImplementedError("Diff tool not yet implemented")
