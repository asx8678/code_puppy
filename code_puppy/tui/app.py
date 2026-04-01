"""Main Textual application for Code Puppy.

This is the unified full-screen TUI that replaces the prompt_toolkit-based
interactive loop. It provides a chat-style interface with scrollable output,
an input line at the bottom, and a status bar showing token rate.
"""

import asyncio
from collections import deque

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, RichLog, Static

from code_puppy.tui.theme import APP_CSS
from code_puppy.tui.widgets.completion_overlay import CompletionOverlay

# Maximum number of history entries to keep
MAX_HISTORY = 500


class StatusBar(Static):
    """Status bar showing token rate and current activity."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $surface-darken-1;
        color: $text-muted;
        padding: 0 2;
    }
    """


class PuppyInput(Input):
    """Custom Input widget with command history support.

    Adds up/down arrow history navigation on top of Textual's Input.
    """

    DEFAULT_CSS = """
    PuppyInput {
        dock: bottom;
        height: 3;
        margin: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(placeholder=">>> Type a message or /command...", **kwargs)
        self._history: deque[str] = deque(maxlen=MAX_HISTORY)
        self._history_index: int = -1
        self._saved_input: str = ""

    def add_to_history(self, text: str) -> None:
        """Add a command to history."""
        if text.strip() and (not self._history or self._history[-1] != text):
            self._history.append(text)
        self._history_index = -1
        self._saved_input = ""

    def on_key(self, event) -> None:
        """Handle up/down arrow for history navigation and tab for completion."""
        if event.key == "up":
            if not self._history:
                return
            if self._history_index == -1:
                self._saved_input = self.value
                self._history_index = len(self._history) - 1
            elif self._history_index > 0:
                self._history_index -= 1
            self.value = self._history[self._history_index]
            self.cursor_position = len(self.value)
            event.prevent_default()
        elif event.key == "down":
            if self._history_index == -1:
                return
            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                self.value = self._history[self._history_index]
            else:
                self._history_index = -1
                self.value = self._saved_input
            self.cursor_position = len(self.value)
            event.prevent_default()
        elif event.key == "tab":
            event.prevent_default()
            # Post a message to the app to show completions
            from code_puppy.tui.completion import get_completions

            completions = get_completions(self.value, self.cursor_position)
            if completions:
                try:
                    overlay = self.app.query_one("#completions", CompletionOverlay)
                    overlay.show_completions(completions)
                except Exception:
                    pass


class CodePuppyApp(App):
    """The main Code Puppy TUI application.

    Layout:
        Header — app name, model, agent
        RichLog — scrollable chat output
        CompletionOverlay — tab-completion dropdown
        StatusBar — token rate, activity messages
        PuppyInput — command/message input
        Footer — F-key bindings
    """

    TITLE = "Code Puppy 🐶"

    CSS = (
        APP_CSS
        + """
    /* App-specific styles */
    #chat-log {
        height: 1fr;
        border-bottom: solid $primary-lighten-3;
        scrollbar-gutter: stable;
        padding: 0 1;
    }
    """
    )

    BINDINGS = [
        Binding("f1", "show_help", "Help", show=True),
        Binding("f2", "show_model_picker", "Model", show=True),
        Binding("f3", "show_agent_picker", "Agent", show=True),
        Binding("f4", "show_settings", "Settings", show=True),
        Binding("ctrl+h", "show_help", "Help", show=False),  # Mac-friendly alt
        Binding("ctrl+x", "cancel_task", "Cancel", show=False),
    ]

    # Reactive properties
    is_working: reactive[bool] = reactive(False)
    token_rate: reactive[float] = reactive(0.0)
    status_message: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        """Create the app layout."""
        yield Header()
        yield RichLog(id="chat-log", highlight=True, markup=True, wrap=True)
        yield CompletionOverlay(id="completions")
        yield StatusBar(id="status-bar")
        yield PuppyInput(id="input")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize the app after mounting."""
        # Start the message bridge so emit_info/emit_warning/etc. appear in the TUI
        from code_puppy.tui.message_bridge import TUIMessageBridge

        self._message_bridge = TUIMessageBridge(self)
        self._message_bridge.start()

        chat = self.query_one("#chat-log", RichLog)
        chat.write("[bold cyan]🐶 Welcome to Code Puppy![/]")
        chat.write("")
        chat.write("[dim]Type a message or /command to get started.[/dim]")
        chat.write("[dim]Press F1 for help, Escape to quit.[/dim]")
        chat.write("")
        self.query_one("#input", PuppyInput).focus()

        # Execute initial command if provided
        initial = getattr(self, "_initial_command", None)
        if initial:
            self._initial_command = None
            # Schedule it to run after the app is fully mounted
            self.call_later(self._run_initial_command, initial)

    def on_unmount(self) -> None:
        """Clean up resources when the app exits."""
        if hasattr(self, "_message_bridge"):
            self._message_bridge.stop()

    async def _run_initial_command(self, command: str) -> None:
        """Execute the initial command passed at startup."""
        chat = self.query_one("#chat-log", RichLog)
        chat.write(f"\n[bold]Initial:[/bold] {command}")
        if command.startswith("/"):
            await self._handle_slash_command(command)
        else:
            await self._handle_agent_prompt(command)

    # --- Reactive watchers ---

    def watch_is_working(self, working: bool) -> None:
        """Update UI state when working status changes."""
        input_widget = self.query_one("#input", PuppyInput)
        if working:
            input_widget.placeholder = ">>> (working... Ctrl+X to cancel)"
            input_widget.disabled = True
        else:
            input_widget.placeholder = ">>> Type a message or /command..."
            input_widget.disabled = False
            input_widget.focus()

    def watch_token_rate(self, rate: float) -> None:
        """Update status bar with current token rate."""
        self._update_status_bar()

    def watch_status_message(self, message: str) -> None:
        """Update status bar text."""
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        """Refresh the status bar content."""
        bar = self.query_one("#status-bar", StatusBar)
        parts = []

        if self.is_working:
            if self.token_rate > 0:
                parts.append(f"⏳ {self.token_rate:.1f} t/s")
            if self.status_message:
                parts.append(f"🐾 {self.status_message}")
            elif self.token_rate == 0:
                parts.append("⏳ Working...")
        else:
            parts.append("Ready")
            if self.token_rate > 0:
                parts.append(f"Last: {self.token_rate:.1f} t/s")

        try:
            from code_puppy.config import get_global_model_name

            model = get_global_model_name()
            parts.append(f"[{model}]")
        except Exception:
            pass

        bar.update(" │ ".join(parts))

    # --- Completion overlay handlers ---

    def on_completion_overlay_completion_selected(
        self, event: CompletionOverlay.CompletionSelected
    ) -> None:
        """Apply selected completion to input."""
        input_widget = self.query_one("#input", PuppyInput)
        text = input_widget.value

        # For @ file completions, replace from the @ to cursor
        if "@" in text:
            at_pos = text.rfind("@")
            input_widget.value = text[: at_pos + 1] + event.item.text
        # For / commands, replace the whole input
        elif text.lstrip().startswith("/"):
            parts = text.split(None, 1)
            if len(parts) > 1 and event.item.text.startswith("/"):
                # Subcommand completion (e.g., /model name)
                input_widget.value = parts[0] + " " + event.item.text
            else:
                input_widget.value = event.item.text
        else:
            input_widget.value = event.item.text

        input_widget.cursor_position = len(input_widget.value)
        input_widget.focus()

    def on_completion_overlay_completion_dismissed(self, event) -> None:
        """Refocus input when completions dismissed."""
        self.query_one("#input", PuppyInput).focus()

    # --- Input handling ---

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        if event.input.id != "input":
            return

        text = event.value.strip()
        if not text:
            return

        input_widget = self.query_one("#input", PuppyInput)
        input_widget.add_to_history(text)
        input_widget.value = ""

        chat = self.query_one("#chat-log", RichLog)
        chat.write(f"\n[bold]You:[/bold] {text}")

        # Handle exit commands
        if text.lower() in ("/exit", "/quit", "exit", "quit"):
            self.exit()
            return

        # Handle /clear
        if text.lower() in ("/clear", "clear"):
            chat.clear()
            chat.write("[dim]Conversation cleared.[/dim]")
            return

        # Shell pass-through: !command
        if text.startswith("!") and len(text) > 1:
            await self._handle_shell_passthrough(text)
            return

        # Slash commands
        if text.startswith("/"):
            await self._handle_slash_command(text)
            return

        # Regular text → send to agent
        await self._handle_agent_prompt(text)

    async def _handle_slash_command(self, command: str) -> None:
        """Dispatch a slash command to the command handler."""
        chat = self.query_one("#chat-log", RichLog)
        cmd_lower = command.strip().lower()
        cmd_parts = cmd_lower.split()
        cmd_name = cmd_parts[0] if cmd_parts else ""

        # --- Native Textual screens (handled directly, no handle_command) ---

        if cmd_name == "/help":
            # Render help directly in chat (don't rely on message bridge)
            try:
                from code_puppy.command_line.command_handler import get_commands_help

                help_text = get_commands_help()
                chat.write(help_text)
            except Exception as e:
                chat.write(f"[red]Error loading help: {e}[/red]")
            return

        if cmd_name == "/settings":
            from code_puppy.tui.screens.model_settings_screen import ModelSettingsScreen

            self.push_screen(ModelSettingsScreen())
            return

        if cmd_name == "/agent" and len(cmd_parts) == 1:
            # Just "/agent" with no args → show picker
            from code_puppy.tui.screens.agent_screen import AgentScreen

            self.push_screen(AgentScreen())
            return

        # Handle /colors natively via Textual screen
        if command.strip().lower() in ("/colors",):
            from code_puppy.tui.screens.colors_screen import ColorsScreen

            self.push_screen(ColorsScreen())
            return

        # Handle /autosave_load via Textual screen
        if command.strip().lower() in ("/autosave_load",):
            from code_puppy.tui.screens.autosave_screen import AutosaveScreen

            self.push_screen(AutosaveScreen())
            return

        # Handle /tutorial via Textual screen
        if command.strip().lower() in ("/tutorial",):
            from code_puppy.tui.screens.onboarding_screen import OnboardingScreen

            self.push_screen(OnboardingScreen())
            return

        # Handle /skills via Textual screen
        if command.strip().lower() in ("/skills",):
            from code_puppy.tui.screens.skills_screen import SkillsScreen

            self.push_screen(SkillsScreen())
            return

        # Handle /hooks via Textual screen
        if command.strip().lower() in ("/hooks",):
            from code_puppy.tui.screens.hooks_screen import HooksScreen

            self.push_screen(HooksScreen())
            return

        # Handle /scheduler via Textual screen
        if command.strip().lower() in ("/scheduler",):
            from code_puppy.tui.screens.scheduler_screen import SchedulerScreen

            self.push_screen(SchedulerScreen())
            return

        # Handle /uc via Textual screen
        if command.strip().lower() in ("/uc",):
            from code_puppy.tui.screens.uc_screen import UCScreen

            self.push_screen(UCScreen())
            return

        # Handle /add_model via Textual screen
        if command.strip().lower() in ("/add_model",):
            from code_puppy.tui.screens.add_model_screen import AddModelScreen

            self.push_screen(AddModelScreen())
            return

        # Handle /mcp install via Textual screen
        _cmd_parts = command.strip().split()
        if (
            len(_cmd_parts) >= 2
            and _cmd_parts[0].lower() == "/mcp"
            and _cmd_parts[1].lower() == "install"
        ):
            from code_puppy.tui.screens.mcp_screen import MCPScreen

            def _on_mcp_selected(server_id: str | None) -> None:
                if server_id:
                    self._install_mcp_server(server_id)

            self.push_screen(MCPScreen(), callback=_on_mcp_selected)
            return

        # Handle /mcp add via Textual form screen
        if (
            len(_cmd_parts) >= 2
            and _cmd_parts[0].lower() == "/mcp"
            and _cmd_parts[1].lower() == "add"
        ):
            from code_puppy.tui.screens.mcp_form_screen import MCPFormScreen

            def _on_mcp_form_done(server_name: str | None) -> None:
                if server_name:
                    _chat = self.query_one("#chat-log", RichLog)
                    _chat.write(
                        f"[bold green]✅ Custom MCP server '[cyan]{server_name}[/cyan]' added![/bold green]"
                    )
                    _chat.write(
                        f"[dim]Use '/mcp start {server_name}' to start it.[/dim]"
                    )

            self.push_screen(MCPFormScreen(), callback=_on_mcp_form_done)
            return

        try:
            from code_puppy.command_line.command_handler import handle_command

            result = handle_command(command)

            if result is True:
                # Command handled — output was emitted via messaging system
                # The TUIMessageBridge will display it asynchronously
                # Add a small delay to let the bridge process messages
                await asyncio.sleep(0.1)
            elif isinstance(result, str):
                # Command returned text to process as agent prompt
                await self._handle_agent_prompt(result)
            elif result is False:
                chat.write(f"[yellow]Unknown command: {command}[/yellow]")
                chat.write("[dim]Type /help for available commands.[/dim]")
        except Exception as e:
            chat.write(f"[red]Command error: {e}[/red]")

    async def _handle_agent_prompt(self, text: str) -> None:
        """Send text to the agent and stream the response."""
        chat = self.query_one("#chat-log", RichLog)
        self.set_working(True, "Sending to agent...")

        try:
            from code_puppy.agents import get_current_agent
            from code_puppy.agents.event_stream_handler import set_streaming_console
            from code_puppy.config import auto_save_session_if_enabled, save_command_to_history
            from code_puppy.prompt_runner import run_prompt_with_attachments
            from code_puppy.tui.message_bridge import TUIConsole

            save_command_to_history(text)

            agent = get_current_agent()

            # Redirect event_stream_handler output to the TUI chat log
            tui_console = TUIConsole(self)
            set_streaming_console(tui_console)

            result, agent_task = await run_prompt_with_attachments(
                agent, text, spinner_console=tui_console, use_spinner=False
            )

            if result is None:
                chat.write("[yellow]Task cancelled.[/yellow]")
                return

            # Display the final response as formatted markdown
            agent_response = result.output
            if agent_response:
                from rich.markdown import Markdown

                chat.write(Markdown(str(agent_response)))

            # Update message history for autosave
            if hasattr(result, "all_messages"):
                agent.set_message_history(list(result.all_messages()))

            auto_save_session_if_enabled()

        except asyncio.CancelledError:
            chat.write("[yellow]Task cancelled by user.[/yellow]")
        except Exception as e:
            chat.write(f"[red]Error: {e}[/red]")
            try:
                from code_puppy.error_logging import log_error

                log_error(e, context="TUI agent response error")
            except Exception:
                pass
        finally:
            self.set_working(False)

    async def _handle_shell_passthrough(self, text: str) -> None:
        """Handle !command shell passthrough."""
        chat = self.query_one("#chat-log", RichLog)
        try:
            from code_puppy.command_line.shell_passthrough import execute_shell_passthrough

            execute_shell_passthrough(text)
        except Exception as e:
            chat.write(f"[red]Shell error: {e}[/red]")

    # --- Action handlers for F-keys ---

    def action_show_help(self) -> None:
        """Show help information."""
        chat = self.query_one("#chat-log", RichLog)
        chat.write("\n[bold cyan]━━━ Help ━━━[/bold cyan]")
        chat.write("[dim]F1[/dim] This help")
        chat.write("[dim]F2[/dim] Switch model")
        chat.write("[dim]F3[/dim] Switch agent")
        chat.write("[dim]F4[/dim] Model settings")
        chat.write("[dim]Ctrl+X[/dim] Cancel running task")
        chat.write("[dim]/exit[/dim] Quit")
        chat.write("")

    def action_show_model_picker(self) -> None:
        """Show model picker screen (placeholder)."""
        chat = self.query_one("#chat-log", RichLog)
        chat.write("[yellow]Model picker not yet migrated.[/yellow]")

    def action_show_agent_picker(self) -> None:
        """Show agent picker screen."""
        from code_puppy.tui.screens.agent_screen import AgentScreen

        self.push_screen(AgentScreen())

    def action_show_settings(self) -> None:
        """Show model settings screen."""
        from code_puppy.tui.screens.model_settings_screen import ModelSettingsScreen

        self.push_screen(ModelSettingsScreen())

    def action_cancel_task(self) -> None:
        """Cancel the currently running task."""
        if self.is_working:
            # Cancel any running agent task
            if hasattr(self, "_current_agent_task") and self._current_agent_task:
                self._current_agent_task.cancel()
            self.is_working = False
            self.status_message = ""
            chat = self.query_one("#chat-log", RichLog)
            chat.write("[red]Task cancelled.[/red]")

    # --- MCP install helpers ---

    def _install_mcp_server(self, server_id: str) -> None:
        """Install a catalog MCP server with env-var defaults (no interactive prompt)."""
        import os

        chat = self.query_one("#chat-log", RichLog)
        try:
            from code_puppy.mcp_.server_registry_catalog import catalog

            server = catalog.by_id.get(server_id)
        except Exception:
            server = None

        if server is None:
            chat.write(f"[red]Unknown MCP server: {server_id}[/red]")
            return

        # Build a minimal config using already-set env vars; skip interactive prompts
        env_vars = {}
        for var in server.get_environment_vars():
            val = os.environ.get(var, "")
            if val:
                env_vars[var] = val

        install_config = {
            "name": server.name,
            "env_vars": env_vars,
            "cmd_args": {},
        }

        chat.write(
            f"[bold]⏳ Installing [cyan]{server.display_name}[/cyan]...[/bold]"
        )

        def _do_install() -> None:
            try:
                from code_puppy.command_line.mcp.catalog_server_installer import (
                    install_catalog_server,
                )
                from code_puppy.mcp_.manager import get_manager

                manager = get_manager()
                success = install_catalog_server(manager, server, install_config)
                self.app.call_from_thread(
                    self._on_mcp_install_done, server.display_name, success
                )
            except Exception as exc:
                self.app.call_from_thread(
                    self._on_mcp_install_done, server.display_name, False, str(exc)
                )

        self.run_worker(_do_install, thread=True)

    def _on_mcp_install_done(
        self, display_name: str, success: bool, error: str | None = None
    ) -> None:
        """Report MCP install result to the chat log."""
        chat = self.query_one("#chat-log", RichLog)
        if success:
            chat.write(
                f"[bold green]✅ '{display_name}' installed successfully![/bold green]"
            )
        else:
            msg = error or "Installation failed."
            chat.write(f"[bold red]❌ Install failed: {msg}[/bold red]")

    # --- Public API for other modules to write to the chat ---

    def write_to_chat(self, content: str, **kwargs) -> None:
        """Write content to the chat log.

        This is the primary API for other modules (stream renderer,
        command handler, etc.) to output to the chat.
        """
        chat = self.query_one("#chat-log", RichLog)
        chat.write(content, **kwargs)

    def set_working(self, working: bool, message: str = "") -> None:
        """Set the working state and optional status message."""
        self.is_working = working
        self.status_message = message

    def update_token_rate(self, rate: float) -> None:
        """Update the displayed token rate."""
        self.token_rate = rate


def run_app() -> None:
    """Entry point to launch the Code Puppy TUI.

    Can be called from main.py or used for standalone testing.
    """
    app = CodePuppyApp()
    app.run()


if __name__ == "__main__":
    run_app()
