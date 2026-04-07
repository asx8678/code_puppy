"""Lazy plugin loading system for code_puppy.

Plugins are discovered at startup but only imported when their callbacks are first triggered.
This reduces cold-start time by deferring heavy imports until they're actually needed.
"""

import importlib
import importlib.util
import logging
import sys
import threading
from pathlib import Path
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from code_puppy.callbacks import PhaseType

logger = logging.getLogger(__name__)

# User plugins directory
USER_PLUGINS_DIR = Path.home() / ".code_puppy" / "plugins"

# Track if plugins have already been discovered to prevent duplicate work
_PLUGINS_DISCOVERED = False

# Registry of lazy-loadable plugins: {phase: [(plugin_type, plugin_name, load_func), ...]}
# plugin_type is 'builtin' or 'user'
# load_func is a callable that performs the actual import and returns the module
_LAZY_PLUGIN_REGISTRY: dict[str, list[tuple[str, str, Callable]]] = {}

# Track which plugins have been fully loaded to prevent duplicate imports
_LOADED_PLUGINS: set[str] = set()

# Lock for thread-safe access to _LOADED_PLUGINS
_plugin_load_lock = threading.Lock()


def _create_loader_builtin(plugin_name: str, module_name: str) -> Callable:
    """Create a lazy loader function for a built-in plugin."""
    def _load():
        try:
            return importlib.import_module(module_name)
        except ImportError as e:
            logger.warning(f"Failed to lazy-load built-in plugin {plugin_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error lazy-loading built-in plugin {plugin_name}: {e}")
            return None
    return _load


def _create_loader_user(plugin_name: str, callbacks_file: Path) -> Callable:
    """Create a lazy loader function for a user plugin.
    
    SECURITY FIX c9z0: User plugins execute with full privileges via exec_module().
    Added warnings and allowlist requirement for user plugin security.
    """
    def _load():
        try:
            # SECURITY FIX c9z0: Check if user plugins are enabled
            from code_puppy.config import get_value
            user_plugins_enabled = get_value("enable_user_plugins")
            if user_plugins_enabled is None:
                # Default to disabled - require explicit opt-in
                logger.warning(
                    f"SECURITY: User plugin '{plugin_name}' not loaded. "
                    f"User plugins are disabled by default. Set enable_user_plugins=true "
                    f"in config to enable (executes untrusted code with full privileges)."
                )
                return None
            
            # Check allowlist if configured
            allowed_plugins = get_value("allowed_user_plugins")
            if allowed_plugins:
                allowed = [p.strip() for p in allowed_plugins.split(",")]
                if plugin_name not in allowed:
                    logger.warning(
                        f"SECURITY: User plugin '{plugin_name}' not in allowlist. "
                        f"Add to allowed_user_plugins config to enable."
                    )
                    return None
            
            # Log security warning when loading
            logger.warning(
                f"SECURITY: Loading user plugin '{plugin_name}' from {callbacks_file}. "
                f"This plugin will execute with full system privileges!"
            )
            
            module_name = f"{plugin_name}.register_callbacks"
            spec = importlib.util.spec_from_file_location(module_name, callbacks_file)
            if spec is None or spec.loader is None:
                logger.warning(f"Could not create module spec for user plugin: {plugin_name}")
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            # SECURITY: exec_module() executes arbitrary Python code
            # This is the attack surface for RCE via malicious plugins
            spec.loader.exec_module(module)
            return module
        except ImportError as e:
            logger.warning(f"Failed to lazy-load user plugin {plugin_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error lazy-loading user plugin {plugin_name}: {e}", exc_info=True)
            return None
    return _load


def _register_lazy_plugin(phase: str, plugin_type: str, plugin_name: str, load_func: Callable) -> None:
    """Register a plugin for lazy loading when a specific phase is triggered."""
    if phase not in _LAZY_PLUGIN_REGISTRY:
        _LAZY_PLUGIN_REGISTRY[phase] = []
    _LAZY_PLUGIN_REGISTRY[phase].append((plugin_type, plugin_name, load_func))
    logger.debug(f"Registered {plugin_type} plugin '{plugin_name}' for lazy loading on phase '{phase}'")


