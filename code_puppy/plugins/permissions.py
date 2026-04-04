"""Plugin permission enforcement and manifest validation.

This module handles loading manifest.json files from plugin directories
and validating that plugins only use the hooks and permissions they declare.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from code_puppy.callbacks import PhaseType, get_callbacks

if TYPE_CHECKING:
    from code_puppy.plugins.manifest import PluginManifest

logger = logging.getLogger(__name__)

# Track which hooks were registered by which plugins
# This is populated during plugin loading
_plugin_hook_registry: dict[str, list[str]] = {}

# Store loaded manifests by plugin name
_loaded_manifests: dict[str, "PluginManifest"] = {}


def _get_valid_hook_names() -> set[str]:
    """Get the set of all valid hook names from callbacks module.

    Returns:
        Set of valid PhaseType strings
    """
    from code_puppy.callbacks import PhaseType

    # Get the valid phases from the type
    # PhaseType is a Literal, so we get the args
    import typing

    phase_type = typing.get_args(PhaseType)
    if phase_type:
        return set(phase_type)
    # Fallback: extract from the module
    return {
        "startup",
        "shutdown",
        "invoke_agent",
        "agent_exception",
        "version_check",
        "edit_file",
        "create_file",
        "replace_in_file",
        "delete_snippet",
        "delete_file",
        "run_shell_command",
        "load_model_config",
        "load_models_config",
        "load_prompt",
        "agent_reload",
        "custom_command",
        "custom_command_help",
        "file_permission",
        "pre_tool_call",
        "post_tool_call",
        "stream_event",
        "register_tools",
        "register_agents",
        "register_model_type",
        "get_model_system_prompt",
        "agent_run_start",
        "agent_run_end",
        "register_mcp_catalog_servers",
        "register_browser_types",
        "get_motd",
        "register_model_providers",
        "message_history_processor_start",
        "message_history_processor_end",
    }


def load_manifest(
    plugin_dir: Path,
    plugin_name: str,
    is_builtin: bool = False,
) -> "PluginManifest | None":
    """Load manifest.json from a plugin directory if it exists.

    Args:
        plugin_dir: Path to the plugin directory
        plugin_name: Name of the plugin
        is_builtin: Whether this is a built-in plugin (affects default trust_level)

    Returns:
        PluginManifest if manifest.json exists and is valid, None otherwise
    """
    from code_puppy.plugins.manifest import PluginManifest

    manifest_path = plugin_dir / "manifest.json"

    if not manifest_path.exists():
        logger.debug(f"No manifest.json found for plugin '{plugin_name}' at {manifest_path}")
        return None

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Set default trust_level based on plugin type if not specified
        if "trust_level" not in data:
            data["trust_level"] = "builtin" if is_builtin else "user"

        manifest = PluginManifest.from_dict(data, plugin_name)
        _loaded_manifests[plugin_name] = manifest

        logger.debug(
            f"Loaded manifest for '{plugin_name}': "
            f"hooks={manifest.declared_hooks}, "
            f"trust={manifest.trust_level}"
        )
        return manifest

    except json.JSONDecodeError as e:
        logger.warning(
            f"Invalid JSON in manifest.json for plugin '{plugin_name}': {e}"
        )
        return None
    except Exception as e:
        logger.warning(
            f"Failed to load manifest.json for plugin '{plugin_name}': {e}"
        )
        return None


def get_manifest(plugin_name: str) -> "PluginManifest | None":
    """Get a loaded manifest by plugin name.

    Args:
        plugin_name: Name of the plugin

    Returns:
        The PluginManifest if loaded, None otherwise
    """
    return _loaded_manifests.get(plugin_name)


def get_all_manifests() -> dict[str, "PluginManifest"]:
    """Get all loaded manifests.

    Returns:
        Dictionary mapping plugin names to their manifests
    """
    return dict(_loaded_manifests)


def record_plugin_hooks(plugin_name: str, hooks: list[str]) -> None:
    """Record which hooks a plugin actually registered.

    This should be called after a plugin is loaded to track its actual
    callback registrations.

    Args:
        plugin_name: Name of the plugin
        hooks: List of hook names the plugin registered
    """
    if plugin_name not in _plugin_hook_registry:
        _plugin_hook_registry[plugin_name] = []
    _plugin_hook_registry[plugin_name].extend(hooks)


def get_plugin_recorded_hooks(plugin_name: str) -> list[str]:
    """Get the list of hooks a plugin actually registered.

    Args:
        plugin_name: Name of the plugin

    Returns:
        List of hook names (empty if plugin not tracked)
    """
    return list(_plugin_hook_registry.get(plugin_name, []))


def validate_plugin_hooks(
    plugin_name: str,
    manifest: "PluginManifest | None" = None,
) -> dict[str, list[str]]:
    """Validate that a plugin's actual hook registrations match its manifest.

    Compares the hooks the plugin actually registered (recorded via
    record_plugin_hooks) against the hooks declared in its manifest.

    Args:
        plugin_name: Name of the plugin to validate
        manifest: Optional manifest to use (if None, will look up loaded manifest)

    Returns:
        Dictionary with 'undeclared' and 'missing' keys:
        - 'undeclared': Hooks the plugin registered but didn't declare
        - 'missing': Hooks the plugin declared but didn't register
    """
    if manifest is None:
        manifest = get_manifest(plugin_name)

    actual_hooks = set(_plugin_hook_registry.get(plugin_name, []))

    if manifest is None:
        # No manifest - all hooks are technically "undeclared"
        return {
            "undeclared": list(actual_hooks),
            "missing": [],
        }

    declared_hooks = set(manifest.declared_hooks)

    undeclared = list(actual_hooks - declared_hooks)
    missing = list(declared_hooks - actual_hooks)

    return {
        "undeclared": undeclared,
        "missing": missing,
    }


def check_permission_violations(
    plugin_name: str,
    manifest: "PluginManifest | None" = None,
) -> list[str]:
    """Check for permission violations by a plugin.

    Analyzes the hooks a plugin registered to infer what permissions
    it might be using, and compares against its declared permissions.

    Args:
        plugin_name: Name of the plugin
        manifest: Optional manifest to use (if None, will look up loaded manifest)

    Returns:
        List of warning messages about potential violations
    """
    if manifest is None:
        manifest = get_manifest(plugin_name)

    actual_hooks = set(_plugin_hook_registry.get(plugin_name, []))
    violations = []

    if manifest is None:
        # No manifest - warn about any sensitive operations
        sensitive_hooks = {
            "run_shell_command",
            "file_permission",
            "create_file",
            "replace_in_file",
            "delete_file",
            "delete_snippet",
        }
        used_sensitive = actual_hooks & sensitive_hooks
        if used_sensitive:
            violations.append(
                f"Plugin '{plugin_name}' has no manifest.json but uses sensitive hooks: "
                f"{', '.join(sorted(used_sensitive))}. "
                f"Consider adding a manifest.json for transparency."
            )
        return violations

    # Check hook-based permission inferences
    # File operations
    file_hooks = {"create_file", "replace_in_file", "delete_file", "delete_snippet", "file_permission"}
    if (actual_hooks & file_hooks) and not manifest.file_access:
        violations.append(
            f"Plugin '{plugin_name}' registers file operation hooks but declares file_access=false"
        )

    # Shell operations
    if "run_shell_command" in actual_hooks and not manifest.shell_access:
        violations.append(
            f"Plugin '{plugin_name}' registers run_shell_command but declares shell_access=false"
        )

    # Network operations (inferred from hooks that typically involve network)
    # Note: This is heuristic-based and may need refinement
    network_hooks = {
        "invoke_agent",  # Often involves API calls
        "agent_run_start",
        "agent_run_end",
        "stream_event",
    }
    if (actual_hooks & network_hooks) and not manifest.network_access:
        # Only warn for plugins that seem to be doing agent/network stuff
        # but don't declare it. This is a soft warning.
        pass  # Network inference is tricky, skip for now

    return violations


def log_validation_results(
    plugin_name: str,
    validation: dict[str, list[str]],
    violations: list[str],
) -> None:
    """Log validation results for a plugin.

    Args:
        plugin_name: Name of the plugin
        validation: Result from validate_plugin_hooks()
        violations: List of permission violation warnings
    """
    undeclared = validation.get("undeclared", [])
    missing = validation.get("missing", [])

    if undeclared:
        logger.warning(
            f"Plugin '{plugin_name}' uses undeclared hooks: {', '.join(sorted(undeclared))}"
        )

    if missing:
        logger.debug(
            f"Plugin '{plugin_name}' declared but didn't register hooks: {', '.join(sorted(missing))}"
        )

    for violation in violations:
        logger.warning(violation)


def validate_all_plugins() -> dict[str, dict]:
    """Validate all plugins with loaded manifests.

    Returns:
        Dictionary mapping plugin names to their validation results:
        {
            "plugin_name": {
                "manifest": PluginManifest or None,
                "validation": {"undeclared": [...], "missing": [...]},
                "violations": [...],
            }
        }
    """
    results = {}

    for plugin_name in _plugin_hook_registry:
        manifest = get_manifest(plugin_name)
        validation = validate_plugin_hooks(plugin_name, manifest)
        violations = check_permission_violations(plugin_name, manifest)

        results[plugin_name] = {
            "manifest": manifest,
            "validation": validation,
            "violations": violations,
        }

        log_validation_results(plugin_name, validation, violations)

    return results


def clear_plugin_data(plugin_name: str | None = None) -> None:
    """Clear stored data for a plugin or all plugins.

    This is mainly useful for testing.

    Args:
        plugin_name: Specific plugin to clear, or None to clear all
    """
    global _plugin_hook_registry, _loaded_manifests

    if plugin_name is None:
        _plugin_hook_registry.clear()
        _loaded_manifests.clear()
    else:
        _plugin_hook_registry.pop(plugin_name, None)
        _loaded_manifests.pop(plugin_name, None)


def get_plugin_summary(plugin_name: str) -> dict | None:
    """Get a summary of a plugin's manifest and actual usage.

    Args:
        plugin_name: Name of the plugin

    Returns:
        Summary dict or None if plugin not tracked
    """
    manifest = get_manifest(plugin_name)
    actual_hooks = _plugin_hook_registry.get(plugin_name)

    if actual_hooks is None and manifest is None:
        return None

    validation = validate_plugin_hooks(plugin_name, manifest)
    violations = check_permission_violations(plugin_name, manifest)

    return {
        "name": plugin_name,
        "has_manifest": manifest is not None,
        "manifest": manifest.to_dict() if manifest else None,
        "actual_hooks": actual_hooks or [],
        "undeclared_hooks": validation["undeclared"],
        "missing_hooks": validation["missing"],
        "permission_violations": violations,
    }
