"""AppRunner class for Code Puppy.

Separates concerns of the main application lifecycle into distinct methods:
argument parsing, renderer setup, logo display, signal handling,
configuration/validation, and the top-level run dispatch.

Import-time optimization notes:
- DBOS and heavy TUI imports are deferred to runtime (inside methods)
- This allows --help to be fast (~0.1s) while full runtime pays the import cost
- Rich console is only imported in setup_renderers() where it's used
"""

import argparse
import os
import sys
import time
from typing import TYPE_CHECKING

from code_puppy import __version__, callbacks
from code_puppy.config import (
    DBOS_DATABASE_URL,
    ensure_config_exists,
    get_use_dbos,
    initialize_command_history_file,
)
from code_puppy.config_package import env_bool
from code_puppy.console import build_console
from code_puppy.keymap import KeymapError, validate_cancel_agent_key
from code_puppy.terminal_utils import reset_windows_terminal_full
from code_puppy.version_checker import default_version_mismatch_behavior
from code_puppy.dbos_utils import is_dbos_initialized

if TYPE_CHECKING:
    # Type-only imports for static analysis — not loaded at runtime
    from rich.console import Console
    from dbos import DBOSConfig

# Module-level flag accessible to external code
shutdown_flag = False

# Lazy-loaded function references — populated on first use of run()
_interactive_mode: callable | None = None
_execute_single_prompt: callable | None = None


def _get_interactive_mode() -> callable:
    """Lazy import interactive_mode to defer heavy TUI dependencies."""
    global _interactive_mode
    if _interactive_mode is None:
        from code_puppy.interactive_loop import interactive_mode

        _interactive_mode = interactive_mode
    return _interactive_mode


def _get_execute_single_prompt() -> callable:
    """Lazy import execute_single_prompt to defer heavy dependencies."""
    global _execute_single_prompt
    if _execute_single_prompt is None:
        from code_puppy.prompt_runner import execute_single_prompt

        _execute_single_prompt = execute_single_prompt
    return _execute_single_prompt


def _log_gil_status() -> None:
    """Log whether the Python GIL is enabled or disabled (free-threaded mode)."""
    from code_puppy.messaging import emit_info

    try:
        gil_enabled = sys._is_gil_enabled()  # Python 3.13+
    except AttributeError:
        return  # Python < 3.13, GIL is always enabled

    if not gil_enabled:
        emit_info("🧵 Free-threaded Python active (GIL disabled)")
    else:
        emit_info("🔒 GIL enabled (set PYTHON_GIL=0 or use python3.14t for free-threading)")


