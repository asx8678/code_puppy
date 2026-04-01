"""Main Textual application for Code Puppy.

This is the unified full-screen TUI that replaces the prompt_toolkit-based
interactive loop. It provides a chat-style interface with scrollable output,
an input line at the bottom, and a status bar showing token rate.
"""

from collections import deque

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, RichLog, Static

from code_puppy.tui.theme import APP_CSS

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
        """Handle up/down arrow for history navigation."""
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


class CodePuppyApp(App):
    """The main Code Puppy TUI application.

    Layout:
        Header — app name, model, agent
        RichLog — scrollable chat output
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
        yield StatusBar(id="status-bar")
        yield PuppyInput(id="input")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize the app after mounting."""
        chat = self.query_one("#chat-log", RichLog)
        chat.write("[bold cyan]🐶 Welcome to Code Puppy![/]")
        chat.write("")
        chat.write("[dim]Type a message or /command to get started.[/dim]")
        chat.write("[dim]Press F1 for help, Escape to quit.[/dim]")
        chat.write("")
        # Focus the input
        self.query_one("#input", PuppyInput).focus()

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

        # Placeholder for future integration:
        # - /commands will be dispatched to handle_command()
        # - Regular text will be sent to the agent via run_prompt_with_attachments()
        # - Streaming responses will be written to chat-log via stream_renderer
        # For now, echo back to demonstrate the shell works
        if text.startswith("/"):
            chat.write(f"[yellow]Command: {text} (not yet wired)[/yellow]")
        else:
            chat.write(f"[dim]Message received: {text} (agent not yet wired)[/dim]")

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
        """Show agent picker screen (placeholder)."""
        chat = self.query_one("#chat-log", RichLog)
        chat.write("[yellow]Agent picker not yet migrated.[/yellow]")

    def action_show_settings(self) -> None:
        """Show settings screen (placeholder)."""
        chat = self.query_one("#chat-log", RichLog)
        chat.write("[yellow]Settings not yet migrated.[/yellow]")

    def action_cancel_task(self) -> None:
        """Cancel the currently running task."""
        if self.is_working:
            self.is_working = False
            self.status_message = ""
            chat = self.query_one("#chat-log", RichLog)
            chat.write("[red]Task cancelled.[/red]")

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
