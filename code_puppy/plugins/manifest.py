"""Plugin manifest data model for declaring plugin capabilities and permissions.

This module defines the PluginManifest dataclass that describes what a plugin
does and what permissions it requires. Manifests are loaded from manifest.json
files in plugin directories.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Valid trust levels for plugins
TRUST_LEVELS = ("builtin", "user", "untrusted")

# Default manifest values
DEFAULT_DECLARED_HOOKS: list[str] = field(default_factory=list)
DEFAULT_FILE_ACCESS = False
DEFAULT_SHELL_ACCESS = False
DEFAULT_NETWORK_ACCESS = False


@dataclass(frozen=True)
class PluginManifest:
    """Declaration of plugin capabilities and required permissions.

    Plugins should include a manifest.json in their directory to declare
    what hooks they register and what permissions they need. This allows
    the system to:

    1. Warn about undeclared hook usage (plugin may be doing unexpected things)
    2. Provide visibility into what plugins can do (security audit)
    3. Allow users to make informed decisions about which plugins to enable

    Example manifest.json:
        {
            "name": "shell_safety",
            "declared_hooks": ["run_shell_command"],
            "file_access": false,
            "shell_access": true,
            "network_access": false,
            "trust_level": "builtin"
        }

    Attributes:
        name: Unique identifier for the plugin
        declared_hooks: List of callback hook names this plugin registers
        file_access: Whether the plugin reads or writes files
        shell_access: Whether the plugin executes shell commands
        network_access: Whether the plugin makes network requests
        trust_level: One of "builtin", "user", or "untrusted"
    """

    name: str
    declared_hooks: list[str] = field(default_factory=list)
    file_access: bool = False
    shell_access: bool = False
    network_access: bool = False
    trust_level: str = "user"

    def __post_init__(self) -> None:
        """Validate trust level is one of the allowed values."""
        if self.trust_level not in TRUST_LEVELS:
            object.__setattr__(
                self,
                "trust_level",
                "untrusted" if self.trust_level != "builtin" else "user",
            )
            logger.warning(
                f"Plugin '{self.name}' has invalid trust_level, defaulting to safer value"
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_name: str = "unknown") -> PluginManifest:
        """Create a PluginManifest from a dictionary (e.g., parsed JSON).

        Args:
            data: Dictionary containing manifest fields
            default_name: Fallback name if not specified in data

        Returns:
            A new PluginManifest instance
        """
        return cls(
            name=data.get("name", default_name),
            declared_hooks=list(data.get("declared_hooks", [])),
            file_access=bool(data.get("file_access", False)),
            shell_access=bool(data.get("shell_access", False)),
            network_access=bool(data.get("network_access", False)),
            trust_level=data.get("trust_level", "user"),
        )

    @classmethod
    def from_json(cls, json_str: str, default_name: str = "unknown") -> PluginManifest:
        """Create a PluginManifest from a JSON string.

        Args:
            json_str: JSON string containing manifest fields
            default_name: Fallback name if not specified in JSON

        Returns:
            A new PluginManifest instance

        Raises:
            json.JSONDecodeError: If json_str is not valid JSON
        """
        data = json.loads(json_str)
        return cls.from_dict(data, default_name)

    @classmethod
    def from_file(cls, path: Path | str, default_name: str = "unknown") -> PluginManifest:
        """Create a PluginManifest from a JSON file.

        Args:
            path: Path to the manifest.json file
            default_name: Fallback name if not specified in file

        Returns:
            A new PluginManifest instance

        Raises:
            FileNotFoundError: If the file doesn't exist
            json.JSONDecodeError: If the file is not valid JSON
        """
        path_obj = Path(path)
        with open(path_obj, "r", encoding="utf-8") as f:
            return cls.from_json(f.read(), default_name)

    def to_dict(self) -> dict[str, Any]:
        """Convert the manifest to a dictionary.

        Returns:
            Dictionary representation of this manifest
        """
        return {
            "name": self.name,
            "declared_hooks": self.declared_hooks,
            "file_access": self.file_access,
            "shell_access": self.shell_access,
            "network_access": self.network_access,
            "trust_level": self.trust_level,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert the manifest to a JSON string.

        Args:
            indent: Number of spaces for indentation (default: 2)

        Returns:
            JSON string representation of this manifest
        """
        return json.dumps(self.to_dict(), indent=indent)

    def declares_hook(self, hook_name: str) -> bool:
        """Check if this manifest declares a specific hook.

        Args:
            hook_name: Name of the hook to check

        Returns:
            True if the hook is in declared_hooks, False otherwise
        """
        return hook_name in self.declared_hooks

    def has_any_sensitive_access(self) -> bool:
        """Check if this plugin has any sensitive permissions.

        Returns:
            True if file_access, shell_access, or network_access is True
        """
        return self.file_access or self.shell_access or self.network_access
