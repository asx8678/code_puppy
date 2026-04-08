"""Tests for the ColorsScreen Textual screen.

Covers: imports, class hierarchy, bindings, instantiation,
helper widgets, and data-wiring with ColorConfiguration.
"""

import pytest


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


def test_import_colors_screen():
    """ColorsScreen module can be imported."""
    from code_puppy.tui.screens.colors_screen import ColorsScreen

    assert ColorsScreen is not None


def test_import_color_picker_screen():
    """ColorPickerScreen can be imported."""
    from code_puppy.tui.screens.colors_screen import ColorPickerScreen

    assert ColorPickerScreen is not None


def test_import_banner_list_item():
    """BannerListItem widget can be imported."""
    from code_puppy.tui.screens.colors_screen import BannerListItem

    assert BannerListItem is not None


def test_import_banner_preview_panel():
    """BannerPreviewPanel widget can be imported."""
    from code_puppy.tui.screens.colors_screen import BannerPreviewPanel

    assert BannerPreviewPanel is not None


def test_import_banner_markup_helper():
    """_banner_markup helper can be imported and returns a string."""
    from code_puppy.tui.screens.colors_screen import _banner_markup

    result = _banner_markup("THINKING", "⚡", "blue")
    assert isinstance(result, str)
    assert "THINKING" in result
    assert "blue" in result


# ---------------------------------------------------------------------------
# Class hierarchy
# ---------------------------------------------------------------------------


def test_colors_screen_is_menu_screen():
    """ColorsScreen is a subclass of MenuScreen."""
    from code_puppy.tui.base_screen import MenuScreen
    from code_puppy.tui.screens.colors_screen import ColorsScreen

    assert issubclass(ColorsScreen, MenuScreen)


def test_color_picker_screen_is_menu_screen():
    """ColorPickerScreen is a subclass of MenuScreen."""
    from code_puppy.tui.base_screen import MenuScreen
    from code_puppy.tui.screens.colors_screen import ColorPickerScreen

    assert issubclass(ColorPickerScreen, MenuScreen)


# ---------------------------------------------------------------------------
# Binding checks
# ---------------------------------------------------------------------------


def test_colors_screen_has_standard_bindings():
    """ColorsScreen inherits escape and q from MenuScreen."""
    from code_puppy.tui.screens.colors_screen import ColorsScreen

    keys = [b.key for b in ColorsScreen.BINDINGS]
    assert "escape" in keys
    assert "q" in keys


def test_colors_screen_has_enter_binding():
    """ColorsScreen has 'enter' binding for editing a banner."""
    from code_puppy.tui.screens.colors_screen import ColorsScreen

    keys = [b.key for b in ColorsScreen.BINDINGS]
    assert "enter" in keys


def test_colors_screen_has_save_binding():
    """ColorsScreen has 's' binding for save & exit."""
    from code_puppy.tui.screens.colors_screen import ColorsScreen

    keys = [b.key for b in ColorsScreen.BINDINGS]
    assert "s" in keys


def test_colors_screen_has_reset_binding():
    """ColorsScreen has 'r' binding for reset all defaults."""
    from code_puppy.tui.screens.colors_screen import ColorsScreen

    keys = [b.key for b in ColorsScreen.BINDINGS]
    assert "r" in keys


def test_color_picker_screen_has_enter_binding():
    """ColorPickerScreen has 'enter' binding for confirming color."""
    from code_puppy.tui.screens.colors_screen import ColorPickerScreen

    keys = [b.key for b in ColorPickerScreen.BINDINGS]
    assert "enter" in keys


def test_color_picker_screen_has_escape_binding():
    """ColorPickerScreen has 'escape' binding inherited from MenuScreen."""
    from code_puppy.tui.screens.colors_screen import ColorPickerScreen

    keys = [b.key for b in ColorPickerScreen.BINDINGS]
    assert "escape" in keys


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


def test_colors_screen_instantiation():
    """ColorsScreen can be instantiated without errors."""
    from code_puppy.tui.screens.colors_screen import ColorsScreen

    screen = ColorsScreen()
    assert screen is not None


def test_banner_list_item_instantiation():
    """BannerListItem can be instantiated with key and color."""
    from code_puppy.tui.screens.colors_screen import BannerListItem

    item = BannerListItem(banner_key="thinking", current_color="blue")
    assert item.banner_key == "thinking"
    assert item.current_color == "blue"


