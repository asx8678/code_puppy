"""Launcher for the Textual TUI mode.

Provides textual_interactive_mode() which is the Textual equivalent of
interactive_mode() from interactive_loop.py. Called by AppRunner when
TUI mode is enabled.
"""

from code_puppy.config_package import env_bool


def is_tui_enabled() -> bool:
    """Check if Textual TUI mode is enabled.

    The Textual TUI is opt-in while still under development.
    Set CODE_PUPPY_TUI=1 to enable it. Otherwise the classic
    prompt_toolkit UI is used.
    """
    return env_bool("CODE_PUPPY_TUI", default=False)


async def textual_interactive_mode(
    message_renderer=None, initial_command: str = None
) -> None:
    """Run Code Puppy in Textual TUI mode.

    This replaces interactive_mode() when TUI mode is enabled.

    Args:
        message_renderer: Legacy renderer (not used in TUI mode, kept for API compat)
        initial_command: Optional initial command to execute on startup
    """
    from code_puppy.tui.app import CodePuppyApp

    app = CodePuppyApp()

    # If there's an initial command, queue it for execution after mount
    if initial_command:
        app._initial_command = initial_command

    # Run the Textual app
    await app.run_async()
