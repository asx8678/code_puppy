"""Info bar widget — replaces both StatusBar and Footer.

Shows current agent, model, status, and key shortcuts in a single
bottom-docked bar with live updates.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class InfoBar(Widget):
    """Single-line bottom bar showing current agent, model, and status."""

    DEFAULT_CSS = """
    InfoBar {
        dock: bottom;
        height: 1;
        background: $primary-background;
        color: $text;
        layout: horizontal;
    }

    InfoBar > .info-bar--agent {
        width: auto;
        padding: 0 1;
        color: $success;
        text-style: bold;
    }

    InfoBar > .info-bar--sep {
        width: 3;
        color: $text-muted;
        content-align: center middle;
    }

    InfoBar > .info-bar--model {
        width: auto;
        padding: 0 1;
        color: $accent;
    }

    InfoBar > .info-bar--status {
        width: 1fr;
        padding: 0 1;
        color: $text-muted;
    }

    InfoBar > .info-bar--keys {
        width: auto;
        padding: 0 1;
        color: $text-muted;
    }
    """

    # Reactive properties that trigger refresh
    agent_name: reactive[str] = reactive("", layout=True)
    model_name: reactive[str] = reactive("", layout=True)
    status_text: reactive[str] = reactive("Ready", layout=True)
    is_working: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        yield Static("", classes="info-bar--agent", id="ib-agent")
        yield Static(" │ ", classes="info-bar--sep")
        yield Static("", classes="info-bar--model", id="ib-model")
        yield Static(" │ ", classes="info-bar--sep")
        yield Static("", classes="info-bar--status", id="ib-status")
        yield Static("F1 Help  F4 Settings", classes="info-bar--keys", id="ib-keys")

    def _refresh_agent(self) -> None:
        """Update the agent label."""
        try:
            label = self.query_one("#ib-agent", Static)
            label.update(f"🐶 {self.agent_name}" if self.agent_name else "🐶 —")
        except Exception:
            pass

    def _refresh_model(self) -> None:
        """Update the model label."""
        try:
            label = self.query_one("#ib-model", Static)
            label.update(f"🤖 {self.model_name}" if self.model_name else "🤖 —")
        except Exception:
            pass

    def _refresh_status(self) -> None:
        """Update the status label."""
        try:
            label = self.query_one("#ib-status", Static)
            label.update(self.status_text)
        except Exception:
            pass

    def watch_agent_name(self, value: str) -> None:
        self._refresh_agent()

    def watch_model_name(self, value: str) -> None:
        self._refresh_model()

    def watch_status_text(self, value: str) -> None:
        self._refresh_status()

    def watch_is_working(self, value: bool) -> None:
        """Update keys hint based on working state."""
        try:
            keys = self.query_one("#ib-keys", Static)
            if value:
                keys.update("Ctrl+X Cancel")
            else:
                keys.update("F1 Help  F4 Settings")
        except Exception:
            pass

    def update_from_app_state(self) -> None:
        """Pull current agent/model from app state. Call on mount and after changes."""
        try:
            from code_puppy.agents import get_current_agent

            agent = get_current_agent()
            self.agent_name = agent.display_name
        except Exception:
            self.agent_name = ""

        try:
            from code_puppy.command_line.model_picker_completion import get_active_model

            self.model_name = get_active_model() or ""
        except Exception:
            self.model_name = ""
