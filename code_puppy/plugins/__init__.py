import importlib
import importlib.util
import logging
import sys
from pathlib import Path

from code_puppy import callbacks as _callbacks_module

logger = logging.getLogger(__name__)

# User plugins directory
USER_PLUGINS_DIR = Path.home() / ".code_puppy" / "plugins"

# Track if plugins have already been loaded to prevent duplicate registration
_PLUGINS_LOADED = False

# Track which plugin is currently being loaded (for hook attribution)
_CURRENT_PLUGIN: str | None = None


def _set_current_plugin(name: str | None) -> None:
    """Set the plugin name context for hook attribution.
    
    This allows us to track which hooks are registered by which plugin.
    """
    global _CURRENT_PLUGIN
    _CURRENT_PLUGIN = name


def _get_current_plugin() -> str | None:
    """Get the name of the plugin currently being loaded."""
    return _CURRENT_PLUGIN


def _wrap_register_callback_for_tracking():
    """Wrap the register_callback function to track plugin hook registrations."""
    original_register = _callbacks_module.register_callback
    
    def tracked_register(phase, func):
        # Call the original registration
        result = original_register(phase, func)
        
        # Track which plugin registered this hook
        plugin_name = _get_current_plugin()
        if plugin_name:
            from code_puppy.plugins.permissions import record_plugin_hooks
            record_plugin_hooks(plugin_name, [phase])
            logger.debug(f"Plugin '{plugin_name}' registered hook '{phase}'")
        
        return result
    
    # Replace the function in the module
    _callbacks_module.register_callback = tracked_register


def _load_builtin_plugins(plugins_dir: Path) -> list[dict]:
    """Load built-in plugins from the package plugins directory.

    Returns list of dicts with plugin info:
        {"name": str, "manifest": PluginManifest or None}
    """
    from code_puppy.config import get_safety_permission_level
    from code_puppy.plugins.manifest import PluginManifest
    from code_puppy.plugins.permissions import (
        load_manifest,
        validate_plugin_hooks,
        check_permission_violations,
        log_validation_results,
    )

    loaded = []

    for item in plugins_dir.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            plugin_name = item.name
            callbacks_file = item / "register_callbacks.py"

            if callbacks_file.exists():
                # Skip shell_safety plugin unless safety_permission_level is "low" or "none"
                if plugin_name == "shell_safety":
                    safety_level = get_safety_permission_level()
                    if safety_level not in ("none", "low"):
                        logger.debug(
                            f"Skipping shell_safety plugin - safety_permission_level is '{safety_level}' (needs 'low' or 'none')"
                        )
                        continue

                # Load manifest if it exists
                manifest = load_manifest(item, plugin_name, is_builtin=True)
                if manifest is None:
                    logger.debug(f"No manifest.json for built-in plugin '{plugin_name}'")

                try:
                    # Set current plugin for hook tracking
                    _set_current_plugin(plugin_name)
                    
                    module_name = f"code_puppy.plugins.{plugin_name}.register_callbacks"
                    importlib.import_module(module_name)
                    
                    loaded.append({"name": plugin_name, "manifest": manifest})
                    
                    # Validate hooks if we have a manifest
                    if manifest:
                        validation = validate_plugin_hooks(plugin_name, manifest)
                        violations = check_permission_violations(plugin_name, manifest)
                        log_validation_results(plugin_name, validation, violations)
                    else:
                        # Check for permission violations even without manifest
                        violations = check_permission_violations(plugin_name, None)
                        for v in violations:
                            logger.warning(v)
                            
                except ImportError as e:
                    logger.warning(
                        f"Failed to import callbacks from built-in plugin {plugin_name}: {e}"
                    )
                except Exception as e:
                    logger.error(
                        f"Unexpected error loading built-in plugin {plugin_name}: {e}"
                    )
                finally:
                    # Clear current plugin context
                    _set_current_plugin(None)

    return loaded


