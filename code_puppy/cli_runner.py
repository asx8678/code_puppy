"""CLI runner for Code Puppy.

This module is the public entry-point shim. It applies pydantic-ai patches
*before* any pydantic-ai imports occur, loads plugin callbacks, then
provides lazy access to the public API so that simple CLI operations
(like --help) are fast without loading heavy dependencies.

Actual application logic lives in:
  - code_puppy.app_runner   – AppRunner class and main()
  - code_puppy.interactive_loop – interactive_mode() REPL
  - code_puppy.prompt_runner    – run_prompt_with_attachments(), execute_single_prompt()

Import-time optimization:
- Heavy imports are deferred until first use via __getattr__
- --help is fast because it only parses args without loading models
- Tests that import from cli_runner don't trigger heavy deps unless used
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from typing import TYPE_CHECKING

# Apply pydantic-ai patches BEFORE any pydantic-ai imports (these are lightweight)
from code_puppy.pydantic_patches import apply_all_patches

apply_all_patches()

from code_puppy import plugins
from code_puppy.config import get_use_dbos
from code_puppy.errors import FatalError
from code_puppy.terminal_utils import reset_unix_terminal

plugins.load_plugin_callbacks()

if TYPE_CHECKING:
    # Type hints for static analysis — not loaded at runtime
    pass

# -----------------------------------------------------------------------------
# Lazy import registry: attribute -> import spec
# These are heavy modules that should only load when actually accessed.
# -----------------------------------------------------------------------------
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "AppRunner": ("code_puppy.app_runner", "AppRunner"),
    "main": ("code_puppy.app_runner", "main"),
    "shutdown_flag": ("code_puppy.app_runner", "shutdown_flag"),
    "interactive_mode": ("code_puppy.interactive_loop", "interactive_mode"),
    "execute_single_prompt": ("code_puppy.prompt_runner", "execute_single_prompt"),
    "run_prompt_with_attachments": (
        "code_puppy.prompt_runner",
        "run_prompt_with_attachments",
    ),
}


def __getattr__(name: str) -> object:
    """Lazy import heavy symbols on first access.

    This allows `from code_puppy.cli_runner import main` to work while
    deferring the heavy pydantic_ai, openai, anthropic imports until
    the symbol is actually accessed.

    Args:
        name: The attribute name being accessed on this module.

    Returns:
        The requested symbol or raises AttributeError if not found.

    Raises:
        AttributeError: If the requested attribute is not in _LAZY_IMPORTS.
    """
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        mod = __import__(module_path, fromlist=[attr_name])
        value = getattr(mod, attr_name)
        # Cache on this module for subsequent accesses
        globals()[name] = value
        return value
    raise AttributeError(f"module 'code_puppy.cli_runner' has no attribute '{name}'")


def __dir__() -> list[str]:
    """Ensure dir(cli_runner) shows lazy-loaded symbols."""
    return sorted(set(globals().keys()) | set(_LAZY_IMPORTS.keys()))


# -----------------------------------------------------------------------------
# Synchronous entry point (installed as the ``code-puppy`` CLI command)
# -----------------------------------------------------------------------------


def main_entry() -> None:
    """Entry point for the installed CLI tool."""
    try:
        # Lazy import main to avoid heavy deps for --help
        from code_puppy.app_runner import main

        asyncio.run(main())
    except FatalError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        # Note: Using sys.stderr for crash output - messaging system may not be available
        sys.stderr.write(traceback.format_exc())
        if get_use_dbos():
            from dbos import DBOS

            DBOS.destroy()
        return 0
    finally:
        # Reset terminal on Unix-like systems (not Windows)
        reset_unix_terminal()
