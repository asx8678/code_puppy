"""Tests for the TUI completion system."""

import os
from code_puppy.tui.completion import (
    CompletionItem,
    get_completions,
    _complete_slash_command,
    _complete_file_path,
    _complete_directories,
    _complete_command_names,
    _complete_model_names,
    _complete_agent_names,
    _complete_config_keys,
)


def test_completion_item_defaults():
    """Test CompletionItem auto-fills display from text."""
    item = CompletionItem(text="/help")
    assert item.display == "/help"
    assert item.description == ""


def test_completion_item_custom_display():
    """Test CompletionItem with explicit display."""
    item = CompletionItem(text="/m", display="/m → /model", description="Switch model")
    assert item.display == "/m → /model"
    assert item.description == "Switch model"


def test_completion_item_text_preserved():
    """Test CompletionItem stores text correctly."""
    item = CompletionItem(text="some-text")
    assert item.text == "some-text"


def test_slash_completion_triggers():
    """Test that / prefix triggers command completion."""
    results = get_completions("/")
    # Should return command completions (may be empty if registry not loaded)
    assert isinstance(results, list)


def test_slash_completion_with_partial():
    """Test that /h prefix returns command completions."""
    results = get_completions("/h")
    assert isinstance(results, list)
    # All results should start with /h (case-insensitive)
    for item in results:
        assert item.text.lower().startswith("/h")


def test_no_completion_for_plain_text():
    """Test that plain text returns no completions."""
    results = get_completions("hello world")
    assert results == []


def test_no_completion_for_empty():
    """Test that empty string returns no completions."""
    results = get_completions("")
    assert results == []


def test_at_completion_triggers():
    """Test that @ triggers file path completion."""
    results = get_completions("look at @.")
    assert isinstance(results, list)
    # Should find at least current directory files
    if results:
        assert all(isinstance(r, CompletionItem) for r in results)


def test_file_path_completion_finds_files():
    """Test file path completion finds real files."""
    results = _complete_file_path("@pyproject")
    # Should find pyproject.toml
    found = [r for r in results if "pyproject" in r.text]
    assert len(found) > 0


def test_file_path_completion_no_at():
    """Test file path completion returns empty if no @ found."""
    results = _complete_file_path("no at sign here")
    assert results == []


def test_file_path_completion_icons():
    """Test that file path completions have appropriate icons."""
    results = _complete_file_path("@code_puppy")
    dirs = [r for r in results if "code_puppy" in r.text and os.path.isdir(r.text)]
    for d in dirs:
        assert "📁" in d.display


def test_file_path_completion_limit():
    """Test that file path completion returns at most 50 results."""
    results = _complete_file_path("@")
    assert len(results) <= 50


def test_directory_completion():
    """Test directory completion for /cd."""
    results = _complete_directories("")
    # Should find directories in current dir
    assert isinstance(results, list)
    dirs = [r for r in results if "code_puppy" in r.text]
    assert len(dirs) > 0


def test_directory_completion_icons():
    """Test that directory completions have folder icons."""
    results = _complete_directories("")
    for item in results:
        assert "📁" in item.display


def test_directory_completion_trailing_sep():
    """Test that directory completions end with os.sep."""
    results = _complete_directories("")
    for item in results:
        assert item.text.endswith(os.sep)


def test_complete_command_names_returns_list():
    """Test _complete_command_names returns a list."""
    results = _complete_command_names("/")
    assert isinstance(results, list)


def test_complete_command_names_all_start_with_slash():
    """Test all returned command names start with /."""
    results = _complete_command_names("/")
    for item in results:
        assert item.text.startswith("/")


def test_complete_model_names_returns_list():
    """Test _complete_model_names returns a list."""
    results = _complete_model_names("")
    assert isinstance(results, list)


def test_complete_model_names_partial():
    """Test _complete_model_names filters by partial string."""
    # All results should match the partial (case-insensitive)
    partial = "cl"
    results = _complete_model_names(partial)
    for item in results:
        assert item.text.lower().startswith(partial.lower())


def test_complete_agent_names_returns_list():
    """Test _complete_agent_names returns a list."""
    results = _complete_agent_names("")
    assert isinstance(results, list)


def test_complete_config_keys_returns_list():
    """Test _complete_config_keys returns a list."""
    results = _complete_config_keys("")
    assert isinstance(results, list)


def test_complete_config_keys_excludes_token():
    """Test that puppy_token is excluded from config completions."""
    results = _complete_config_keys("")
    for item in results:
        assert item.text != "puppy_token"


def test_complete_slash_command_model_subcommand():
    """Test /model subcommand triggers model completions."""
    results = _complete_slash_command("/model ")
    assert isinstance(results, list)
    # These should be model names, not command names
    for item in results:
        assert not item.text.startswith("/")


def test_complete_slash_command_agent_subcommand():
    """Test /agent subcommand triggers agent completions."""
    results = _complete_slash_command("/agent ")
    assert isinstance(results, list)


def test_complete_slash_command_set_subcommand():
    """Test /set subcommand triggers config key completions."""
    results = _complete_slash_command("/set ")
    assert isinstance(results, list)
    for item in results:
        assert item.text != "puppy_token"


def test_complete_slash_command_cd_subcommand():
    """Test /cd subcommand triggers directory completions."""
    results = _complete_slash_command("/cd ")
    assert isinstance(results, list)


def test_get_completions_cursor_pos():
    """Test that cursor_pos parameter limits completion context."""
    # With cursor at position 2 (after "/h"), complete /h commands
    text = "/help extra stuff"
    results = get_completions(text, cursor_pos=2)
    assert isinstance(results, list)
    for item in results:
        assert item.text.lower().startswith("/h")


def test_get_completions_at_with_cursor():
    """Test @ completion respects cursor position."""
    text = "@src/ some other text"
    results = get_completions(text, cursor_pos=5)
    assert isinstance(results, list)


def test_completion_overlay_import():
    """Test that CompletionOverlay can be imported."""
    from code_puppy.tui.widgets.completion_overlay import CompletionOverlay

    assert CompletionOverlay is not None


def test_completion_overlay_creation():
    """Test CompletionOverlay instantiation."""
    from code_puppy.tui.widgets.completion_overlay import CompletionOverlay

    overlay = CompletionOverlay(id="test-overlay")
    assert overlay is not None
    assert overlay._items == []


def test_completion_overlay_messages_exist():
    """Test that CompletionOverlay has the expected message classes."""
    from code_puppy.tui.widgets.completion_overlay import CompletionOverlay

    assert hasattr(CompletionOverlay, "CompletionSelected")
    assert hasattr(CompletionOverlay, "CompletionDismissed")


def test_completion_overlay_in_widgets_init():
    """Test that CompletionOverlay is exported from widgets package."""
    from code_puppy.tui.widgets import CompletionOverlay

    assert CompletionOverlay is not None


def test_completion_overlay_in_tui_init():
    """Test that CompletionOverlay is exported from tui package."""
    from code_puppy.tui import CompletionOverlay

    assert CompletionOverlay is not None


def test_completion_selected_message():
    """Test CompletionSelected message stores item."""
    from code_puppy.tui.widgets.completion_overlay import CompletionOverlay

    item = CompletionItem(text="/help", description="Show help")
    msg = CompletionOverlay.CompletionSelected(item)
    assert msg.item is item
    assert msg.item.text == "/help"


def test_completion_item_description():
    """Test CompletionItem description field."""
    item = CompletionItem(text="claude", description="model")
    assert item.description == "model"
    assert item.display == "claude"  # auto-filled from text
