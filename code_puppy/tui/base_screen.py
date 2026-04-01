"""Base screen class for all Code Puppy TUI menu screens."""

from textual.binding import Binding
from textual.screen import Screen


class MenuScreen(Screen):
    """Base class for all Code Puppy menu overlay screens.

    Provides standard navigation bindings and styling that all menus share.
    Subclasses implement compose() to define their layout.
    """

    BINDINGS = [
        Binding("escape", "pop_screen", "Back", show=True),
        Binding("q", "quit_screen", "Quit", show=False),
    ]

    def action_pop_screen(self) -> None:
        """Go back to the previous screen."""
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()

    def action_quit_screen(self) -> None:
        """Quit the menu (same as escape for overlay screens)."""
        self.action_pop_screen()
