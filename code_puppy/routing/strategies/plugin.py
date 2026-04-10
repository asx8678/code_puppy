"""PluginStrategy — delegate to plugin-registered model providers."""

import logging
from code_puppy.routing.strategy import RoutingContext, RoutingDecision

logger = logging.getLogger(__name__)


class PluginStrategy:
    """Checks plugin-registered model providers and type handlers."""

    @property
    def name(self) -> str:
        return "plugin"

    def route(self, context: RoutingContext) -> RoutingDecision | None:
        from code_puppy.model_config import (
            get_custom_provider,
            load_plugin_providers,
            resolve_model_type,
        )
        from code_puppy import callbacks

        model_config = context.config.get(context.model_name)
        if not model_config:
            return None

        model_type = resolve_model_type(model_config)
        if not model_type:
            return None

        load_plugin_providers()

        # Check custom provider classes first
        provider_class = get_custom_provider(model_type)
        if provider_class is not None:
            try:
                result = provider_class(
                    model_name=context.model_name,
                    model_config=model_config,
                    config=context.config,
                )
                if result is not None:
                    return RoutingDecision(
                        model=result,
                        model_name=context.model_name,
                        metadata={"reasoning": f"custom provider '{model_type}'"},
                    )
            except Exception as e:
                logger.debug("Custom provider '%s' failed: %s", model_type, e)

        # Check plugin callback handlers
        registered = callbacks.on_register_model_types()
        for handler_info in registered:
            handlers = (
                handler_info
                if isinstance(handler_info, list)
                else [handler_info]
                if handler_info
                else []
            )
            for entry in handlers:
                if not isinstance(entry, dict) or entry.get("type") != model_type:
                    continue
                handler = entry.get("handler")
                if callable(handler):
                    try:
                        result = handler(
                            context.model_name, model_config, context.config
                        )
                        if result is not None:
                            return RoutingDecision(
                                model=result,
                                model_name=context.model_name,
                                metadata={
                                    "reasoning": f"plugin handler '{model_type}'"
                                },
                            )
                    except Exception as e:
                        logger.debug("Plugin handler '%s' failed: %s", model_type, e)

        return None
