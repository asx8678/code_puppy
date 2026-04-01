"""Tests for the main CodePuppyApp shell."""

import pytest
from code_puppy.tui.app import CodePuppyApp, PuppyInput
from code_puppy.tui.widgets.info_bar import InfoBar


def test_app_can_be_instantiated():
    """Verify the app can be created."""
    app = CodePuppyApp()
    assert app.TITLE == "Code Puppy 🐶"


def test_puppy_input_history():
    """Test command history in PuppyInput."""
    inp = PuppyInput(id="test")
    inp.add_to_history("first command")
    inp.add_to_history("second command")
    assert len(inp._history) == 2
    assert inp._history[0] == "first command"
    assert inp._history[1] == "second command"


def test_puppy_input_no_duplicate_history():
    """Test that consecutive duplicates are not added to history."""
    inp = PuppyInput(id="test")
    inp.add_to_history("same command")
    inp.add_to_history("same command")
    assert len(inp._history) == 1


def test_puppy_input_empty_not_in_history():
    """Test that empty/whitespace strings are not added to history."""
    inp = PuppyInput(id="test")
    inp.add_to_history("")
    inp.add_to_history("   ")
    assert len(inp._history) == 0


def test_info_bar_creation():
    """Verify InfoBar can be instantiated."""
    bar = InfoBar()
    assert bar is not None


def test_app_bindings():
    """Verify the app has expected F-key bindings."""
    app = CodePuppyApp()
    binding_keys = [b.key for b in app.BINDINGS]
    assert "f1" in binding_keys
    assert "f2" in binding_keys
    assert "f3" in binding_keys
    assert "f4" in binding_keys
    assert "ctrl+x" in binding_keys


def test_app_has_css():
    """Verify the app has CSS defined."""
    assert CodePuppyApp.CSS is not None
    assert len(CodePuppyApp.CSS) > 0
    assert "#chat-log" in CodePuppyApp.CSS


def test_screens_package_importable():
    """Verify the screens package is importable."""
    from code_puppy.tui import screens  # noqa: F401

    assert screens is not None


def test_puppy_input_history_index_resets_after_add():
    """Test that history index resets when a new command is added."""
    inp = PuppyInput(id="test")
    inp.add_to_history("alpha")
    inp.add_to_history("beta")
    # Simulate navigating history
    inp._history_index = 0
    # Adding a new item should reset the index
    inp.add_to_history("gamma")
    assert inp._history_index == -1


def test_puppy_input_history_max_size():
    """Test that history respects MAX_HISTORY limit."""
    from code_puppy.tui.app import MAX_HISTORY

    inp = PuppyInput(id="test")
    for i in range(MAX_HISTORY + 10):
        inp.add_to_history(f"command {i}")
    assert len(inp._history) == MAX_HISTORY


def test_app_run_app_function_exists():
    """Verify run_app() function is importable and callable."""
    from code_puppy.tui.app import run_app

    assert callable(run_app)