def _load_user_plugins(user_plugins_dir: Path) -> list[dict]:
    """Load user plugins from ~/.code_puppy/plugins/.

    Each plugin should be a directory containing a register_callbacks.py file.
    Plugins are loaded by adding their parent to sys.path and importing them.

    Returns list of dicts with plugin info:
        {"name": str, "manifest": PluginManifest or None}
    """
    from code_puppy.plugins.manifest import PluginManifest
    from code_puppy.plugins.permissions import (
        load_manifest,
        validate_plugin_hooks,
        check_permission_violations,
        log_validation_results,
    )

    loaded = []

    if not user_plugins_dir.exists():
        return loaded

    if not user_plugins_dir.is_dir():
        logger.warning(f"User plugins path is not a directory: {user_plugins_dir}")
        return loaded

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

            # Load manifest if it exists
            manifest = load_manifest(item, plugin_name, is_builtin=False)
            if manifest is None:
                logger.debug(f"No manifest.json for user plugin '{plugin_name}'")

            if callbacks_file.exists():
                try:
                    # Set current plugin for hook tracking
                    _set_current_plugin(plugin_name)
                    
                    # Load the plugin module directly from the file
                    module_name = f"{plugin_name}.register_callbacks"
                    spec = importlib.util.spec_from_file_location(
                        module_name, callbacks_file
                    )
                    if spec is None or spec.loader is None:
                        logger.warning(
                            f"Could not create module spec for user plugin: {plugin_name}"
                        )
                        _set_current_plugin(None)
                        continue

                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module

                    spec.loader.exec_module(module)
                    loaded.append({"name": plugin_name, "manifest": manifest})
                    
                    # Validate hooks if we have a manifest
                    if manifest:
                        validation = validate_plugin_hooks(plugin_name, manifest)
                        violations = check_permission_violations(plugin_name, manifest)
                        log_validation_results(plugin_name, validation, violations)
                    else:
                        # Check for permission violations even without manifest
                        violations = check_permission_violations(plugin_name, None)
                        for v in violations:
                            logger.warning(v)

                except ImportError as e:
                    logger.warning(
                        f"Failed to import callbacks from user plugin {plugin_name}: {e}"
                    )
                except Exception as e:
                    logger.error(
                        f"Unexpected error loading user plugin {plugin_name}: {e}",
                        exc_info=True)
                finally:
                    # Clear current plugin context
                    _set_current_plugin(None)
            else:
                # Check if there's an __init__.py - might be a simple plugin
                init_file = item / "__init__.py"
                if init_file.exists():
                    try:
                        # Set current plugin for hook tracking
                        _set_current_plugin(plugin_name)
                        
                        module_name = plugin_name
                        spec = importlib.util.spec_from_file_location(
                            module_name, init_file
                        )
                        if spec is None or spec.loader is None:
                            _set_current_plugin(None)
                            continue

                        module = importlib.util.module_from_spec(spec)
                        sys.modules[module_name] = module
                        spec.loader.exec_module(module)
                        loaded.append({"name": plugin_name, "manifest": manifest})
                        
                        # Validate hooks if we have a manifest
                        if manifest:
                            validation = validate_plugin_hooks(plugin_name, manifest)
                            violations = check_permission_violations(plugin_name, manifest)
                            log_validation_results(plugin_name, validation, violations)
                        else:
                            # Check for permission violations even without manifest
                            violations = check_permission_violations(plugin_name, None)
                            for v in violations:
                                logger.warning(v)

                    except Exception as e:
                        logger.error(
                            f"Unexpected error loading user plugin {plugin_name}: {e}",
                            exc_info=True)
                    finally:
                        # Clear current plugin context
                        _set_current_plugin(None)

    return loaded


def load_plugin_callbacks() -> dict[str, list[dict]]:
    """Dynamically load register_callbacks.py from all plugin sources.

    Loads plugins from:
    1. Built-in plugins in the code_puppy/plugins/ directory
    2. User plugins in ~/.code_puppy/plugins/

    Returns dict with 'builtin' and 'user' keys containing lists of plugin info:
    Each item is a dict: {"name": str, "manifest": PluginManifest or None}

    NOTE: This function is idempotent - calling it multiple times will only
    load plugins once. Subsequent calls return empty lists.
    """
    global _PLUGINS_LOADED

    # Prevent duplicate loading - plugins register callbacks at import time,
    # so re-importing would cause duplicate registrations
    if _PLUGINS_LOADED:
        logger.debug("Plugins already loaded, skipping duplicate load")
        return {"builtin": [], "user": []}

    # Wrap register_callback to track which plugin registers which hooks
    _wrap_register_callback_for_tracking()

    plugins_dir = Path(__file__).parent

    builtin_loaded = _load_builtin_plugins(plugins_dir)
    user_loaded = _load_user_plugins(USER_PLUGINS_DIR)

    result = {
        "builtin": builtin_loaded,
        "user": user_loaded,
    }

    _PLUGINS_LOADED = True
    
    # Extract just names for the log message
    builtin_names = [p["name"] for p in builtin_loaded]
    user_names = [p["name"] for p in user_loaded]
    logger.debug(f"Loaded plugins: builtin={builtin_names}, user={user_names}")

    # Drain any events that were buffered during plugin loading
    from code_puppy.callbacks import drain_all_backlogs
    drained = drain_all_backlogs()
    if drained:
        logger.debug(f"Drained backlogged events for phases: {list(drained.keys())}")

    return result


def get_user_plugins_dir() -> Path:
    """Return the path to the user plugins directory."""
    return USER_PLUGINS_DIR


def ensure_user_plugins_dir() -> Path:
    """Create the user plugins directory if it doesn't exist.

    Returns the path to the directory.
    """
    USER_PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    return USER_PLUGINS_DIR
