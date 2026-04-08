"""CLI runner for Code Puppy.

This module is the public entry-point shim. It applies pydantic-ai patches
*before* any pydantic-ai imports occur, loads plugin callbacks, then
re-exports the public API so that callers and tests can still import from
``code_puppy.cli_runner`` as before.

Actual application logic lives in:
  - code_puppy.app_runner   – AppRunner class and main()
  - code_puppy.interactive_loop – interactive_mode() REPL
  - code_puppy.prompt_runner    – run_prompt_with_attachments(), execute_single_prompt()
"""

# Apply pydantic-ai patches BEFORE any pydantic-ai imports
from code_puppy.pydantic_patches import apply_all_patches

apply_all_patches()

import asyncio  # noqa: E402
import sys  # noqa: E402
import traceback  # noqa: E402

from code_puppy import plugins  # noqa: E402
from code_puppy.config import get_use_dbos  # noqa: E402
from code_puppy.terminal_utils import reset_unix_terminal  # noqa: E402

plugins.load_plugin_callbacks()

# ---------------------------------------------------------------------------
# Re-export public API so existing importers keep working
# ---------------------------------------------------------------------------

# app_runner provides AppRunner, main(), and shutdown_flag
from code_puppy.app_runner import AppRunner, main, shutdown_flag  # noqa: F401, E402

# interactive_loop provides the REPL entry-point
from code_puppy.interactive_loop import interactive_mode  # noqa: F401, E402

# prompt_runner provides the two prompt-execution helpers
from code_puppy.prompt_runner import (  # noqa: F401, E402
    execute_single_prompt,
    run_prompt_with_attachments,
)


# ---------------------------------------------------------------------------
# Synchronous entry point (installed as the ``code-puppy`` CLI command)
# ---------------------------------------------------------------------------


def main_entry() -> None:
    """Entry point for the installed CLI tool."""
    try:
        asyncio.run(main())
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
