"""Composite model routing — chain-of-responsibility for model selection.

Inspired by Gemini CLI's routing/strategies architecture.
"""

from code_puppy.routing.strategy import (
    RoutingContext,
    RoutingDecision,
    RoutingStrategy,
    TerminalStrategy,
)
from code_puppy.routing.composite import CompositeStrategy

__all__ = [
    "CompositeStrategy",
    "RoutingContext",
    "RoutingDecision",
    "RoutingStrategy",
    "TerminalStrategy",
]
