"""Built-in capability definitions and providers.

These define the standard capabilities that Code Puppy supports out of
the box.  Plugins can register additional :class:`~types.Provider`
instances for any of these capabilities by calling
:func:`~registry.register_provider`.

Standard capabilities defined here
------------------------------------
* ``"models"``   – AI model configurations
* ``"rules"``    – Agent behaviour rules
* ``"mcps"``     – Model Context Protocol server configurations

Example – adding a custom models provider from a plugin::

    from code_puppy.capability import register_provider
    from code_puppy.capability.types import LoadContext, LoadResult

    class MyModelsProvider:
        id = "my_plugin_models"
        display_name = "My Plugin Models"
        description = "Models supplied by my plugin"
        priority = 50

        def load(self, ctx: LoadContext) -> LoadResult:
            return LoadResult(items=[{"name": "my-custom-gpt", "type": "openai"}])

    register_provider("models", MyModelsProvider())
"""

from .registry import define_capability

# ---------------------------------------------------------------------------
# Standard capabilities
# ---------------------------------------------------------------------------

models_capability = define_capability(
    id="models",
    display_name="Models",
    description="AI model configurations",
    key_fn=lambda m: m.get("name") if isinstance(m, dict) else None,
)

rules_capability = define_capability(
    id="rules",
    display_name="Rules",
    description="Agent behaviour rules",
    key_fn=lambda r: r.get("name") if isinstance(r, dict) else None,
)

mcps_capability = define_capability(
    id="mcps",
    display_name="MCP Servers",
    description="Model Context Protocol server configurations",
    key_fn=lambda m: m.get("name") if isinstance(m, dict) else None,
)

__all__ = [
    "models_capability",
    "rules_capability",
    "mcps_capability",
]
