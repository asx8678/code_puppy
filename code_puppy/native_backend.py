"""Native backend adapter — unified interface for native acceleration capabilities.

This module provides a single entry point for all native acceleration:
- MESSAGE_CORE: code_puppy_core (message serialization)
- FILE_OPS: Elixir FileOps / Python fallback (list_files, grep, read_file)
- REPO_INDEX: Python indexer via repo_compass (Elixir indexer available)
- PARSE: turbo_parse / Elixir NIF (tree-sitter parsing)

All methods gracefully fall back to Python implementations when native modules
are unavailable, ensuring the system works regardless of Rust build status.

Backend Preference (bd-13):
- ELIXIR_FIRST (default): Try Elixir, fall back to Rust/Python
- RUST_FIRST: Try Rust first (for PARSE, skips Elixir if turbo_parse available)
- PYTHON_ONLY: Use only Python fallbacks

bd-61: Phase 1 of Fast Puppy rewrite — native backend adapter.
bd-62: Phase 2 — Add Elixir control plane routing for file operations.
bd-11: Phase 4 — Add Elixir NIF routing for parse operations.
bd-13: Fix RUST_FIRST semantics, explicit capability routing, cache all turbo_parse imports.
"""

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from code_puppy.config import get_acceleration_config

# Re-export message core types for consumers routing through NativeBackend (bd-67)
from code_puppy._core_bridge import (
    MessageBatchHandle,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapabilityInfo:
    """Information about a native capability."""

    name: str
    configured: str  # "rust", "python", or "elixir"
    available: bool
    active: bool
    status: str  # "active", "disabled", "unavailable"


class BackendPreference(str, Enum):
    """Backend preference for routing native operations.

    bd-62: Controls the priority order for backend selection.
    bd-13: RUST_FIRST semantics fixed — for PARSE, skips Elixir when turbo_parse available.

    Routing behavior per capability:
    - MESSAGE_CORE: RUST_ONLY (no Elixir support)
    - FILE_OPS/REPO_INDEX: ELIXIR_FIRST → Elixir → Python; RUST_FIRST → Elixir → Python
      (no Rust fallback since turbo_ops removed in bd-76)
    - PARSE: ELIXIR_FIRST → Elixir → Rust → Python; RUST_FIRST → Rust → Elixir → Python
      (RUST_FIRST skips Elixir when turbo_parse available)
    """

    ELIXIR_FIRST = "elixir_first"  # Try Elixir first, then native fallbacks
    RUST_FIRST = "rust_first"  # Try Rust first (for PARSE, skips Elixir if turbo_parse available)
    PYTHON_ONLY = "python_only"  # Only use Python fallbacks


class NativeBackend:
    """Unified interface for native acceleration capabilities.

    This class provides a single entry point for all native acceleration,
    with automatic fallback to Python implementations when native modules
    are unavailable.

    bd-63: Per-capability enable/disable profiles replace global toggle.

    Example:
        # Check what's available
        status = NativeBackend.get_status()

        # Use file operations (auto-fallback to Python)
        files = await NativeBackend.list_files(".")
        matches = await NativeBackend.grep("def ", "src")
        content = await NativeBackend.read_file("main.py")

        # Use message core
        serialized = NativeBackend.serialize_messages(messages)

        # Use parsing (stub for now)
        ast = NativeBackend.parse_file("main.py", "python")
    """

    # Capability categories
    class Capabilities:
        """Capability names as constants."""

        MESSAGE_CORE = "message_core"  # code_puppy_core
        FILE_OPS = "file_ops"  # Elixir FileOps / Python fallback
        EDIT_OPS = "edit_ops"  # Elixir Text operations (fuzzy_match, replace, diff)
        REPO_INDEX = "repo_index"  # Repository indexing (Elixir + Python fallback)
        PARSE = "parse"  # turbo_parse

    _turbo_parse_imports: dict[str, Any] | None = None

    # bd-62: Backend preference for routing decisions
    # bd-89: Default is ELIXIR_FIRST for runtime profile persistence
    # bd-13: Fixed RUST_FIRST semantics for PARSE capability (skips Elixir when turbo_parse available)
    _backend_preference: BackendPreference = BackendPreference.ELIXIR_FIRST

    # bd-63: Per-capability enabled state (user can disable even if available)
    _capability_enabled: dict[str, bool] = {
        Capabilities.MESSAGE_CORE: True,
        Capabilities.FILE_OPS: True,
        Capabilities.EDIT_OPS: True,
        Capabilities.REPO_INDEX: True,
        Capabilities.PARSE: True,
    }

    # bd-63: Legacy global toggle for backward compatibility
    _legacy_global_enabled: bool | None = None

    # bd-11: Track last source used for each capability
    _last_source: dict[str, str] = {}

    # -------------------------------------------------------------------------
    # Elixir Bridge Integration (bd-62)
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Per-Capability Enable/Disable (bd-63)
    # -------------------------------------------------------------------------

    @classmethod
    def enable_capability(cls, capability: str) -> bool:
        """Enable a capability (will use native if available).

        Args:
            capability: One of the Capability constants.

        Returns:
            True if capability exists and was enabled, False if unknown.
        """
        if capability in cls._capability_enabled:
            cls._capability_enabled[capability] = True
            logger.debug(f"Enabled capability: {capability}")
            return True
        return False

    @classmethod
    def disable_capability(cls, capability: str) -> bool:
        """Disable a capability (will use Python fallback).

        Args:
            capability: One of the Capability constants.

        Returns:
            True if capability exists and was disabled, False if unknown.
        """
        if capability in cls._capability_enabled:
            cls._capability_enabled[capability] = False
            logger.debug(f"Disabled capability: {capability}")
            return True
        return False

    @classmethod
    def is_enabled(cls, capability: str) -> bool:
        """Check if capability is enabled by user preference.

        Args:
            capability: One of the Capability constants.

        Returns:
            True if capability is enabled (may still be unavailable).
        """
        return cls._capability_enabled.get(capability, False)

    @classmethod
    def is_active(cls, capability: str) -> bool:
        """Check if capability is both available AND enabled.

        Args:
            capability: One of the Capability constants.

        Returns:
            True if capability is available and user has enabled it.
        """
        return cls.is_available(capability) and cls.is_enabled(capability)

    @classmethod
    def enable_all(cls) -> None:
        """Enable all capabilities."""
        for cap in cls._capability_enabled:
            cls._capability_enabled[cap] = True
        logger.debug("Enabled all capabilities")

    @classmethod
    def disable_all(cls) -> None:
        """Disable all capabilities (Python-only mode)."""
        for cap in cls._capability_enabled:
            cls._capability_enabled[cap] = False
        logger.debug("Disabled all capabilities")

    @classmethod
    def load_preferences(cls) -> None:
        """Load capability preferences from config.

        bd-63: Supports both legacy global toggle and per-capability settings.
        bd-89: Added backend_preference loading for runtime profile persistence.
        """
        from code_puppy.config import get_value

        # Check legacy global toggle first (for backward compatibility)
        legacy = get_value("enable_fast_puppy")
        if legacy is not None:
            enabled = str(legacy).strip().lower() in ("true", "1", "yes", "on")
            cls._legacy_global_enabled = enabled
            for cap in cls._capability_enabled:
                cls._capability_enabled[cap] = enabled
            logger.info(f"bd-92: Migrating legacy enable_fast_puppy={enabled} to per-capability keys")
            # Migration will save per-capability keys on next config update
            return

        # Load per-capability preferences
        for cap in cls._capability_enabled:
            key = f"fast_puppy.{cap}"
            value = get_value(key)
            if value is not None:
                cls._capability_enabled[cap] = str(value).strip().lower() in (
                    "true",
                    "1",
                    "yes",
                    "on",
                )
                logger.debug(f"Loaded preference {key}={cls._capability_enabled[cap]}")

        # bd-89: Load backend preference for runtime profile persistence
        backend_pref = get_value("native_backend_preference")
        if backend_pref is not None:
            pref_str = str(backend_pref).strip().lower()
            try:
                cls._backend_preference = BackendPreference(pref_str)
                logger.debug(f"Loaded backend_preference={pref_str}")
            except ValueError:
                logger.warning(
                    f"Invalid backend_preference value: {pref_str}, keeping default"
                )

    @classmethod
    def save_preferences(cls) -> None:
        """Save capability preferences to config.

        bd-63: Saves per-capability settings (not legacy global toggle).
        bd-89: Added backend_preference saving for runtime profile persistence.
        """
        from code_puppy.config import set_config_value

        for cap, enabled in cls._capability_enabled.items():
            key = f"fast_puppy.{cap}"
            set_config_value(key, "true" if enabled else "false")
            logger.debug(f"Saved preference {key}={enabled}")

        # bd-89: Save backend preference for runtime profile persistence
        set_config_value("native_backend_preference", cls._backend_preference.value)
        logger.debug(f"Saved backend_preference={cls._backend_preference.value}")

    @classmethod
    def set_capabilities_from_legacy(cls, enabled: bool) -> None:
        """Set all capabilities from legacy global toggle.

        bd-63: Used when migrating from old enable_fast_puppy config.

        Args:
            enabled: True to enable all, False to disable all.
        """
        cls._legacy_global_enabled = enabled
        for cap in cls._capability_enabled:
            cls._capability_enabled[cap] = enabled
        logger.debug(f"Set all capabilities from legacy toggle: {enabled}")

    # -------------------------------------------------------------------------
    # Elixir Bridge Integration (bd-62)
    # -------------------------------------------------------------------------

    @classmethod
    def _is_elixir_available(cls) -> bool:
        """Check if Elixir control plane is connected and available.

        Returns:
            True if Elixir control plane can be used for file operations.
        """
        try:
            from code_puppy.plugins.elixir_bridge import is_connected

            return is_connected()
        except ImportError:
            return False

    @classmethod
    def is_elixir_connected(cls) -> bool:
        """Check if Elixir bridge is connected.  # bd-90"""
        return cls._is_elixir_available()

    @classmethod
    def _call_elixir(cls, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Make JSON-RPC call to Elixir control plane.

        Args:
            method: JSON-RPC method name (e.g., "file_list")
            params: Method parameters dict

        Returns:
            Response dict from Elixir

        Raises:
            ConnectionError: If Elixir is not connected
            Exception: If the call fails
        """
        from code_puppy.plugins.elixir_bridge import call_method

        return call_method(method, params)

    @classmethod
    def set_backend_preference(cls, preference: str | BackendPreference) -> None:
        """Set the backend preference for file operations.

        bd-62: Controls the priority order for routing file operations.

        Args:
            preference: One of "elixir_first", "rust_first", or "python_only"

        Example:
            NativeBackend.set_backend_preference("elixir_first")
            # Now Elixir will be tried first, with Rust/Python fallback
        """
        if isinstance(preference, str):
            cls._backend_preference = BackendPreference(preference)
        else:
            cls._backend_preference = preference

    @classmethod
    def get_backend_preference(cls) -> BackendPreference:
        """Get the current backend preference.

        Returns:
            Current BackendPreference value.
        """
        return cls._backend_preference

    @classmethod
    def _is_turbo_parse_entrypoint_available(cls, entrypoint: str) -> bool:
        """Check if a specific turbo_parse entrypoint is available.

        bd-13-partial-fix: Per-entrypoint checks for partial turbo_parse builds.

        Args:
            entrypoint: Entrypoint name (e.g., "parse_file", "extract_symbols")

        Returns:
            True if the specific entrypoint exists and is callable.
        """
        turbo = cls._get_turbo_parse()
        if not turbo.get("available", False):
            return False
        func = turbo.get(entrypoint)
        return func is not None and callable(func)

    @classmethod
    def _should_use_elixir(cls, capability: str, entrypoint: str | None = None) -> bool:
        """Determine if Elixir should be used for a capability.

        bd-76: Routing logic based on backend preference and Elixir availability.
        bd-13: RUST_FIRST semantics fixed — for PARSE, skips Elixir when turbo_parse available.
        bd-13-fix: PYTHON_ONLY must block ALL native backend calls including Elixir.
        bd-13-partial-fix: For PARSE, checks specific entrypoint availability, not just generic.

        Args:
            capability: Capability name (e.g., "file_ops")
            entrypoint: Optional entrypoint name for PARSE capability. When provided,
                       checks if that specific turbo_parse entrypoint is available.

        Returns:
            True if Elixir should be tried for this capability.
        """
        # bd-13-fix: PYTHON_ONLY blocks ALL native backends
        if cls._backend_preference == BackendPreference.PYTHON_ONLY:
            return False

        # Also check if the capability is enabled
        if not cls.is_enabled(capability):
            return False

        # For PARSE with RUST_FIRST: skip Elixir if turbo_parse is available
        # bd-13-partial-fix: Check specific entrypoint, not just generic availability
        if capability == cls.Capabilities.PARSE:
            if cls._backend_preference == BackendPreference.RUST_FIRST:
                # If entrypoint specified, check that specific entrypoint
                if entrypoint:
                    if cls._is_turbo_parse_entrypoint_available(entrypoint):
                        return False  # RUST_FIRST + specific entrypoint available → skip Elixir
                else:
                    # Fallback to generic check for backward compatibility
                    turbo = cls._get_turbo_parse()
                    if turbo.get("available", False):
                        return False  # RUST_FIRST + turbo_parse available → skip Elixir

        # ELIXIR_FIRST or RUST_FIRST (with fallback): use Elixir if available
        return cls._is_elixir_available()

    @classmethod
    def _should_use_turbo_parse(cls) -> bool:
        """Determine if turbo_parse should be used.

        bd-13-fix: Check if turbo_parse should be tried based on preference and capability state.

        Returns:
            True if turbo_parse should be tried.
        """
        # PYTHON_ONLY blocks ALL native backends
        if cls._backend_preference == BackendPreference.PYTHON_ONLY:
            return False

        # Check if PARSE capability is enabled
        if not cls.is_enabled(cls.Capabilities.PARSE):
            return False

        turbo = cls._get_turbo_parse()
        return turbo.get("available", False)

    @classmethod
    def get_capability_routing(
        cls, capability: str, entrypoint: str | None = None
    ) -> dict[str, Any]:
        """Get explicit routing plan for a capability.

        bd-13: Makes capability routing explicit and introspectable.
        bd-13-fix-semantics: Fixed PYTHON_ONLY reporting to reflect actual runtime behavior:
            - Disabled capability => will_use="disabled" (or None)
            - FILE_OPS/REPO_INDEX with PYTHON_ONLY => route to Python, not disabled
            - PARSE with PYTHON_ONLY => route to python_fallback, not disabled
        bd-13-partial-fix: Added entrypoint parameter for entrypoint-aware routing in
            partial turbo_parse builds (e.g., parse_source available but parse_file missing).

        Args:
            capability: One of the Capability constants.
            entrypoint: Optional entrypoint name for PARSE capability. When provided,
                       checks specific entrypoint availability instead of generic turbo_parse.
                       Use "parse_file" for status/reporting (the primary parse entrypoint).

        Returns:
            Dict with routing info:
            - backends: Ordered list of (backend_name, available) tuples
            - preference: Current backend preference setting
            - will_use: The backend that will actually be used (first available),
                        or "disabled" if capability is disabled
        """
        preference = cls._backend_preference
        elixir_avail = cls._is_elixir_available()
        turbo = cls._get_turbo_parse()
        # bd-13-partial-fix: For PARSE with entrypoint, check specific entrypoint availability
        if capability == cls.Capabilities.PARSE and entrypoint:
            turbo_avail = cls._is_turbo_parse_entrypoint_available(entrypoint)
        else:
            turbo_avail = turbo.get("available", False)
        capability_enabled = cls.is_enabled(capability)

        # bd-13-fix-semantics: Only report disabled if capability is actually disabled
        # PYTHON_ONLY should report the Python fallback, not "disabled"
        if not capability_enabled:
            return {
                "backends": [],
                "preference": preference.value,
                "will_use": "disabled",
                "capability": capability,
                "reason": "capability_disabled",
            }

        # Determine backend order and availability per capability
        if capability == cls.Capabilities.MESSAGE_CORE:
            # MESSAGE_CORE: Rust only (no Elixir support)
            from code_puppy._core_bridge import RUST_AVAILABLE

            backends = [
                ("rust", RUST_AVAILABLE),
                ("python", True),  # Always available fallback
            ]

        elif capability in (cls.Capabilities.FILE_OPS, cls.Capabilities.REPO_INDEX):
            # FILE_OPS/REPO_INDEX: Elixir → Python (no Rust since turbo_ops removed)
            # bd-13-fix-semantics: In PYTHON_ONLY, only Python is available
            if preference == BackendPreference.PYTHON_ONLY:
                backends = [
                    ("python", True),  # Python fallback always available
                ]
            else:
                backends = [
                    ("elixir", elixir_avail),
                    ("python", True),  # Always available fallback
                ]

        elif capability == cls.Capabilities.EDIT_OPS:
            # EDIT_OPS: Elixir → Python (no Rust since bd-40 removed edit modules)
            # bd-41: Elixir-first routing for fuzzy_match, replace, diff
            if preference == BackendPreference.PYTHON_ONLY:
                backends = [
                    ("python", True),  # Python fallback always available
                ]
            else:
                backends = [
                    ("elixir", elixir_avail),
                    ("python", True),  # Always available fallback
                ]

        elif capability == cls.Capabilities.PARSE:
            # PARSE: Depends on preference
            # bd-13-fix-semantics: In PYTHON_ONLY, only python_fallback is available
            if preference == BackendPreference.PYTHON_ONLY:
                backends = [
                    ("python_fallback", True),  # Python fallback always available
                ]
            elif preference == BackendPreference.RUST_FIRST and turbo_avail:
                backends = [
                    ("turbo_parse", turbo_avail),
                    ("elixir", elixir_avail),
                    ("python_fallback", True),
                ]
            else:
                # ELIXIR_FIRST or RUST_FIRST with turbo unavailable
                backends = [
                    ("elixir", elixir_avail),
                    ("turbo_parse", turbo_avail),
                    ("python_fallback", True),
                ]
        else:
            backends = [("python", True)]

        # Determine which backend will actually be used
        will_use = None
        for name, available in backends:
            if available:
                will_use = name
                break

        return {
            "backends": backends,
            "preference": preference.value,
            "will_use": will_use,
            "capability": capability,
        }

    # -------------------------------------------------------------------------
    # Native Module Loading
    # -------------------------------------------------------------------------

    @classmethod
    def _get_turbo_parse(cls) -> dict[str, Any]:
        """Lazy-load turbo_parse imports with fallback handling.

        bd-13: Expanded to cache all parse-related functions for explicit routing.
        bd-13-fix: Use getattr to allow partial imports - older/partial turbo_parse
        builds still expose core parse functions even if newer methods are missing.
        """
        if cls._turbo_parse_imports is None:
            imports: dict[str, Any] = {
                "available": False,
                "parse_file": None,
                "parse_source": None,
                "extract_symbols": None,
                "supported_languages": None,
                "is_language_supported": None,
                "extract_syntax_diagnostics": None,
                "get_folds": None,
                "get_highlights": None,
                "health_check": None,
                "stats": None,
            }
            try:
                import turbo_parse

                # bd-13-fix: Use getattr to allow partial imports
                # This lets older/partial turbo_parse builds still work
                imports["parse_file"] = getattr(turbo_parse, "parse_file", None)
                imports["parse_source"] = getattr(turbo_parse, "parse_source", None)
                imports["extract_symbols"] = getattr(turbo_parse, "extract_symbols", None)
                imports["supported_languages"] = getattr(turbo_parse, "supported_languages", None)
                imports["is_language_supported"] = getattr(turbo_parse, "is_language_supported", None)
                imports["extract_syntax_diagnostics"] = getattr(turbo_parse, "extract_syntax_diagnostics", None)
                imports["get_folds"] = getattr(turbo_parse, "get_folds", None)
                imports["get_highlights"] = getattr(turbo_parse, "get_highlights", None)
                imports["health_check"] = getattr(turbo_parse, "health_check", None)
                imports["stats"] = getattr(turbo_parse, "stats", None)
                # Consider available if at least core parse functions exist
                imports["available"] = (
                    imports["parse_file"] is not None or
                    imports["parse_source"] is not None
                )
                if imports["available"]:
                    logger.debug("turbo_parse loaded with partial availability")
            except (ImportError, SystemError) as e:
                logger.debug(f"turbo_parse not available: {e}")

            cls._turbo_parse_imports = imports

        return cls._turbo_parse_imports

    @classmethod
    def get_status(cls) -> dict[str, CapabilityInfo]:
        """Return status of all capabilities.

        bd-63: Now includes user enable/disable preferences.
        bd-13: Uses NativeBackend's own turbo_parse cache, not turbo_parse_bridge.

        Returns:
            Dict mapping capability names to CapabilityInfo objects.
        """
        config = get_acceleration_config()

        # Import bridge modules to check their status
        from code_puppy._core_bridge import RUST_AVAILABLE, is_rust_enabled

        # bd-13: Use NativeBackend's own turbo_parse cache instead of turbo_parse_bridge
        turbo_parse = cls._get_turbo_parse()
        TURBO_PARSE_AVAILABLE = turbo_parse.get("available", False)

        # bd-62: Check Elixir availability
        elixir_available = cls._is_elixir_available()

        # bd-76: file_ops availability — Elixir or Python fallback (turbo_ops removed)
        file_ops_tech_available = (
            elixir_available or True
        )  # Python fallback always available
        file_ops_user_enabled = cls.is_enabled(cls.Capabilities.FILE_OPS)
        file_ops_active = file_ops_tech_available and file_ops_user_enabled

        # bd-76: repo_index — Python indexer always available
        repo_index_tech_available = True  # Python fallback via repo_compass
        repo_index_user_enabled = cls.is_enabled(cls.Capabilities.REPO_INDEX)
        repo_index_active = repo_index_tech_available and repo_index_user_enabled

        # bd-41: edit_ops availability — Elixir or Python fallback (Rust modules removed in bd-40)
        edit_ops_tech_available = True  # Python fallback always available
        edit_ops_user_enabled = cls.is_enabled(cls.Capabilities.EDIT_OPS)
        edit_ops_active = edit_ops_tech_available and edit_ops_user_enabled

        # Determine message_core technical availability
        msg_core_tech_available = RUST_AVAILABLE
        msg_core_user_enabled = cls.is_enabled(cls.Capabilities.MESSAGE_CORE)
        # Legacy: also respect _core_bridge.is_rust_enabled() for backward compat
        msg_core_active = (
            msg_core_tech_available and msg_core_user_enabled and is_rust_enabled()
        )

        # Determine parse technical availability (bd-11: include Elixir)
        parse_tech_available = TURBO_PARSE_AVAILABLE or cls._is_elixir_available()
        parse_user_enabled = cls.is_enabled(cls.Capabilities.PARSE)
        parse_active = parse_tech_available and parse_user_enabled

        return {
            cls.Capabilities.MESSAGE_CORE: CapabilityInfo(
                name=cls.Capabilities.MESSAGE_CORE,
                configured=config.get("puppy_core", "python"),
                available=msg_core_tech_available,
                active=msg_core_active,
                status="active"
                if msg_core_active
                else ("disabled" if not msg_core_user_enabled else "unavailable"),
            ),
            cls.Capabilities.FILE_OPS: CapabilityInfo(
                name=cls.Capabilities.FILE_OPS,
                configured="elixir",
                available=file_ops_tech_available,
                active=file_ops_active,
                status="active"
                if file_ops_active
                else ("disabled" if not file_ops_user_enabled else "unavailable"),
            ),
            cls.Capabilities.EDIT_OPS: CapabilityInfo(
                name=cls.Capabilities.EDIT_OPS,
                configured="elixir",
                available=edit_ops_tech_available,
                active=edit_ops_active,
                status="active"
                if edit_ops_active
                else ("disabled" if not edit_ops_user_enabled else "unavailable"),
            ),
            cls.Capabilities.REPO_INDEX: CapabilityInfo(
                name=cls.Capabilities.REPO_INDEX,
                configured="elixir",
                available=repo_index_tech_available,
                active=repo_index_active,
                status="active"
                if repo_index_active
                else ("disabled" if not repo_index_user_enabled else "unavailable"),
            ),
            cls.Capabilities.PARSE: CapabilityInfo(
                name=cls.Capabilities.PARSE,
                configured=config.get("turbo_parse", "python"),
                available=parse_tech_available,
                active=parse_active,
                status="active"
                if parse_active
                else ("disabled" if not parse_user_enabled else "unavailable"),
            ),
        }

    @classmethod
    def get_detailed_status(cls) -> dict[str, Any]:
        """Return detailed status including all backend sources.

        bd-62: Extended status with Elixir and backend preference info.
        bd-13: Fixed message_core.rust_available to reflect real availability.

        Returns:
            Dict with detailed capability status, backend info, and routing plan.
        """
        turbo_parse = cls._get_turbo_parse()
        elixir_available = cls._is_elixir_available()

        # bd-13: Get real Rust availability from _core_bridge
        from code_puppy._core_bridge import RUST_AVAILABLE

        return {
            "message_core": {
                "available": True,
                "rust_available": RUST_AVAILABLE,  # bd-13: Real availability, not hardcoded
                "source": cls._get_message_core_source(),
                "routing": cls.get_capability_routing(cls.Capabilities.MESSAGE_CORE),
            },
            "file_ops": {
                "available": True,  # Python fallback always available
                "elixir_available": elixir_available,
                "source": cls._get_file_ops_source(),
                "backend_preference": cls._backend_preference.value,
                "routing": cls.get_capability_routing(cls.Capabilities.FILE_OPS),
            },
            "edit_ops": {
                "available": True,  # Python fallback always available
                "elixir_available": elixir_available,
                "source": "elixir" if elixir_available and cls.is_enabled(cls.Capabilities.EDIT_OPS) else "python",
                "routing": cls.get_capability_routing(cls.Capabilities.EDIT_OPS),
            },
            "repo_index": {
                "available": True,  # Python fallback always available
                "elixir_available": elixir_available,
                "source": cls._last_source.get(
                    cls.Capabilities.REPO_INDEX,
                    "elixir" if elixir_available else "python",
                ),
                "routing": cls.get_capability_routing(cls.Capabilities.REPO_INDEX),
            },
            "parse": {
                "available": turbo_parse.get("available", False) or elixir_available,
                "rust_available": turbo_parse.get("available", False),
                "elixir_available": elixir_available,
                "routing": cls.get_capability_routing(cls.Capabilities.PARSE),
                "source": cls._last_source.get(cls.Capabilities.PARSE, "unknown"),
            },
        }

    @classmethod
    def _get_message_core_source(cls) -> str:
        """Get the actual source for message_core capability."""
        if not cls.is_active(cls.Capabilities.MESSAGE_CORE):
            return "disabled"
        try:
            from code_puppy._core_bridge import is_rust_enabled

            if is_rust_enabled():
                return "rust"
        except ImportError:
            pass
        return "python"

    @classmethod
    def _get_file_ops_source(cls) -> str:
        """Determine the effective file_ops source based on routing logic.

        bd-76: turbo_ops removed. Source is now Elixir or Python.

        Returns:
            One of "elixir" or "python".
        """
        if cls._backend_preference == BackendPreference.PYTHON_ONLY:
            return "python"

        if cls._is_elixir_available():
            return "elixir"

        return "python"

    @classmethod
    def is_available(cls, capability: str) -> bool:
        """Check if a specific capability is available.

        Args:
            capability: One of the Capability constants.

        Returns:
            True if the capability is available and active.
        """
        status = cls.get_status()
        info = status.get(capability)
        return info.active if info else False

    @classmethod
    def _run_with_fallback(
        cls,
        native_func: Callable | None,
        fallback_func: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute native function with fallback to Python on failure.

        Args:
            native_func: The native (Rust) function to try first.
            fallback_func: The Python fallback function.
            *args, **kwargs: Arguments to pass to the function.

        Returns:
            Result from either native or fallback function.
        """
        if native_func is not None:
            try:
                return native_func(*args, **kwargs)
            except Exception as e:
                logger.debug(f"Native operation failed, using fallback: {e}")

        return fallback_func(*args, **kwargs)

    @classmethod
    def _async_run_with_fallback(
        cls,
        native_func: Callable | None,
        fallback_func: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute native function in thread pool with fallback to async Python.

        Args:
            native_func: The native (Rust) function to try first (runs in thread pool).
            fallback_func: The async Python fallback function.
            *args, **kwargs: Arguments to pass to the function.

        Returns:
            Result from either native or fallback function.
        """
        if native_func is not None:
            try:
                # Run native function in thread pool (Rust functions are usually sync)
                return asyncio.to_thread(native_func, *args, **kwargs)
            except Exception as e:
                logger.debug(f"Native operation failed, using fallback: {e}")

        return fallback_func(*args, **kwargs)

    # -------------------------------------------------------------------------
    # File Operations (Elixir / Python fallback)
    # -------------------------------------------------------------------------

    @classmethod
    def list_files(
        cls,
        directory: str = ".",
        recursive: bool = True,
        *,
        _prefer_native: bool = True,
    ) -> dict[str, Any]:
        """List files with fallback to Python.

        bd-62: Routes through Elixir control plane when available and preferred.

        Args:
            directory: Directory to list.
            recursive: Whether to list recursively.
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            Dict with "files" key containing list of file paths,
            or "error" key if listing failed.
        """
        # bd-63: Check if capability is enabled first
        if not cls.is_active(cls.Capabilities.FILE_OPS):
            _prefer_native = False

        # bd-62: Try Elixir first if preferred and available
        if _prefer_native and cls._should_use_elixir("file_ops"):
            try:
                result = cls._call_elixir(
                    "file_list",
                    {
                        "directory": directory,
                        "recursive": recursive,
                    },
                )
                # Normalize Elixir response format
                if result.get("success", True):
                    return {
                        "files": [
                            f.get("path", f) if isinstance(f, dict) else f
                            for f in result.get("files", [])
                        ],
                        "count": result.get("file_count", len(result.get("files", []))),
                        "total_size": result.get("total_size", 0),
                        "source": "elixir",
                    }
                else:
                    logger.debug(
                        f"Elixir file_list returned error: {result.get('error')}"
                    )
            except NotImplementedError:
                # Elixir transport not yet implemented, fall through
                logger.debug("Elixir transport not implemented, falling back")
            except Exception as e:
                logger.debug(f"Elixir file_list failed, falling back: {e}")

        def _python_fallback(dir_path: str, rec: bool) -> dict[str, Any]:
            """Python fallback using standard library with proper error handling."""
            import os

            dir_path = os.path.abspath(os.path.expanduser(dir_path))

            # Check if directory exists
            if not os.path.exists(dir_path):
                return {
                    "error": f"Directory '{dir_path}' does not exist",
                    "files": [],
                    "count": 0,
                    "source": "python_fallback",
                }
            if not os.path.isdir(dir_path):
                return {
                    "error": f"'{dir_path}' is not a directory",
                    "files": [],
                    "count": 0,
                    "source": "python_fallback",
                }

            try:
                files = []
                if rec:
                    for root, _dirs, filenames in os.walk(dir_path):
                        for filename in filenames:
                            full_path = os.path.join(root, filename)
                            rel_path = os.path.relpath(full_path, dir_path)
                            files.append(rel_path)
                else:
                    for entry in os.listdir(dir_path):
                        full_path = os.path.join(dir_path, entry)
                        if os.path.isfile(full_path):
                            files.append(entry)

                return {
                    "files": files,
                    "count": len(files),
                    "source": "python_fallback",
                }
            except Exception as e:
                return {
                    "error": str(e),
                    "files": [],
                    "count": 0,
                    "source": "python_fallback",
                }

        return _python_fallback(directory, recursive)

    @classmethod
    def grep(
        cls,
        pattern: str,
        directory: str = ".",
        *,
        _prefer_native: bool = True,
    ) -> dict[str, Any]:
        """Search files with fallback to Python.

        bd-62: Routes through Elixir control plane when available and preferred.

        Args:
            pattern: Search pattern (regex supported).
            directory: Directory to search in.
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            Dict with "matches" key containing list of match dicts,
            or "error" key if search failed.
        """
        # bd-63: Check if capability is enabled first
        if not cls.is_active(cls.Capabilities.FILE_OPS):
            _prefer_native = False

        # bd-62: Try Elixir first if preferred and available
        if _prefer_native and cls._should_use_elixir("file_ops"):
            try:
                result = cls._call_elixir(
                    "grep_search",
                    {
                        "search_string": pattern,
                        "directory": directory,
                    },
                )
                # Normalize Elixir response format
                if result.get("success", True):
                    matches = result.get("matches", [])
                    return {
                        "matches": matches,
                        "total_matches": len(matches),
                        "files_searched": result.get("files_searched", 0),
                        "source": "elixir",
                    }
                else:
                    logger.debug(
                        f"Elixir grep_search returned error: {result.get('error')}"
                    )
            except NotImplementedError:
                logger.debug("Elixir transport not implemented, falling back")
            except Exception as e:
                logger.debug(f"Elixir grep_search failed, falling back: {e}")

        def _python_fallback(pat: str, dir_path: str) -> dict[str, Any]:
            """Python fallback using re module."""
            import os
            import re

            matches = []
            try:
                regex = re.compile(pat)
                for root, _dirs, files in os.walk(dir_path):
                    for filename in files:
                        if filename.endswith(
                            (
                                ".py",
                                ".js",
                                ".ts",
                                ".java",
                                ".c",
                                ".cpp",
                                ".h",
                                ".rs",
                                ".go",
                                ".rb",
                            )
                        ):
                            filepath = os.path.join(root, filename)
                            try:
                                with open(
                                    filepath, "r", encoding="utf-8", errors="ignore"
                                ) as f:
                                    for line_num, line in enumerate(f, 1):
                                        if regex.search(line):
                                            matches.append(
                                                {
                                                    "file_path": filepath,
                                                    "line_number": line_num,
                                                    "line_content": line.strip()[
                                                        :200
                                                    ],  # Limit line length
                                                }
                                            )
                            except Exception:
                                continue

                return {
                    "matches": matches,
                    "total_matches": len(matches),
                    "source": "python_fallback",
                }
            except Exception as e:
                return {
                    "error": str(e),
                    "matches": [],
                    "total_matches": 0,
                    "source": "python_fallback",
                }

        return _python_fallback(pattern, directory)

    @classmethod
    def read_file(
        cls,
        path: str,
        start_line: int | None = None,
        num_lines: int | None = None,
        *,
        _prefer_native: bool = True,
    ) -> dict[str, Any]:
        """Read file with fallback to Python.

        bd-62: Routes through Elixir control plane when available and preferred.

        Args:
            path: Path to file.
            start_line: Optional 1-based starting line number.
            num_lines: Optional number of lines to read.
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            Dict with "content" key containing file content,
            "num_tokens" with token estimate, or "error" key if read failed.
        """
        import os

        # bd-63: Check if capability is enabled first
        if not cls.is_active(cls.Capabilities.FILE_OPS):
            _prefer_native = False

        # bd-62: Try Elixir first if preferred and available
        if _prefer_native and cls._should_use_elixir("file_ops"):
            try:
                params: dict[str, Any] = {"path": path}
                if start_line is not None:
                    params["start_line"] = start_line
                if num_lines is not None:
                    params["num_lines"] = num_lines

                result = cls._call_elixir("file_read", params)
                # Normalize Elixir response format
                if result.get("success", True):
                    content = result.get("content", "")
                    return {
                        "content": content,
                        "num_tokens": len(content) // 4,  # Rough estimate
                        "total_lines": result.get("total_lines", 0),
                        "source": "elixir",
                    }
                else:
                    logger.debug(
                        f"Elixir file_read returned error: {result.get('error')}"
                    )
            except NotImplementedError:
                logger.debug("Elixir transport not implemented, falling back")
            except Exception as e:
                logger.debug(f"Elixir file_read failed, falling back: {e}")

        def _python_fallback(
            file_path: str, start: int | None, num: int | None
        ) -> dict[str, Any]:
            """Python fallback using standard file operations."""
            try:
                file_path = os.path.abspath(os.path.expanduser(file_path))

                if not os.path.exists(file_path):
                    return {
                        "error": f"File not found: {file_path}",
                        "content": None,
                        "num_tokens": 0,
                        "source": "python_fallback",
                    }

                with open(
                    file_path, "r", encoding="utf-8", errors="surrogateescape"
                ) as f:
                    if start is not None and num is not None:
                        import itertools

                        start_idx = start - 1
                        lines = list(itertools.islice(f, start_idx, start_idx + num))
                        content = "".join(lines)
                    else:
                        content = f.read()

                # Estimate tokens (rough approximation: 4 chars ≈ 1 token)
                num_tokens = len(content) // 4

                return {
                    "content": content,
                    "num_tokens": num_tokens,
                    "source": "python_fallback",
                }
            except Exception as e:
                return {
                    "error": str(e),
                    "content": None,
                    "num_tokens": 0,
                    "source": "python_fallback",
                }

        return _python_fallback(path, start_line, num_lines)

    @classmethod
    def read_files(
        cls,
        paths: list[str],
        start_line: int | None = None,
        num_lines: int | None = None,
        *,
        _prefer_native: bool = True,
    ) -> dict[str, Any]:
        """Batch read files with fallback to Python.

        bd-62: Routes through Elixir control plane when available and preferred.

        Args:
            paths: List of file paths to read.
            start_line: Optional 1-based starting line number (applied to all files).
            num_lines: Optional number of lines to read (applied to all files).
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            Dict with "files" key containing list of file result dicts,
            each with "file_path", "content", "num_tokens", "error", "success" keys.
        """
        # bd-63: Check if capability is enabled first
        if not cls.is_active(cls.Capabilities.FILE_OPS):
            _prefer_native = False

        # bd-62: Try Elixir batch read if preferred and available
        if _prefer_native and cls._should_use_elixir("file_ops"):
            try:
                params: dict[str, Any] = {"paths": paths}
                if start_line is not None:
                    params["start_line"] = start_line
                if num_lines is not None:
                    params["num_lines"] = num_lines

                result = cls._call_elixir("file_read_batch", params)
                # Normalize Elixir response format
                if result.get("success", True):
                    files = result.get("files", [])
                    return {
                        "files": files,
                        "total_files": len(paths),
                        "successful_reads": sum(
                            1 for f in files if f.get("success", False)
                        ),
                        "source": "elixir",
                    }
                else:
                    logger.debug(
                        f"Elixir file_read_batch returned error: {result.get('error')}"
                    )
            except NotImplementedError:
                logger.debug(
                    "Elixir transport not implemented, falling back to sequential"
                )
            except Exception as e:
                logger.debug(f"Elixir file_read_batch failed, falling back: {e}")

        # Fall back to sequential reads (Rust or Python per file)
        results = []
        for path in paths:
            result = cls.read_file(
                path, start_line, num_lines, _prefer_native=_prefer_native
            )
            results.append(
                {
                    "file_path": path,
                    "content": result.get("content"),
                    "num_tokens": result.get("num_tokens", 0),
                    "error": result.get("error"),
                    "success": result.get("error") is None
                    and result.get("content") is not None,
                }
            )

        return {
            "files": results,
            "total_files": len(paths),
            "successful_reads": sum(1 for r in results if r["success"]),
            "source": "native_backend",
        }

    # -------------------------------------------------------------------------
    # Message Core (from code_puppy_core)
    # -------------------------------------------------------------------------

    @classmethod
    def serialize_messages(cls, messages: list) -> list[dict]:
        """Serialize messages for API calls.

        This delegates to _core_bridge for the actual serialization,
        which handles pydantic-ai message objects.

        Args:
            messages: List of pydantic-ai ModelMessage objects.

        Returns:
            List of serialized message dicts.
        """
        from code_puppy._core_bridge import serialize_messages_for_rust

        return serialize_messages_for_rust(messages)

    @classmethod
    def create_message_batch(cls, messages: list) -> Any:
        """Create a MessageBatchHandle for efficient batch operations.

        Args:
            messages: List of pydantic-ai ModelMessage objects.

        Returns:
            MessageBatchHandle for batch operations.
        """

        return MessageBatchHandle(messages)

    @classmethod
    def is_message_core_active(cls) -> bool:
        """Check if message_core (Rust acceleration) is both available AND enabled.

        bd-67: Replaces scattered is_rust_enabled() checks in consumers.
        This is the single entry point for checking if Rust message processing
        is available and should be used.

        Returns:
            True if Rust message core is installed, enabled by user, and active.
        """
        return cls.is_active(cls.Capabilities.MESSAGE_CORE)

    # -------------------------------------------------------------------------
    # Repository Index (Python indexer via repo_compass)
    # -------------------------------------------------------------------------

    @classmethod
    def index_directory(
        cls,
        root: str,
        max_files: int = 40,
        max_symbols_per_file: int = 8,
        *,
        _prefer_native: bool = True,
    ) -> list[dict[str, Any]]:
        """Index directory for repository structure.

        Args:
            root: Root directory to index.
            max_files: Maximum number of files to include.
            max_symbols_per_file: Maximum symbols to extract per file.
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            List of file summary dicts with "path", "kind", "symbols" keys.
        """
        # bd-63: Check if capability is enabled first
        if not cls.is_active(cls.Capabilities.REPO_INDEX):
            _prefer_native = False

        # bd-9: Try Elixir first if preferred and available (use repo_compass_index for compact format)
        if _prefer_native and cls._should_use_elixir(cls.Capabilities.REPO_INDEX):
            try:
                result = cls._call_elixir(
                    "repo_compass_index",
                    {
                        "root": root,
                        "max_files": max_files,
                        "max_symbols_per_file": max_symbols_per_file,
                    },
                )
                if "error" not in result:
                    cls._last_source[cls.Capabilities.REPO_INDEX] = "elixir"
                    return result.get("files", [])
            except Exception as e:
                logger.debug(f"Elixir repo_compass_index failed, falling back to Python: {e}")

        # Python fallback via repo_compass
        try:
            from pathlib import Path

            from code_puppy.plugins.repo_compass.indexer import (
                build_structure_map as python_build_structure_map,
            )

            py_results = python_build_structure_map(
                Path(root), max_files, max_symbols_per_file
            )
            cls._last_source[cls.Capabilities.REPO_INDEX] = "python"
            return [
                {
                    "path": r.path,
                    "kind": r.kind,
                    "symbols": list(r.symbols),
                }
                for r in py_results
            ]
        except Exception as e:
            logger.warning(f"Python fallback index_directory failed: {e}")
            return []

    # -------------------------------------------------------------------------
    # Parse Contract (bd-11) — Complete routing through NativeBackend
    #
    # Elixir-first routing (default):
    #   1. Elixir NIF (turbo_parse_nif) - calls Rust tree-sitter via NIF
    #   2. Rust turbo_parse - direct Python bindings (fallback)
    #   3. Python fallback - minimal implementation
    #
    # Rust-first routing (optional):
    #   1. Rust turbo_parse - direct Python bindings
    #   2. Elixir NIF - fallback to NIF when Rust unavailable
    #   3. Python fallback
    #
    # Methods:
    #   - parse_file()          → Elixir NIF → Rust → Python error stub
    #   - parse_source()        → Elixir NIF → Rust → Python error stub
    #   - extract_symbols()     → Elixir NIF → Rust → Python (regex fallback for py/ex)
    #   - extract_syntax_diagnostics() → Elixir NIF → Rust → Python empty
    #   - get_folds()           → Elixir NIF → Rust → Python empty
    #   - get_highlights()      → Elixir NIF → Rust → Python empty
    #   - parse_batch()         → Elixir (Task.async_stream) → Rust → Python
    #   - supported_languages() → Elixir NIF → Rust → Python ["python", "elixir"]
    #   - is_language_supported() → Elixir NIF → Rust → Python set lookup
    #   - parse_health_check()  → Rust turbo_parse only (diagnostic)
    #   - parse_stats()         → Rust turbo_parse only (diagnostic)
    # -------------------------------------------------------------------------

    @classmethod
    def parse_file(
        cls,
        path: str,
        language: str | None = None,
        *,
        _prefer_native: bool = True,
    ) -> dict[str, Any]:
        """Parse file for symbols/AST.

        bd-11: Routes through Elixir control plane when available and preferred.

        Routing priority (ELIXIR_FIRST):
            1. Elixir NIF (turbo_parse_nif)
            2. Rust turbo_parse (direct Python bindings)
            3. Python fallback (returns error stub)

        Routing priority (RUST_FIRST):
            1. Rust turbo_parse
            2. Elixir NIF
            3. Python fallback

        Args:
            path: Path to file to parse.
            language: Optional language hint (auto-detected if None).
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            Dict with parse results or error.
        """
        # bd-13-fix: Check if capability is enabled first (not is_active).
        # is_enabled allows Python fallback in PYTHON_ONLY mode; is_active would block it.
        if not cls.is_enabled(cls.Capabilities.PARSE):
            return {"error": "Parse capability disabled", "path": path}

        # bd-11: Try Elixir first if preferred and available
        # bd-13-fix: _should_use_elixir now handles PYTHON_ONLY internally
        # bd-13-partial-fix: Pass specific entrypoint for accurate RUST_FIRST fallback
        if _prefer_native and cls._should_use_elixir(cls.Capabilities.PARSE, entrypoint="parse_file"):
            try:
                result = cls._call_elixir(
                    "parse_file",
                    {
                        "path": path,
                        "language": language,
                    },
                )
                if "error" not in result:
                    cls._last_source[cls.Capabilities.PARSE] = "elixir"
                    return result
            except Exception as e:
                logger.debug(f"Elixir parse_file failed: {e}")

        # Try Rust turbo_parse
        # bd-13-fix: Use _should_use_turbo_parse to respect PYTHON_ONLY mode
        turbo_parse = cls._get_turbo_parse()
        if _prefer_native and cls._should_use_turbo_parse():
            try:
                native_func = turbo_parse["parse_file"]
                result = native_func(path, language)
                cls._last_source[cls.Capabilities.PARSE] = "turbo_parse"
                return result
            except Exception as e:
                logger.debug(f"turbo_parse.parse_file failed: {e}")

        # Python fallback - return error stub
        cls._last_source[cls.Capabilities.PARSE] = "python_fallback"
        return {
            "error": "No parse backend available",
            "path": path,
            "language": language or "unknown",
        }

    @classmethod
    def parse_source(
        cls,
        source: str,
        language: str,
        *,
        _prefer_native: bool = True,
    ) -> dict[str, Any]:
        """Parse source code for symbols/AST.

        bd-11: Routes through Elixir control plane when available and preferred.

        Args:
            source: Source code string to parse.
            language: Language identifier.
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            Dict with parse results or error.
        """
        # bd-13-fix: Check if capability is enabled first (not is_active).
        # is_enabled allows Python fallback in PYTHON_ONLY mode; is_active would block it.
        if not cls.is_enabled(cls.Capabilities.PARSE):
            return {"error": "Parse capability disabled"}

        # bd-11: Try Elixir first if preferred and available
        # bd-13-fix: _should_use_elixir now handles PYTHON_ONLY internally
        # bd-13-partial-fix: Pass specific entrypoint for accurate RUST_FIRST fallback
        if _prefer_native and cls._should_use_elixir(cls.Capabilities.PARSE, entrypoint="parse_source"):
            try:
                result = cls._call_elixir(
                    "parse_source",
                    {
                        "source": source,
                        "language": language,
                    },
                )
                if "error" not in result:
                    cls._last_source[cls.Capabilities.PARSE] = "elixir"
                    return result
            except Exception as e:
                logger.debug(f"Elixir parse_source failed: {e}")

        # Try Rust turbo_parse
        # bd-13-fix: Use _should_use_turbo_parse to respect PYTHON_ONLY mode
        turbo_parse = cls._get_turbo_parse()
        if _prefer_native and cls._should_use_turbo_parse():
            try:
                native_func = turbo_parse["parse_source"]
                result = native_func(source, language)
                cls._last_source[cls.Capabilities.PARSE] = "turbo_parse"
                return result
            except Exception as e:
                logger.debug(f"turbo_parse.parse_source failed: {e}")

        cls._last_source[cls.Capabilities.PARSE] = "python_fallback"
        return {"error": "No parse backend available", "language": language}

    @classmethod
    def extract_symbols(
        cls,
        source: str,
        language: str,
        *,
        _prefer_native: bool = True,
    ) -> list[dict]:
        """Extract symbols from source code.

        bd-11: Routes through Elixir control plane when available and preferred.

        Args:
            source: Source code string to extract symbols from.
            language: Language identifier.
            _prefer_native: Internal flag to force Python fallback.

        Returns:
            List of symbol dicts with name, kind, range info.
        """
        # bd-13-fix: Check if capability is enabled first (not is_active).
        # is_enabled allows Python fallback in PYTHON_ONLY mode; is_active would block it.
        if not cls.is_enabled(cls.Capabilities.PARSE):
            return []

        # bd-11: Try Elixir first if preferred and available
        # bd-13-fix: _should_use_elixir now handles PYTHON_ONLY internally
        # bd-13-partial-fix: Pass specific entrypoint for accurate RUST_FIRST fallback
        if _prefer_native and cls._should_use_elixir(cls.Capabilities.PARSE, entrypoint="extract_symbols"):
            try:
                result = cls._call_elixir(
                    "extract_symbols",
                    {
                        "source": source,
                        "language": language,
                    },
                )
                symbols = result.get("symbols", [])
                if symbols:
                    cls._last_source[cls.Capabilities.PARSE] = "elixir"
                    return symbols
            except Exception as e:
                logger.debug(f"Elixir extract_symbols failed: {e}")

        # Try Rust turbo_parse
        # bd-13-fix: Use _should_use_turbo_parse to respect PYTHON_ONLY mode
        turbo_parse = cls._get_turbo_parse()
        if _prefer_native and cls._should_use_turbo_parse():
            try:
                native_func = turbo_parse["extract_symbols"]
                result = native_func(source, language)
                cls._last_source[cls.Capabilities.PARSE] = "turbo_parse"
                # Handle both dict and list return types
                if isinstance(result, dict):
                    return result.get("symbols", [])
                return result if isinstance(result, list) else []
            except Exception as e:
                logger.debug(f"turbo_parse.extract_symbols failed: {e}")

        cls._last_source[cls.Capabilities.PARSE] = "python_fallback"
        return []

    @classmethod
    def get_folds(cls, source: str, language: str) -> dict:
        """Get code fold ranges.  # bd-93

        Routing: Elixir → Rust turbo_parse → Python stub

        Args:
            source: Source code string.
            language: Language identifier.

        Returns:
            Dict with fold ranges or error info.
        """
        # bd-13-fix: Check if capability is enabled first (not is_active).
        # is_enabled allows Python fallback in PYTHON_ONLY mode; is_active would block it.
        if not cls.is_enabled(cls.Capabilities.PARSE):
            return {"error": "Parse capability disabled", "folds": []}

        # Try Elixir
        # bd-13-partial-fix: Pass specific entrypoint for accurate RUST_FIRST fallback
        if cls._should_use_elixir(cls.Capabilities.PARSE, entrypoint="get_folds"):
            try:
                result = cls._call_elixir(
                    "get_folds",
                    {"source": source, "language": language},
                )
                if "error" not in result:
                    cls._last_source[cls.Capabilities.PARSE] = "elixir"
                    return result
            except Exception as e:
                logger.debug(f"Elixir get_folds failed: {e}")

        # Try Rust turbo_parse
        # bd-13-fix: Use _should_use_turbo_parse to respect PYTHON_ONLY and capability state
        turbo_parse = cls._get_turbo_parse()
        if cls._should_use_turbo_parse() and turbo_parse.get("get_folds"):
            try:
                result = turbo_parse["get_folds"](source, language)
                cls._last_source[cls.Capabilities.PARSE] = "turbo_parse"
                if isinstance(result, dict):
                    return result
                return {"folds": result if isinstance(result, list) else []}
            except Exception as e:
                logger.debug(f"turbo_parse.get_folds failed: {e}")

        cls._last_source[cls.Capabilities.PARSE] = "python_fallback"
        return {"error": "No fold backend available", "folds": []}

    @classmethod
    def get_highlights(cls, source: str, language: str) -> dict:
        """Get syntax highlights.  # bd-93

        Routing: Elixir → Rust turbo_parse → Python stub

        Args:
            source: Source code string.
            language: Language identifier.

        Returns:
            Dict with highlight ranges or error info.
        """
        # bd-13-fix: Check if capability is enabled first (not is_active).
        # is_enabled allows Python fallback in PYTHON_ONLY mode; is_active would block it.
        if not cls.is_enabled(cls.Capabilities.PARSE):
            return {"error": "Parse capability disabled", "highlights": []}

        # Try Elixir
        # bd-13-partial-fix: Pass specific entrypoint for accurate RUST_FIRST fallback
        if cls._should_use_elixir(cls.Capabilities.PARSE, entrypoint="get_highlights"):
            try:
                result = cls._call_elixir(
                    "get_highlights",
                    {"source": source, "language": language},
                )
                if "error" not in result:
                    cls._last_source[cls.Capabilities.PARSE] = "elixir"
                    return result
            except Exception as e:
                logger.debug(f"Elixir get_highlights failed: {e}")

        # Try Rust turbo_parse
        # bd-13-fix: Use _should_use_turbo_parse to respect PYTHON_ONLY and capability state
        turbo_parse = cls._get_turbo_parse()
        if cls._should_use_turbo_parse() and turbo_parse.get("get_highlights"):
            try:
                result = turbo_parse["get_highlights"](source, language)
                cls._last_source[cls.Capabilities.PARSE] = "turbo_parse"
                if isinstance(result, dict):
                    return result
                return {"highlights": result if isinstance(result, list) else []}
            except Exception as e:
                logger.debug(f"turbo_parse.get_highlights failed: {e}")

        cls._last_source[cls.Capabilities.PARSE] = "python_fallback"
        return {"error": "No highlight backend available", "highlights": []}

    @classmethod
    def parse_batch(
        cls,
        paths: list[str],
        language: str | None = None,
    ) -> dict:
        """Parse multiple files in batch.  # bd-11

        Routing: Elixir (Task.async_stream) → Rust → sequential Python

        bd-11: Complete parse contract with Elixir NIF routing.

        Args:
            paths: List of file paths to parse.
            language: Optional language identifier (auto-detected if not provided).

        Returns:
            Dict with results list and count.
        """
        # bd-13-fix: Check if capability is enabled first (not is_active).
        # is_enabled allows Python fallback in PYTHON_ONLY mode; is_active would block it.
        if not cls.is_enabled(cls.Capabilities.PARSE):
            return {"error": "Parse capability disabled", "results": [], "count": 0}

        # Try Elixir (uses Task.async_stream for concurrency)
        # bd-13-partial-fix: Uses parse_file under the hood, so check that entrypoint
        if cls._should_use_elixir(cls.Capabilities.PARSE, entrypoint="parse_file"):
            try:
                result = cls._call_elixir(
                    "parse_batch",
                    {"paths": paths, "language": language},
                )
                if "error" not in result:
                    cls._last_source[cls.Capabilities.PARSE] = "elixir"
                    return result
            except Exception as e:
                logger.debug(f"Elixir parse_batch failed: {e}")

        # Try Rust turbo_parse (sequential)
        # bd-13-fix: Gate with BOTH _should_use_turbo_parse() AND _is_turbo_parse_entrypoint_available
        # to respect PYTHON_ONLY semantics. Partial turbo_parse builds may have available=True
        # (parse_source exists) but parse_file missing, so we must verify the specific entrypoint.
        turbo_parse = cls._get_turbo_parse()
        if cls._should_use_turbo_parse() and cls._is_turbo_parse_entrypoint_available("parse_file"):
            try:
                native_func = turbo_parse["parse_file"]
                results = []
                for path in paths:
                    try:
                        file_result = native_func(path, language)
                        results.append(
                            {"path": path, "result": file_result, "error": None}
                        )
                    except Exception as e:
                        results.append(
                            {"path": path, "result": None, "error": str(e)}
                        )
                cls._last_source[cls.Capabilities.PARSE] = "turbo_parse"
                return {"results": results, "count": len(results)}
            except Exception as e:
                logger.debug(f"turbo_parse parse_batch failed: {e}")

        # Python fallback (sequential with basic parse)
        cls._last_source[cls.Capabilities.PARSE] = "python_fallback"
        results = []
        for path in paths:
            try:
                file_result = cls.parse_file(path, language or "unknown")
                results.append({"path": path, "result": file_result, "error": None})
            except Exception as e:
                results.append({"path": path, "result": None, "error": str(e)})
        return {"results": results, "count": len(results)}

    @classmethod
    def supported_languages(cls) -> list[str]:
        """Get list of supported languages for parsing.

        bd-11: Routes through Elixir when available, then tries Rust.
        bd-13-fix: Respects PYTHON_ONLY mode and capability state.

        Returns:
            List of supported language identifiers.
        """
        # Try Elixir
        # bd-11: Use _should_use_elixir to respect PYTHON_ONLY and capability state
        # bd-13-partial-fix: Pass specific entrypoint for accurate RUST_FIRST fallback
        if cls._should_use_elixir(cls.Capabilities.PARSE, entrypoint="supported_languages"):
            try:
                result = cls._call_elixir("supported_languages", {})
                languages = result.get("languages", [])
                if languages:
                    return languages
            except Exception:
                pass

        # Try Rust
        # bd-13-fix: Use _should_use_turbo_parse to respect PYTHON_ONLY and capability state
        turbo_parse = cls._get_turbo_parse()
        if cls._should_use_turbo_parse() and turbo_parse.get("supported_languages"):
            try:
                result = turbo_parse["supported_languages"]()
                # Handle both list return and dict with "languages" key
                if isinstance(result, list):
                    return result
                if isinstance(result, dict):
                    return result.get("languages", [])
            except Exception:
                pass

        # Fallback
        return ["python", "elixir"]  # Regex fallback only supports these

    @classmethod
    def is_language_supported(cls, language: str) -> bool:
        """Check if a language is supported for parsing.

        bd-13-fix: Respects PYTHON_ONLY mode and capability state.

        Args:
            language: Language identifier to check.

        Returns:
            True if the language is supported.
        """
        # bd-13-fix: Use _should_use_elixir first, then turbo_parse
        # bd-13-partial-fix: Pass specific entrypoint for accurate RUST_FIRST fallback
        if cls._should_use_elixir(cls.Capabilities.PARSE, entrypoint="is_language_supported"):
            try:
                result = cls._call_elixir("is_language_supported", {"language": language})
                if result.get("supported") is not None:
                    return result["supported"]
            except Exception:
                pass

        # Try Rust turbo_parse
        turbo_parse = cls._get_turbo_parse()
        if cls._should_use_turbo_parse() and turbo_parse.get("is_language_supported"):
            try:
                return turbo_parse["is_language_supported"](language)
            except Exception:
                pass

        # Basic fallback for common languages (must match supported_languages())
        supported = {
            "python",
            "elixir",  # bd-11: Added to match supported_languages() fallback
            "javascript",
            "typescript",
            "rust",
            "go",
            "c",
            "cpp",
            "java",
            "ruby",
        }
        return language.lower() in supported

    @classmethod
    def extract_syntax_diagnostics(cls, source: str, language: str) -> dict[str, Any]:
        """Extract syntax diagnostics from source code.

        bd-11: Complete parse contract - Elixir-first routing for diagnostics.

        Routing: Elixir NIF → Rust turbo_parse → Python fallback

        Args:
            source: Source code to analyze
            language: Programming language identifier

        Returns:
            Dict with diagnostics list, error_count, warning_count, success
        """
        # bd-13-fix: Check if capability is enabled first (not is_active).
        # is_enabled allows Python fallback in PYTHON_ONLY mode; is_active would block it.
        if not cls.is_enabled(cls.Capabilities.PARSE):
            return {
                "diagnostics": [],
                "error_count": 0,
                "warning_count": 0,
                "success": False,
                "error": "Parse capability disabled",
            }

        # Try Elixir first
        # bd-13-partial-fix: Pass specific entrypoint for accurate RUST_FIRST fallback
        if cls._should_use_elixir(cls.Capabilities.PARSE, entrypoint="extract_syntax_diagnostics"):
            try:
                result = cls._call_elixir(
                    "extract_syntax_diagnostics",
                    {"source": source, "language": language},
                )
                if "error" not in result:
                    cls._last_source[cls.Capabilities.PARSE] = "elixir"
                    return result
            except Exception as e:
                logger.debug(f"Elixir diagnostics failed: {e}")

        # Try Rust turbo_parse
        # bd-13-fix: Use _should_use_turbo_parse to respect PYTHON_ONLY and capability state
        turbo_parse = cls._get_turbo_parse()
        if cls._should_use_turbo_parse() and turbo_parse.get("extract_syntax_diagnostics"):
            try:
                result = turbo_parse["extract_syntax_diagnostics"](source, language)
                cls._last_source[cls.Capabilities.PARSE] = "rust"
                return result
            except Exception as e:
                logger.debug(f"Rust diagnostics failed: {e}")

        # Python fallback
        cls._last_source[cls.Capabilities.PARSE] = "python"
        return {
            "diagnostics": [],
            "error_count": 0,
            "warning_count": 0,
            "success": False,
            "error": "No parse backend available",
        }

    @classmethod
    def parse_health_check(cls) -> dict[str, Any]:
        """Get health check info for parse capability.

        bd-93: Phase 4 - NativeBackend method for turbo_parse health.
        bd-13-fix: Now turbo_parse-specific; respects PYTHON_ONLY and capability state.

        Returns:
            Dict with available, version, languages, cache_available
        """
        # bd-13-fix: Check if we should even try turbo_parse (PYTHON_ONLY or disabled)
        is_enabled = cls.is_enabled(cls.Capabilities.PARSE)
        is_python_only = cls._backend_preference == BackendPreference.PYTHON_ONLY

        # Try Rust turbo_parse if allowed
        turbo_parse = cls._get_turbo_parse()
        if not is_python_only and is_enabled:
            if turbo_parse.get("available") and turbo_parse.get("health_check"):
                try:
                    result = turbo_parse["health_check"]()
                    # Ensure consistent response format
                    return {
                        "available": result.get("available", True),
                        "version": result.get("version"),
                        "languages": result.get("languages", []),
                        "cache_available": result.get("cache_available", False),
                        "backend": "turbo_parse",
                    }
                except Exception as e:
                    logger.debug(f"turbo_parse health_check failed: {e}")

        # Return appropriate unavailable response
        if is_python_only:
            return {
                "available": False,
                "version": None,
                "languages": [],
                "cache_available": False,
                "backend": "disabled",
                "reason": "python_only_mode",
            }
        if not is_enabled:
            return {
                "available": False,
                "version": None,
                "languages": [],
                "cache_available": False,
                "backend": "disabled",
                "reason": "capability_disabled",
            }
        return {
            "available": False,
            "version": None,
            "languages": [],
            "cache_available": False,
            "backend": "unavailable",
        }

    @classmethod
    def parse_stats(cls) -> dict[str, Any]:
        """Get parsing statistics.

        bd-93: Phase 4 - NativeBackend method for turbo_parse stats.
        bd-13-fix: Now turbo_parse-specific; respects PYTHON_ONLY and capability state.

        Returns:
            Dict with total_parses, cache_hits, cache_misses, etc.
        """
        # bd-13-fix: Check if we should even try turbo_parse (PYTHON_ONLY or disabled)
        is_enabled = cls.is_enabled(cls.Capabilities.PARSE)
        is_python_only = cls._backend_preference == BackendPreference.PYTHON_ONLY

        # Try Rust turbo_parse if allowed
        turbo_parse = cls._get_turbo_parse()
        if not is_python_only and is_enabled:
            if turbo_parse.get("available") and turbo_parse.get("stats"):
                try:
                    result = turbo_parse["stats"]()
                    # Merge with backend info
                    result["backend"] = "turbo_parse"
                    return result
                except Exception as e:
                    logger.debug(f"turbo_parse stats failed: {e}")

        # Return empty stats with reason for unavailability
        result = {
            "total_parses": 0,
            "average_parse_time_ms": 0.0,
            "languages_used": {},
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_evictions": 0,
            "cache_hit_ratio": 0.0,
            "backend": "disabled" if (not is_enabled or is_python_only) else "unavailable",
        }
        if is_python_only:
            result["reason"] = "python_only_mode"
        elif not is_enabled:
            result["reason"] = "capability_disabled"
        return result

    @classmethod
    def verify_routing(cls) -> dict[str, Any]:
        """Log and return the active routing table for all capabilities.

        bd-13: Runtime routing verification — call during startup to log
        which backend will handle each capability.

        Returns:
            Dict mapping capability name to routing info.
        """
        routing_table = {}
        for cap in [
            cls.Capabilities.MESSAGE_CORE,
            cls.Capabilities.FILE_OPS,
            cls.Capabilities.REPO_INDEX,
            cls.Capabilities.PARSE,
        ]:
            routing = cls.get_capability_routing(cap)
            routing_table[cap] = routing
            logger.info(
                "Routing %s: will_use=%s preference=%s",
                cap,
                routing.get("will_use", "unknown"),
                routing.get("preference", "unknown"),
            )
        return routing_table


# Convenience module-level functions for direct import
def get_backend_status() -> dict[str, CapabilityInfo]:
    """Get status of all native backend capabilities."""
    return NativeBackend.get_status()


def is_capability_available(capability: str) -> bool:
    """Check if a specific capability is available."""
    return NativeBackend.is_available(capability)


def list_files(directory: str = ".", recursive: bool = True) -> dict[str, Any]:
    """List files (convenience function)."""
    return NativeBackend.list_files(directory, recursive)


def grep(pattern: str, directory: str = ".") -> dict[str, Any]:
    """Search files (convenience function)."""
    return NativeBackend.grep(pattern, directory)


def read_file(
    path: str, start_line: int | None = None, num_lines: int | None = None
) -> dict[str, Any]:
    """Read file (convenience function)."""
    return NativeBackend.read_file(path, start_line, num_lines)


def read_files(
    paths: list[str], start_line: int | None = None, num_lines: int | None = None
) -> dict[str, Any]:
    """Batch read files (convenience function)."""
    return NativeBackend.read_files(paths, start_line, num_lines)


def serialize_messages(messages: list) -> list[dict]:
    """Serialize messages (convenience function)."""
    return NativeBackend.serialize_messages(messages)


def parse_file(path: str, language: str | None = None) -> dict[str, Any]:
    """Parse file (convenience function)."""
    return NativeBackend.parse_file(path, language)


def parse_source(source: str, language: str) -> dict[str, Any]:
    """Parse source code (convenience function)."""
    return NativeBackend.parse_source(source, language)


def extract_symbols(source: str, language: str) -> list[dict]:
    """Extract symbols from source code (convenience function)."""
    return NativeBackend.extract_symbols(source, language)


def supported_languages() -> list[str]:
    """Get list of supported languages for parsing (convenience function)."""
    return NativeBackend.supported_languages()


def index_directory(
    root: str, max_files: int = 40, max_symbols_per_file: int = 8
) -> list[dict[str, Any]]:
    """Index directory (convenience function)."""
    return NativeBackend.index_directory(root, max_files, max_symbols_per_file)


def get_folds(source: str, language: str) -> dict:
    """Get code fold ranges (convenience function).  # bd-93"""
    return NativeBackend.get_folds(source, language)


def get_highlights(source: str, language: str) -> dict:
    """Get syntax highlights (convenience function).  # bd-93"""
    return NativeBackend.get_highlights(source, language)


def parse_batch(paths: list[str], language: str | None = None) -> dict:
    """Parse multiple files in batch (convenience function).  # bd-93"""
    return NativeBackend.parse_batch(paths, language)


def is_language_supported(language: str) -> bool:
    """Check if language is supported for parsing (convenience function).  # bd-93"""
    return NativeBackend.is_language_supported(language)


def extract_syntax_diagnostics(source: str, language: str) -> dict[str, Any]:
    """Extract syntax diagnostics (convenience function).  # bd-93"""
    return NativeBackend.extract_syntax_diagnostics(source, language)


def parse_health_check() -> dict[str, Any]:
    """Get parse health check info (convenience function).  # bd-93"""
    return NativeBackend.parse_health_check()


def parse_stats() -> dict[str, Any]:
    """Get parse statistics (convenience function).  # bd-93"""
    return NativeBackend.parse_stats()


def create_message_batch(messages: list) -> Any:
    """Create a MessageBatchHandle for batch Rust operations.

    Convenience wrapper around NativeBackend.create_message_batch().
    """
    return NativeBackend.create_message_batch(messages)


__all__ = [
    # Main class
    "NativeBackend",
    "CapabilityInfo",
    "BackendPreference",
    # Status functions
    "get_backend_status",
    "is_capability_available",
    # File operations
    "list_files",
    "grep",
    "read_file",
    "read_files",
    # Message operations
    "serialize_messages",
    # Parse operations
    "parse_file",
    "parse_source",
    "extract_symbols",
    "supported_languages",
    # Fold/Highlight operations  # bd-93
    "get_folds",
    "get_highlights",
    # Batch operations  # bd-96
    "parse_batch",
    # Index operations
    "index_directory",
    # Message batch operations
    "create_message_batch",
    "MessageBatchHandle",
]