def _discover_builtin_plugins(plugins_dir: Path) -> list[tuple[str, list[str]]]:
    """Discover built-in plugins and their target phases without importing them.

    Returns list of (plugin_name, phases) tuples where phases are the callback phases
    the plugin wants to register for.
    """
    discovered = []

    for item in plugins_dir.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            plugin_name = item.name
            callbacks_file = item / "register_callbacks.py"

            if callbacks_file.exists():
                # Check for shell_safety plugin - may need to skip based on config
                if plugin_name == "shell_safety":
                    from code_puppy.config import get_safety_permission_level
                    safety_level = get_safety_permission_level()
                    if safety_level not in ("none", "low"):
                        logger.debug(
                            f"Skipping shell_safety plugin - safety_permission_level is '{safety_level}'"
                        )
                        continue

                # Parse the register_callbacks.py to find which phases it uses
                phases = _extract_phases_from_callbacks_file(callbacks_file, plugin_name)
                if phases:
                    discovered.append((plugin_name, phases))

    return discovered


def _extract_phases_from_callbacks_file(callbacks_file: Path, plugin_name: str) -> list[str]:
    """Extract callback phases from a register_callbacks.py file without executing it.

    This is a lightweight static analysis to determine which phases a plugin
    will register for, so we can lazy-load it only when those phases trigger.
    """
    phases = []
    supported_phases = {
        "startup", "shutdown", "invoke_agent", "agent_exception", "version_check",
        "edit_file", "create_file", "replace_in_file", "delete_snippet", "delete_file",
        "run_shell_command", "load_model_config", "load_models_config", "load_prompt",
        "agent_reload", "custom_command", "custom_command_help", "file_permission",
        "pre_tool_call", "post_tool_call", "stream_event", "register_tools",
        "register_agents", "register_model_type", "get_model_system_prompt",
        "agent_run_start", "agent_run_end", "register_mcp_catalog_servers",
        "register_browser_types", "get_motd", "register_model_providers",
        "message_history_processor_start", "message_history_processor_end",
    }

    try:
        content = callbacks_file.read_text()

        # Look for register_callback("phase", ...) patterns
        import re
        pattern = r'register_callback\s*\(\s*["\']([^"\']+)["\']'
        matches = re.findall(pattern, content)

        for phase in matches:
            if phase in supported_phases:
                phases.append(phase)  # type: ignore

        # If no explicit register_callback calls found but file exists,
        # the plugin might register callbacks at import time via side effects
        # In that case, default to startup phase
        if not phases:
            phases = ["startup"]  # type: ignore

    except Exception as e:
        logger.warning(f"Could not parse callbacks file for {plugin_name}: {e}")
        phases = ["startup"]  # type: ignore

    return phases


def _discover_user_plugins(user_plugins_dir: Path) -> list[tuple[str, list[str]]]:
    """Discover user plugins and their target phases without importing them.

    Returns list of (plugin_name, phases) tuples.
    """
    discovered = []

    if not user_plugins_dir.exists():
        return discovered

    if not user_plugins_dir.is_dir():
        logger.warning(f"User plugins path is not a directory: {user_plugins_dir}")
        return discovered

    # Add user plugins directory to sys.path if not already there
    user_plugins_str = str(user_plugins_dir)
    if user_plugins_str not in sys.path:
        sys.path.insert(0, user_plugins_str)

    for item in user_plugins_dir.iterdir():
        if (
            item.is_dir()
            and not item.name.startswith("_")
            and not item.name.startswith(".")
        ):
            plugin_name = item.name
            callbacks_file = item / "register_callbacks.py"

            if callbacks_file.exists():
                phases = _extract_phases_from_callbacks_file(callbacks_file, plugin_name)
                if phases:
                    discovered.append((plugin_name, phases))
            else:
                # Check if there's an __init__.py - might be a simple plugin
                init_file = item / "__init__.py"
                if init_file.exists():
                    # Simple plugins typically run at startup
                    discovered.append((plugin_name, ["startup"]))  # type: ignore

    return discovered


