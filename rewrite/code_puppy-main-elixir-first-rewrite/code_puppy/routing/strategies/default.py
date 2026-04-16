"""DefaultStrategy (terminal) — uses the ModelFactory builder registry."""

import logging
from code_puppy.routing.strategy import RoutingContext, RoutingDecision

logger = logging.getLogger(__name__)


class DefaultStrategy:
    """Terminal strategy using the core ModelFactory builder registry.

    This wraps the existing _MODEL_BUILDERS lookup that handles
    openai, anthropic, gemini, etc. It must always return a decision.
    """

    @property
    def name(self) -> str:
        return "default"

    def route(self, context: RoutingContext) -> RoutingDecision:
        from code_puppy.model_config import get_model_builder, resolve_model_type

        model_config = context.config.get(context.model_name)
        if not model_config:
            raise ValueError(
                f"Model '{context.model_name}' not found in configuration."
            )

        model_type = resolve_model_type(model_config)
        if not model_type:
            raise ValueError(
                f"Model '{context.model_name}' has no 'type' in configuration."
            )

        builder = get_model_builder(model_type)
        if builder is None:
            raise ValueError(f"Unsupported model type: {model_type}")

        result = builder(context.model_name, model_config, context.config)
        if result is None:
            raise ValueError(
                f"Model '{context.model_name}' (type='{model_type}') "
                f"could not be initialized by builder."
            )

        return RoutingDecision(
            model=result,
            model_name=context.model_name,
            metadata={"reasoning": f"builder '{model_type}'"},
        )
