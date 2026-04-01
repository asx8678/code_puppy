"""Factory for creating the default model router."""

from code_puppy.routing.composite import CompositeStrategy
from code_puppy.routing.strategies.availability import AvailabilityStrategy
from code_puppy.routing.strategies.plugin import PluginStrategy
from code_puppy.routing.strategies.default import DefaultStrategy


def create_default_router() -> CompositeStrategy:
    """Create the default model routing chain.

    Order (first match wins):
    1. AvailabilityStrategy — skip quota-exhausted models
    2. PluginStrategy — check custom model providers
    3. DefaultStrategy (terminal) — use core builder registry
    """
    return CompositeStrategy(
        strategies=[
            AvailabilityStrategy(),
            PluginStrategy(),
            DefaultStrategy(),  # terminal — always returns a decision
        ],
        name="model-router",
    )
