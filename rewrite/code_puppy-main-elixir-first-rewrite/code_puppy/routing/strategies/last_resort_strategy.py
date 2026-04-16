"""LastResortStrategy — guaranteed fallback when primary routing fails.

Ported from gemini-cli/packages/core/src/fallback/handler.ts:43-56
which implements the ``lastResortPolicy`` fallback mechanism:

    const lastResortPolicy = candidates.find((policy) => policy.isLastResort);
    const selectedFallbackModel =
      selection.selectedModel ?? lastResortPolicy?.model;

When all preferred strategies decline (availability check, plugin lookup,
etc.), this strategy picks the first available last-resort model.
If no models are marked as last-resort, it returns None and allows
the terminal default strategy to handle the request (backward compatible).
"""

import logging

from code_puppy.model_availability import (
    availability_service,
    get_last_resort_models,
)
from code_puppy.routing.strategy import RoutingContext, RoutingDecision

logger = logging.getLogger(__name__)


class LastResortStrategy:
    """Last-resort fallback when all preferred routing strategies fail.

    Inspired by gemini-cli/packages/core/src/fallback/handler.ts:43-56.

    This strategy acts as a safety net by trying models explicitly marked
    as last-resort (is_last_resort=True) when primary routing strategies
    (availability, plugin, etc.) all return None.

    Behavior:
    - If no models are marked last-resort: returns None (decline)
    - Otherwise: picks the first last-resort model that's available,
      or the first one if all are unavailable

    Backward compatibility: if no model is marked last-resort, this strategy
    effectively does nothing and the terminal default strategy fires as usual.
    """

    @property
    def name(self) -> str:
        return "last_resort"

    def route(self, context: RoutingContext) -> RoutingDecision | None:
        candidates = get_last_resort_models()
        if not candidates:
            # No last-resort models marked — decline and let default handle it
            return None

        # Find first available last-resort model
        result = availability_service.select_first_available(candidates)

        if result.selected_model:
            model_name = result.selected_model
            logger.info(
                "Last-resort strategy selecting available model '%s' "
                "(skipped %d unavailable)",
                model_name,
                len(result.skipped),
            )
        else:
            # All last-resort models unavailable — pick first anyway
            # This prevents "no model available" fatals per reference implementation
            model_name = candidates[0]
            logger.warning(
                "All last-resort models unavailable; forcing '%s' as fallback",
                model_name,
            )

        # Build the model via ModelFactory
        from code_puppy.model_factory import ModelFactory

        try:
            model = ModelFactory.get_model(model_name, context.config)
            return RoutingDecision(
                model=model,
                model_name=model_name,
                metadata={
                    "source": "last_resort",
                    "reason": "all primary strategies declined",
                    "skipped_last_resort": str(len(result.skipped)),
                },
            )
        except ValueError:
            # ModelFactory can't build this model — let default handle it
            return None
