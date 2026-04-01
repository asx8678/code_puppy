"""AvailabilityStrategy — skip models marked as unavailable by the circuit breaker."""

import logging
from code_puppy.model_availability import availability_service
from code_puppy.routing.strategy import RoutingContext, RoutingDecision

logger = logging.getLogger(__name__)


class AvailabilityStrategy:
    """Checks if the requested model is available; declines if it is, skips if not.

    When the requested model is unavailable, selects the first available
    alternative from the config. Returns None if the requested model is healthy
    (letting downstream strategies handle it).
    """

    @property
    def name(self) -> str:
        return "availability"

    def route(self, context: RoutingContext) -> RoutingDecision | None:
        snap = availability_service.snapshot(context.model_name)
        if snap.available:
            return None  # Model is fine, let other strategies handle

        # Model is down — find first available alternative
        alternatives = [name for name in context.config if name != context.model_name]
        result = availability_service.select_first_available(alternatives)

        if result.selected_model is None:
            logger.warning("All models unavailable — falling through to default")
            return None

        # Build the model via ModelFactory
        from code_puppy.model_factory import ModelFactory

        try:
            model = ModelFactory.get_model(result.selected_model, context.config)
            logger.info(
                "Model '%s' unavailable (%s), routing to '%s'",
                context.model_name,
                snap.reason,
                result.selected_model,
            )
            return RoutingDecision(
                model=model,
                model_name=result.selected_model,
                metadata={
                    "reasoning": f"fallback from {context.model_name} ({snap.reason})"
                },
            )
        except ValueError:
            return None
