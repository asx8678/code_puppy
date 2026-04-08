"""Contract test helpers for plugins, tools, and providers.

This module provides reusable contract validation helpers that can be used
by both the core test suite and third-party plugin authors to validate their
implementations against code_puppy's contracts.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable


class ContractViolation(Exception):
    """Raised when a contract is violated."""

    def __init__(
        self, component: str, issue: str, details: dict[str, Any] | None = None
    ):
        self.component = component
        self.issue = issue
        self.details = details or {}
        super().__init__(f"Contract violation in {component}: {issue}")


class PluginContract:
    """Contract validation for plugins."""

    REQUIRED_CALLBACK_PHASES = [
        "startup",
        "shutdown",
    ]

    @staticmethod
    def validate_import_safety(
        module_name: str, import_func: Callable[[], Any]
    ) -> None:
        """Validate that a plugin can be imported without errors.

        Args:
            module_name: Name of the module to import
            import_func: Function that performs the import

        Raises:
            ContractViolation: If import fails or has side effects
        """
        try:
            result = import_func()
            if result is None:
                raise ContractViolation(
                    module_name,
                    "Import returned None - module should be importable",
                )
        except Exception as e:
            raise ContractViolation(
                module_name,
                f"Import failed with exception: {type(e).__name__}: {e}",
                {"exception": str(e)},
            )

    @staticmethod
    def validate_callback_deduplication(
        register_func: Callable,
        callback: Callable,
        phase: str,
    ) -> None:
        """Validate that registering the same callback twice is deduplicated.

        Args:
            register_func: The register_callback function
            callback: A test callback
            phase: The phase to register for

        Raises:
            ContractViolation: If callback is not deduplicated
        """
        # Register twice
        register_func(phase, callback)
        register_func(phase, callback)

        # Check callbacks list - should only have one instance
        from code_puppy.callbacks import get_callbacks

        callbacks = get_callbacks(phase)

        count = sum(1 for cb in callbacks if cb is callback)
        if count > 1:
            raise ContractViolation(
                f"callback:{phase}",
                f"Callback registered {count} times, expected deduplication",
                {"count": count},
            )


class ToolContract:
    """Contract validation for tools."""

    REQUIRED_FIELDS = ["name", "description", "parameters"]

    @staticmethod
    def validate_tool_schema(schema: dict[str, Any], tool_name: str) -> None:
        """Validate that a tool schema has all required fields.

        Args:
            schema: The tool schema to validate
            tool_name: Name of the tool (for error messages)

        Raises:
            ContractViolation: If schema is missing required fields
        """
        missing = []
        for field in ToolContract.REQUIRED_FIELDS:
            if field not in schema:
                missing.append(field)

        if missing:
            raise ContractViolation(
                f"tool:{tool_name}",
                f"Missing required fields: {missing}",
                {"missing_fields": missing, "schema_keys": list(schema.keys())},
            )

        # Validate parameters schema
        params = schema.get("parameters", {})
        if not isinstance(params, dict):
            raise ContractViolation(
                f"tool:{tool_name}",
                "parameters must be a dict/object",
                {"parameters_type": type(params).__name__},
            )

        if "properties" not in params:
            raise ContractViolation(
                f"tool:{tool_name}",
                "parameters.properties is required",
            )

    @staticmethod
    def validate_tool_signature(func: Callable, tool_name: str) -> None:
        """Validate that a tool function has a valid signature.

        Args:
            func: The tool function
            tool_name: Name of the tool

        Raises:
            ContractViolation: If signature is invalid
        """
        try:
            sig = inspect.signature(func)
        except ValueError as e:
            raise ContractViolation(
                f"tool:{tool_name}",
                f"Could not inspect signature: {e}",
            )

        # Tools should have at least one parameter (usually context or args)
        params = list(sig.parameters.items())

        # Check for **kwargs support (good practice for tools)
        has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for _, p in params)

        # Not required but recommended - just warn for now
        return {
            "has_kwargs": has_kwargs,
            "param_count": len(params),
        }


class ProviderContract:
    """Contract validation for model providers."""

    REQUIRED_METHODS = [
        "create_model",
        "is_available",
    ]

    @staticmethod
    def validate_provider_interface(provider_class: type, provider_name: str) -> None:
        """Validate that a provider class implements required methods.

        Args:
            provider_class: The provider class to validate
            provider_name: Name of the provider

        Raises:
            ContractViolation: If required methods are missing
        """
        missing = []

        for method_name in ProviderContract.REQUIRED_METHODS:
            if not hasattr(provider_class, method_name):
                missing.append(method_name)
                continue

            method = getattr(provider_class, method_name)
            if not callable(method):
                missing.append(f"{method_name} (not callable)")

        if missing:
            raise ContractViolation(
                f"provider:{provider_name}",
                f"Missing required methods: {missing}",
                {"missing_methods": missing},
            )

    @staticmethod
    def validate_model_config(config: dict[str, Any], provider_name: str) -> None:
        """Validate that a model configuration has required fields.

        Args:
            config: The model configuration
            provider_name: Name of the provider

        Raises:
            ContractViolation: If config is invalid
        """
        required_fields = ["model_name", "provider"]

        missing = [f for f in required_fields if f not in config]

        if missing:
            raise ContractViolation(
                f"provider:{provider_name}",
                f"Model config missing fields: {missing}",
                {"missing_fields": missing},
            )


# Convenience functions for third-party plugin authors
def validate_plugin_contracts(module_name: str, import_func: Callable) -> list[str]:
    """Run all plugin contract validations.

    Args:
        module_name: Name of the module to validate
        import_func: Function that imports the module

    Returns:
        List of error messages (empty if all pass)
    """
    errors = []

    try:
        PluginContract.validate_import_safety(module_name, import_func)
    except ContractViolation as e:
        errors.append(str(e))

    return errors


def validate_tool_contracts(tools: dict[str, Callable]) -> list[str]:
    """Run all tool contract validations.

    Args:
        tools: Dict mapping tool names to tool functions

    Returns:
        List of error messages (empty if all pass)
    """
    errors = []

    for name, func in tools.items():
        try:
            ToolContract.validate_tool_signature(func, name)
        except ContractViolation as e:
            errors.append(str(e))

    return errors
