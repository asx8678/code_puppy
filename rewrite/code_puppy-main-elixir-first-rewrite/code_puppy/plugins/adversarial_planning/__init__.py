"""Adversarial Planning Plugin - Evidence-first, multi-agent planning system."""

__version__ = "0.1.0"
__plugin_name__ = "adversarial_planning"

from .renderers import AdversarialPlanningRenderer, render_session
from .commands import register_session, unregister_session, handle_command
from .orchestrator import AdversarialPlanningOrchestrator
from .models import PlanningSession, AdversarialPlanConfig

__all__ = [
    "AdversarialPlanningRenderer",
    "render_session",
    "register_session",
    "unregister_session",
    "handle_command",
    "AdversarialPlanningOrchestrator",
    "PlanningSession",
    "AdversarialPlanConfig",
]