def load_plugin_callbacks() -> dict[str, list[str]]:
    """Discover plugins for lazy loading.

    This function discovers all plugins and registers them for lazy loading
    based on which callback phases they use. Plugins are NOT imported during
    discovery - they're only imported when their registered phases trigger.

    Returns dict with 'builtin' and 'user' keys containing lists of discovered plugin names.

    NOTE: This function is idempotent - calling it multiple times will only
    discover plugins once. Subsequent calls return empty lists.
    """
    global _PLUGINS_DISCOVERED

    if _PLUGINS_DISCOVERED:
        logger.debug("Plugins already discovered, skipping")
        return {"builtin": [], "user": []}

    plugins_dir = Path(__file__).parent

    # Discover built-in plugins
    builtin_discovered = _discover_builtin_plugins(plugins_dir)
    builtin_loaded = []
    for plugin_name, phases in builtin_discovered:
        module_name = f"code_puppy.plugins.{plugin_name}.register_callbacks"
        load_func = _create_loader_builtin(plugin_name, module_name)

        # Register this plugin for lazy loading on each of its phases
        for phase in phases:
            _register_lazy_plugin(phase, "builtin", plugin_name, load_func)

        builtin_loaded.append(plugin_name)

    # Discover user plugins
    user_discovered = _discover_user_plugins(USER_PLUGINS_DIR)
    user_loaded = []
    for plugin_name, phases in user_discovered:
        callbacks_file = USER_PLUGINS_DIR / plugin_name / "register_callbacks.py"
        load_func = _create_loader_user(plugin_name, callbacks_file)

        # Register this plugin for lazy loading on each of its phases
        for phase in phases:
            _register_lazy_plugin(phase, "user", plugin_name, load_func)

        user_loaded.append(plugin_name)

    _PLUGINS_DISCOVERED = True
    logger.debug(f"Discovered plugins for lazy loading: builtin={builtin_loaded}, user={user_loaded}")

    return {"builtin": builtin_loaded, "user": user_loaded}


def _load_plugins_for_phase(phase: str) -> list[str]:
    """Load all plugins registered for a specific phase.

    This is called internally when a phase is triggered to ensure
    all lazy-loaded plugins for that phase are imported before callbacks run.
    """
    if phase not in _LAZY_PLUGIN_REGISTRY:
        return []

    loaded = []
    plugins_to_load = _LAZY_PLUGIN_REGISTRY.get(phase, [])

    for plugin_type, plugin_name, load_func in plugins_to_load:
        # Skip if already loaded (with lock for thread safety)
        plugin_key = f"{plugin_type}:{plugin_name}"
        with _plugin_load_lock:
            if plugin_key in _LOADED_PLUGINS:
                continue

        # Load the plugin
        result = load_func()
        if result is not None:
            with _plugin_load_lock:
                _LOADED_PLUGINS.add(plugin_key)
            loaded.append(plugin_name)
            logger.debug(f"Lazy-loaded {plugin_type} plugin '{plugin_name}' for phase '{phase}'")

    return loaded


def ensure_plugins_loaded_for_phase(phase: str) -> list[str]:
    """Public API to ensure all plugins for a phase are loaded.

    This should be called by the callbacks system before triggering callbacks
    for a phase that might have lazy-loaded plugins.

    Returns list of plugin names that were loaded.
    """
    return _load_plugins_for_phase(phase)


def get_user_plugins_dir() -> Path:
    """Return the path to the user plugins directory."""
    return USER_PLUGINS_DIR


def ensure_user_plugins_dir() -> Path:
    """Create the user plugins directory if it doesn't exist.

    Returns the path to the directory.
    """
    USER_PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    return USER_PLUGINS_DIR
