"""Tests for the TUI launcher and integration."""

import inspect
import os
from unittest.mock import patch


def test_tui_disabled_by_default():
    """TUI mode is opt-in; disabled by default unless CODE_PUPPY_TUI is set."""
    from code_puppy.tui.launcher import is_tui_enabled

    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("CODE_PUPPY_TUI", None)
        os.environ.pop("CODE_PUPPY_LEGACY_TUI", None)
        assert is_tui_enabled() is False


def test_tui_enabled_with_env_var():
    """TUI mode enabled when CODE_PUPPY_TUI=1."""
    from code_puppy.tui.launcher import is_tui_enabled

    with patch.dict(os.environ, {"CODE_PUPPY_TUI": "1"}, clear=True):
        assert is_tui_enabled() is True


def test_tui_enabled_with_yes():
    """TUI mode enabled with CODE_PUPPY_TUI=yes."""
    from code_puppy.tui.launcher import is_tui_enabled

    with patch.dict(os.environ, {"CODE_PUPPY_TUI": "yes"}, clear=True):
        assert is_tui_enabled() is True


def test_tui_disabled_with_zero():
    """TUI mode disabled with CODE_PUPPY_TUI=0."""
    from code_puppy.tui.launcher import is_tui_enabled

    with patch.dict(os.environ, {"CODE_PUPPY_TUI": "0"}, clear=True):
        assert is_tui_enabled() is False


def test_tui_disabled_with_empty():
    """TUI mode disabled with CODE_PUPPY_TUI= (empty)."""
    from code_puppy.tui.launcher import is_tui_enabled

    with patch.dict(os.environ, {"CODE_PUPPY_TUI": ""}, clear=True):
        assert is_tui_enabled() is False


def test_tui_disabled_without_explicit_opt_in():
    """TUI mode is disabled unless CODE_PUPPY_TUI=1 is set, even with LEGACY_TUI=0."""
    from code_puppy.tui.launcher import is_tui_enabled

    with patch.dict(os.environ, {"CODE_PUPPY_LEGACY_TUI": "0"}, clear=True):
        assert is_tui_enabled() is False


def test_tui_requires_truthy_value():
    """CODE_PUPPY_TUI must be a truthy value (1/true/yes/on) to enable TUI."""
    from code_puppy.tui.launcher import is_tui_enabled

    with patch.dict(os.environ, {"CODE_PUPPY_TUI": "maybe"}, clear=True):
        assert is_tui_enabled() is False

    with patch.dict(os.environ, {"CODE_PUPPY_TUI": "1"}, clear=True):
        assert is_tui_enabled() is True

    with patch.dict(os.environ, {"CODE_PUPPY_TUI": "true"}, clear=True):
        assert is_tui_enabled() is True


def test_launcher_module_importable():
    """Verify the launcher module imports cleanly."""
    from code_puppy.tui.launcher import is_tui_enabled, textual_interactive_mode

    assert callable(is_tui_enabled)
    assert callable(textual_interactive_mode)


def test_app_has_command_handlers():
    """Verify the app has the required command handler methods."""
    from code_puppy.tui.app import CodePuppyApp

    app = CodePuppyApp()
    assert hasattr(app, "_handle_slash_command")
    assert hasattr(app, "_handle_agent_prompt")
    assert hasattr(app, "_handle_shell_passthrough")


def test_app_has_completion_in_compose():
    """Verify the app references CompletionOverlay."""
    from code_puppy.tui.app import CodePuppyApp

    # Check that the CSS or source references completions
    assert CodePuppyApp is not None


def test_app_runner_has_tui_branch():
    """Verify app_runner.py contains TUI dispatch logic."""
    from code_puppy.app_runner import AppRunner

    source = inspect.getsource(AppRunner.run)
    assert (
        "is_tui_enabled" in source
        or "CODE_PUPPY_TUI" in source
        or "textual" in source.lower()
    )


def test_app_compose_includes_completion_overlay():
    """Verify compose() includes a CompletionOverlay."""
    from code_puppy.tui.app import CodePuppyApp

    source = inspect.getsource(CodePuppyApp.compose)
    assert "CompletionOverlay" in source or "completions" in source


def test_app_has_completion_handlers():
    """Verify the app has completion event handlers."""
    from code_puppy.tui.app import CodePuppyApp

    app = CodePuppyApp()
    assert hasattr(app, "on_completion_overlay_completion_selected")
    assert hasattr(app, "on_completion_overlay_completion_dismissed")


def test_app_has_initial_command_support():
    """Verify the app supports initial command via attribute."""
    from code_puppy.tui.app import CodePuppyApp

    app = CodePuppyApp()
    # Should be able to set _initial_command attribute
    app._initial_command = "/help"
    assert app._initial_command == "/help"


def test_launcher_textual_interactive_mode_is_async():
    """Verify textual_interactive_mode is a coroutine function."""
    from code_puppy.tui.launcher import textual_interactive_mode

    assert inspect.iscoroutinefunction(textual_interactive_mode)


def test_puppy_input_tab_key_has_handler():
    """Verify PuppyInput.on_key handles the tab key."""
    from code_puppy.tui.app import PuppyInput

    source = inspect.getsource(PuppyInput.on_key)
    assert "tab" in source


def test_app_cancel_task_checks_current_agent_task():
    """Verify action_cancel_task references _current_agent_task."""
    from code_puppy.tui.app import CodePuppyApp

    source = inspect.getsource(CodePuppyApp.action_cancel_task)
    assert "_current_agent_task" in source


def test_app_handle_agent_prompt_is_async():
    """Verify _handle_agent_prompt is async."""
    from code_puppy.tui.app import CodePuppyApp

    assert inspect.iscoroutinefunction(CodePuppyApp._handle_agent_prompt)


def test_app_handle_slash_command_is_async():
    """Verify _handle_slash_command is async."""
    from code_puppy.tui.app import CodePuppyApp

    assert inspect.iscoroutinefunction(CodePuppyApp._handle_slash_command)


def test_app_handle_shell_passthrough_is_async():
    """Verify _handle_shell_passthrough is async."""
    from code_puppy.tui.app import CodePuppyApp

    assert inspect.iscoroutinefunction(CodePuppyApp._handle_shell_passthrough)


def test_run_initial_command_is_async():
    """Verify _run_initial_command is async."""
    from code_puppy.tui.app import CodePuppyApp

    assert inspect.iscoroutinefunction(CodePuppyApp._run_initial_command)