def test_banner_preview_panel_instantiation():
    """BannerPreviewPanel can be instantiated."""
    from code_puppy.tui.screens.colors_screen import BannerPreviewPanel

    panel = BannerPreviewPanel(id="test-preview")
    assert panel is not None


# ---------------------------------------------------------------------------
# ColorConfiguration wiring
# ---------------------------------------------------------------------------


def test_color_picker_screen_stores_banner_key():
    """ColorPickerScreen stores the banner_key and display name correctly."""
    from code_puppy.command_line.colors_menu import (
        BANNER_DISPLAY_INFO,
        ColorConfiguration,
    )
    from code_puppy.tui.screens.colors_screen import ColorPickerScreen

    config = ColorConfiguration()
    screen = ColorPickerScreen(banner_key="thinking", config=config)
    assert screen.banner_key == "thinking"
    assert screen._display_name == BANNER_DISPLAY_INFO["thinking"][0]


def test_color_picker_screen_stores_original_color():
    """ColorPickerScreen captures the original color at instantiation."""
    from code_puppy.command_line.colors_menu import ColorConfiguration
    from code_puppy.tui.screens.colors_screen import ColorPickerScreen

    config = ColorConfiguration()
    original = config.current_colors["thinking"]
    screen = ColorPickerScreen(banner_key="thinking", config=config)
    assert screen._original_color == original


def test_colors_screen_has_config():
    """ColorsScreen creates a ColorConfiguration on init."""
    from code_puppy.command_line.colors_menu import ColorConfiguration
    from code_puppy.tui.screens.colors_screen import ColorsScreen

    screen = ColorsScreen()
    assert isinstance(screen._config, ColorConfiguration)


# ---------------------------------------------------------------------------
# Data constants re-exported from colors_menu
# ---------------------------------------------------------------------------


def test_banner_display_info_imported():
    """BANNER_DISPLAY_INFO is accessible and contains expected keys."""
    from code_puppy.command_line.colors_menu import BANNER_DISPLAY_INFO

    assert "thinking" in BANNER_DISPLAY_INFO
    assert "shell_command" in BANNER_DISPLAY_INFO
    assert "read_file" in BANNER_DISPLAY_INFO


def test_banner_colors_imported():
    """BANNER_COLORS dict is accessible and non-empty."""
    from code_puppy.command_line.colors_menu import BANNER_COLORS

    assert len(BANNER_COLORS) > 0
    assert "blue" in BANNER_COLORS


def test_banner_sample_content_imported():
    """BANNER_SAMPLE_CONTENT is accessible for all banner keys."""
    from code_puppy.command_line.colors_menu import (
        BANNER_DISPLAY_INFO,
        BANNER_SAMPLE_CONTENT,
    )

    for key in BANNER_DISPLAY_INFO:
        assert key in BANNER_SAMPLE_CONTENT, f"Missing sample for {key}"


# ---------------------------------------------------------------------------
# Banner markup helper
# ---------------------------------------------------------------------------


def test_banner_markup_includes_icon():
    """_banner_markup includes the icon when provided."""
    from code_puppy.tui.screens.colors_screen import _banner_markup

    result = _banner_markup("SHELL COMMAND", "🚀", "navy_blue")
    assert "🚀" in result


def test_banner_markup_no_icon():
    """_banner_markup handles empty icon gracefully."""
    from code_puppy.tui.screens.colors_screen import _banner_markup

    result = _banner_markup("AGENT RESPONSE", "", "green4")
    assert "AGENT RESPONSE" in result
    assert "green4" in result


def test_banner_markup_uses_color():
    """_banner_markup embeds the color value in markup."""
    from code_puppy.tui.screens.colors_screen import _banner_markup

    result = _banner_markup("THINKING", "⚡", "purple")
    assert "purple" in result


# ---------------------------------------------------------------------------
# app.py wiring — /colors command
# ---------------------------------------------------------------------------


def test_app_handles_colors_command():
    """app.py handles /colors command via dispatch table."""
    import inspect

    from code_puppy.tui.app import CodePuppyApp

    # Check dispatch table has /colors handler
    assert "/colors" in CodePuppyApp._SLASH_COMMANDS, (
        "/colors should be in _SLASH_COMMANDS dispatch table"
    )
    assert CodePuppyApp._SLASH_COMMANDS["/colors"] == "_cmd_colors"

    # Check _cmd_colors method exists and references ColorsScreen
    source = inspect.getsource(CodePuppyApp._cmd_colors)
    assert "ColorsScreen" in source, "_cmd_colors should push ColorsScreen"