class AppRunner:
    """Orchestrates all top-level concerns of the Code Puppy application.

    Each public method handles one distinct concern so that ``run()`` is a
    readable high-level description of startup order.
    """

    # ------------------------------------------------------------------
    # Argument parsing
    # ------------------------------------------------------------------

    def parse_args(self) -> argparse.Namespace:
        """Parse command-line arguments and return the namespace."""
        parser = argparse.ArgumentParser(
            description="Code Puppy - A code generation agent"
        )
        parser.add_argument(
            "--version",
            "-v",
            action="version",
            version=f"{__version__}",
            help="Show version and exit",
        )
        parser.add_argument(
            "--interactive", "-i", action="store_true", help="Run in interactive mode"
        )
        parser.add_argument(
            "--prompt",
            "-p",
            type=str,
            help="Execute a single prompt and exit (no interactive mode)",
        )
        parser.add_argument(
            "--agent",
            "-a",
            type=str,
            help="Specify which agent to use (e.g., --agent code-puppy)",
        )
        parser.add_argument(
            "--model",
            "-m",
            type=str,
            help="Specify which model to use (e.g., --model gpt-5)",
        )
        parser.add_argument(
            "--bridge-mode",
            action="store_true",
            help="Enable Mana LiveView TCP bridge (CODE_PUPPY_BRIDGE=1)",
        )
        parser.add_argument(
            "command",
            nargs="*",
            help="Run a single command (deprecated, use -p instead)",
        )
        return parser.parse_args()

    # ------------------------------------------------------------------
    # Renderer selection
    # ------------------------------------------------------------------

    def setup_renderers(self) -> tuple:
        """Create and start message renderers; returns (message_renderer, bus_renderer, display_console)."""
        from code_puppy.messaging import (
            RichConsoleRenderer,
            SynchronousInteractiveRenderer,
            get_global_queue,
            get_message_bus,
        )

        # Rich Console configuration — defend against silent downgrade to plain text.
        # Respect CODE_PUPPY_NO_COLOR (off) and CODE_PUPPY_FORCE_COLOR (on) escape hatches.
        display_console = build_console(soft_wrap=False)

        # Legacy renderer for backward compatibility (emits via get_global_queue)
        message_queue = get_global_queue()
        message_renderer = SynchronousInteractiveRenderer(
            message_queue, display_console
        )
        message_renderer.start()

        # New MessageBus renderer for structured messages (tools emit here)
        message_bus = get_message_bus()
        bus_renderer = RichConsoleRenderer(message_bus, display_console)
        bus_renderer.start()

        return message_renderer, bus_renderer, display_console

    # ------------------------------------------------------------------
    # Logo / banner display
    # ------------------------------------------------------------------

    def show_logo(self, args: argparse.Namespace, display_console: Console) -> None:
        """Display the Code Puppy ASCII logo when entering interactive mode."""
        if args.prompt:
            return  # Skip logo in prompt-only mode

        try:
            import pyfiglet

            intro_lines = pyfiglet.figlet_format(
                "CODE PUPPY", font="ansi_shadow"
            ).split("\n")

            gradient_colors = ["bright_blue", "bright_cyan", "bright_green"]
            display_console.print("\n")

            lines = []
            for line_num, line in enumerate(intro_lines):
                if line.strip():
                    color_idx = min(line_num // 2, len(gradient_colors) - 1)
                    color = gradient_colors[color_idx]
                    lines.append(f"[{color}]{line}[/{color}]")
                else:
                    lines.append("")
            display_console.print("\n".join(lines))
        except ImportError:
            from code_puppy.messaging import emit_system_message

            emit_system_message("🐶 Code Puppy is Loading...")

    # ------------------------------------------------------------------
    # Signal handling setup
    # ------------------------------------------------------------------

    def setup_signals(self) -> None:
        """Configure OS signal handlers (Windows + uvx protective handler)."""
        try:
            from code_puppy.uvx_detection import should_use_alternate_cancel_key

            if should_use_alternate_cancel_key():
                from code_puppy.terminal_utils import (
                    disable_windows_ctrl_c,
                    set_keep_ctrl_c_disabled,
                )

                disable_windows_ctrl_c()
                set_keep_ctrl_c_disabled(True)

                print(
                    "🔧 Detected uvx launch on Windows - using Ctrl+K for cancellation "
                    "(Ctrl+C is disabled to prevent terminal issues)"
                )

                import signal

                def _uvx_protective_sigint_handler(_sig, _frame):
                    """Protective SIGINT handler for Windows+uvx."""
                    reset_windows_terminal_full()
                    disable_windows_ctrl_c()

                signal.signal(signal.SIGINT, _uvx_protective_sigint_handler)
        except ImportError:
            pass  # uvx_detection module not available, ignore

    # ------------------------------------------------------------------
    # Plugin loading (config / environment)
    # ------------------------------------------------------------------

    def load_api_keys(self) -> None:
        """Load API keys from puppy.cfg into environment variables."""
        from code_puppy.config import load_api_keys_to_environment

        load_api_keys_to_environment()

    # ------------------------------------------------------------------
    # Agent / model instantiation
    # ------------------------------------------------------------------

    def configure_agent(self, args: argparse.Namespace) -> None:
        """Validate and apply --model / --agent flags from the command line."""
        from code_puppy.messaging import emit_error, emit_system_message

        if args.model:
            from code_puppy.config import _validate_model_exists, set_model_name

            model_name = args.model.strip()
            # Early-set model so config is initialised correctly
            set_model_name(model_name)
            try:
                if not _validate_model_exists(model_name):
                    from code_puppy.model_factory import ModelFactory

                    models_config = ModelFactory.load_config()
                    available_models = (
                        list(models_config.keys()) if models_config else []
                    )
                    emit_error(f"Model '{model_name}' not found")
                    emit_system_message(
                        f"Available models: {', '.join(available_models)}"
                    )
                    sys.exit(1)
                emit_system_message(f"🎯 Using model: {model_name}")
            except SystemExit:
                raise
            except Exception as e:
                emit_error(f"Error validating model: {str(e)}")
                from code_puppy.error_logging import log_error

                log_error(e, context="Model validation error")
                sys.exit(1)

        if args.agent:
            from code_puppy.agents.agent_manager import (
                get_available_agents,
                set_current_agent,
            )

            agent_name = args.agent.lower()
            try:
                available_agents = get_available_agents()
                if agent_name not in available_agents:
                    emit_error(f"Agent '{agent_name}' not found")
                    emit_system_message(
                        f"Available agents: {', '.join(available_agents.keys())}"
                    )
                    sys.exit(1)
                set_current_agent(agent_name)
                emit_system_message(f"🤖 Using agent: {agent_name}")
            except SystemExit:
                raise
            except Exception as e:
                emit_error(f"Error setting agent: {str(e)}")
                from code_puppy.error_logging import log_error

                log_error(e, context="Agent setup error")
                sys.exit(1)

    # ------------------------------------------------------------------
    # REPL loop dispatch (run)
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Full application lifecycle: parse → setup → validate → dispatch."""
        global shutdown_flag

        args = self.parse_args()

        # --bridge-mode sets CODE_PUPPY_BRIDGE=1
        if getattr(args, "bridge_mode", False):
            os.environ.setdefault("CODE_PUPPY_BRIDGE", "1")

        # Check TUI mode early to skip legacy renderers — Textual handles all output
        from code_puppy.tui.launcher import is_tui_enabled

        tui_mode = is_tui_enabled() and not args.prompt

        if tui_mode:
            # In TUI mode, don't start legacy renderer threads — they fight Textual for the terminal
            message_renderer = None
            bus_renderer = None
            display_console = None
        else:
            message_renderer, bus_renderer, display_console = self.setup_renderers()
            self.show_logo(args, display_console)

        initialize_command_history_file()
        from code_puppy.messaging import emit_error, emit_system_message

        ensure_config_exists()

        try:
            validate_cancel_agent_key()
        except KeymapError as e:
            emit_error(str(e))
            sys.exit(1)

        if not tui_mode:
            self.setup_signals()
        self.load_api_keys()
        self.configure_agent(args)

        current_version = __version__
        no_version_update = env_bool("NO_VERSION_UPDATE", default=False)
        if no_version_update:
            emit_system_message(f"Current version: {current_version}")
            emit_system_message(
                "Update phase disabled because NO_VERSION_UPDATE is set to 1 or true"
            )
        else:
            if len(callbacks.get_callbacks("version_check")):
                await callbacks.on_version_check(current_version)
            else:
                default_version_mismatch_behavior(current_version)

        await callbacks.on_startup()

        # Log free-threading (no-GIL) status
        _log_gil_status()

        # Register workflow state callback handlers for tracking flags
        from code_puppy.workflow_state import register_callback_handlers

        register_callback_handlers()

        # Initialize DBOS if not disabled (lazy import — DBOS is heavy and only needed here)
        if get_use_dbos():
            from dbos import DBOS

            dbos_app_version = os.environ.get(
                "DBOS_APP_VERSION", f"{current_version}-{int(time.time() * 1000)}"
            )
            dbos_config: DBOSConfig = {
                "name": "dbos-code-puppy",
                "system_database_url": DBOS_DATABASE_URL,
                "run_admin_server": False,
                "conductor_key": os.environ.get("DBOS_CONDUCTOR_KEY"),
                "log_level": os.environ.get("DBOS_LOG_LEVEL", "ERROR"),
                "application_version": dbos_app_version,
            }
            try:
                DBOS(config=dbos_config)
                DBOS.launch()
            except Exception as e:
                emit_error(f"Error initializing DBOS: {e}")
                from code_puppy.error_logging import log_error

                log_error(e, context="DBOS initialization error")
                sys.exit(1)

            # Verify DBOS actually initialized despite no exception
            if not is_dbos_initialized():
                emit_error(
                    "DBOS initialization verification failed. Workflow durability may be unavailable."
                )

        shutdown_flag = False
        try:
            initial_command = None
            prompt_only_mode = False

            if args.prompt:
                initial_command = args.prompt
                prompt_only_mode = True
            elif args.command:
                initial_command = " ".join(args.command)
                prompt_only_mode = False

            if prompt_only_mode:
                await _get_execute_single_prompt()(initial_command, message_renderer)
            elif tui_mode:
                from code_puppy.tui.launcher import textual_interactive_mode

                await textual_interactive_mode(
                    message_renderer, initial_command=initial_command
                )
            else:
                # Default to interactive mode (no args = same as -i)
                await _get_interactive_mode()(
                    message_renderer, initial_command=initial_command
                )
        finally:
            if message_renderer:
                message_renderer.stop()
            if bus_renderer:
                bus_renderer.stop()
            await callbacks.on_shutdown()
            if get_use_dbos():
                from dbos import DBOS

                DBOS.destroy()


async def main() -> None:
    """Main async entry point for Code Puppy CLI."""
    runner = AppRunner()
    await runner.run()
