"""Tests for the DiffScreen Textual screen.

Covers import, instantiation, class hierarchy, bindings,
and inner widget accessibility — all without spinning up a real TUI.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


def test_import_diff_screen():
    """Verify the module can be imported without side-effects."""
    from code_puppy.tui.screens.diff_screen import DiffScreen

    assert DiffScreen is not None


def test_import_diff_color_item():
    """Verify DiffColorItem can be imported."""
    from code_puppy.tui.screens.diff_screen import DiffColorItem

    assert DiffColorItem is not None


def test_import_diff_settings_panel():
    """Verify DiffSettingsPanel can be imported."""
    from code_puppy.tui.screens.diff_screen import DiffSettingsPanel

    assert DiffSettingsPanel is not None


def test_import_diff_preview_panel():
    """Verify DiffPreviewPanel can be imported."""
    from code_puppy.tui.screens.diff_screen import DiffPreviewPanel

    assert DiffPreviewPanel is not None


# ---------------------------------------------------------------------------
# Class hierarchy
# ---------------------------------------------------------------------------


def test_diff_screen_is_menu_screen_subclass():
    """DiffScreen must extend MenuScreen."""
    from code_puppy.tui.base_screen import MenuScreen
    from code_puppy.tui.screens.diff_screen import DiffScreen

    assert issubclass(DiffScreen, MenuScreen)


def test_diff_color_item_is_list_item():
    """DiffColorItem must extend Textual ListItem."""
    from textual.widgets import ListItem

    from code_puppy.tui.screens.diff_screen import DiffColorItem

    assert issubclass(DiffColorItem, ListItem)


def test_diff_settings_panel_is_widget():
    """DiffSettingsPanel must extend Textual Widget."""
    from textual.widget import Widget

    from code_puppy.tui.screens.diff_screen import DiffSettingsPanel

    assert issubclass(DiffSettingsPanel, Widget)


def test_diff_preview_panel_is_widget():
    """DiffPreviewPanel must extend Textual Widget."""
    from textual.widget import Widget

    from code_puppy.tui.screens.diff_screen import DiffPreviewPanel

    assert issubclass(DiffPreviewPanel, Widget)


# ---------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------


def test_diff_screen_has_standard_bindings():
    """DiffScreen must inherit escape and q from MenuScreen."""
    from code_puppy.tui.screens.diff_screen import DiffScreen

    keys = [b.key for b in DiffScreen.BINDINGS]
    assert "escape" in keys
    assert "q" in keys


def test_diff_screen_has_language_bindings():
    """DiffScreen must expose [ ] for language cycling."""
    from code_puppy.tui.screens.diff_screen import DiffScreen

    keys = [b.key for b in DiffScreen.BINDINGS]
    assert "[" in keys
    assert "]" in keys


def test_diff_screen_has_save_binding():
    """DiffScreen must have 's' for explicit save."""
    from code_puppy.tui.screens.diff_screen import DiffScreen

    keys = [b.key for b in DiffScreen.BINDINGS]
    assert "s" in keys


def test_settings_panel_has_cycle_bindings():
    """DiffSettingsPanel must have left/right bindings for color cycling."""
    from code_puppy.tui.screens.diff_screen import DiffSettingsPanel

    keys = [b.key for b in DiffSettingsPanel.BINDINGS]
    assert "left" in keys
    assert "right" in keys


def test_settings_panel_has_reset_binding():
    """DiffSettingsPanel must have 'd' binding for reset."""
    from code_puppy.tui.screens.diff_screen import DiffSettingsPanel

    keys = [b.key for b in DiffSettingsPanel.BINDINGS]
    assert "d" in keys


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


def test_diff_screen_instantiation():
    """DiffScreen must instantiate without errors."""
    from code_puppy.tui.screens.diff_screen import DiffScreen

    screen = DiffScreen()
    assert screen is not None


def test_diff_settings_panel_instantiation():
    """DiffSettingsPanel must instantiate without errors."""
    from code_puppy.tui.screens.diff_screen import DiffSettingsPanel

    panel = DiffSettingsPanel(id="test-settings")
    assert panel is not None


def test_diff_preview_panel_instantiation():
    """DiffPreviewPanel must instantiate with a DiffConfiguration."""
    from code_puppy.command_line.diff_menu import DiffConfiguration
    from code_puppy.tui.screens.diff_screen import DiffPreviewPanel

    config = DiffConfiguration()
    panel = DiffPreviewPanel(config, id="test-preview")
    assert panel is not None


# ---------------------------------------------------------------------------
# DiffColorItem behaviour
# ---------------------------------------------------------------------------


def test_diff_color_item_additions_instantiation():
    """DiffColorItem for 'additions' must set correct internal state."""
    from code_puppy.command_line.diff_menu import ADDITION_COLORS
    from code_puppy.tui.screens.diff_screen import DiffColorItem

    item = DiffColorItem("additions", id="test-add")
    assert item.setting_type == "additions"
    assert item._color_dict is ADDITION_COLORS


def test_diff_color_item_deletions_instantiation():
    """DiffColorItem for 'deletions' must set correct internal state."""
    from code_puppy.command_line.diff_menu import DELETION_COLORS
    from code_puppy.tui.screens.diff_screen import DiffColorItem

    item = DiffColorItem("deletions", id="test-del")
    assert item.setting_type == "deletions"
    assert item._color_dict is DELETION_COLORS


def test_diff_color_item_current_color_value():
    """current_color_value() must return a hex string from the palette."""
    from code_puppy.tui.screens.diff_screen import DiffColorItem

    item = DiffColorItem("additions", id="test-val")
    val = item.current_color_value()
    assert isinstance(val, str)
    assert val.startswith("#")


def test_diff_color_item_cycle_next():
    """cycle_next() must advance the color index."""
    from code_puppy.tui.screens.diff_screen import DiffColorItem

    item = DiffColorItem("additions", id="test-next")
    old_index = item._color_index
    item.cycle_next()
    new_index = item._color_index
    # Index should change (wraps around with modulo)
    total = len(item._color_dict)
    assert new_index == (old_index + 1) % total


def test_diff_color_item_cycle_prev():
    """cycle_prev() must retreat the color index."""
    from code_puppy.tui.screens.diff_screen import DiffColorItem

    item = DiffColorItem("additions", id="test-prev")
    old_index = item._color_index
    item.cycle_prev()
    new_index = item._color_index
    total = len(item._color_dict)
    assert new_index == (old_index - 1) % total


def test_diff_color_item_reset_default():
    """reset_default() must set the color index to 0."""
    from code_puppy.tui.screens.diff_screen import DiffColorItem

    item = DiffColorItem("additions", id="test-reset")
    item._color_index = 5  # move away from default
    item.reset_default()
    assert item._color_index == 0


# ---------------------------------------------------------------------------
# DiffConfiguration integration
# ---------------------------------------------------------------------------


def test_diff_screen_uses_diff_configuration():
    """DiffScreen must hold a DiffConfiguration instance."""
    from code_puppy.command_line.diff_menu import DiffConfiguration
    from code_puppy.tui.screens.diff_screen import DiffScreen

    screen = DiffScreen()
    assert isinstance(screen._config, DiffConfiguration)


def test_diff_configuration_has_changes_false_initially():
    """Fresh DiffConfiguration should report no changes."""
    from code_puppy.command_line.diff_menu import DiffConfiguration

    config = DiffConfiguration()
    assert config.has_changes() is False


def test_diff_configuration_language_cycling():
    """DiffConfiguration language cycling must stay in bounds."""
    from code_puppy.command_line.diff_menu import DiffConfiguration, SUPPORTED_LANGUAGES

    config = DiffConfiguration()
    assert config.get_current_language() == SUPPORTED_LANGUAGES[0]
    config.next_language()
    assert config.get_current_language() == SUPPORTED_LANGUAGES[1]
    config.prev_language()
    assert config.get_current_language() == SUPPORTED_LANGUAGES[0]


# ---------------------------------------------------------------------------
# Re-export check: shared constants reachable from diff_screen module
# ---------------------------------------------------------------------------


def test_addition_colors_available():
    """ADDITION_COLORS should be importable (used by DiffColorItem)."""
    from code_puppy.command_line.diff_menu import ADDITION_COLORS

    assert isinstance(ADDITION_COLORS, dict)
    assert len(ADDITION_COLORS) > 0


def test_deletion_colors_available():
    """DELETION_COLORS should be importable (used by DiffColorItem)."""
    from code_puppy.command_line.diff_menu import DELETION_COLORS

    assert isinstance(DELETION_COLORS, dict)
    assert len(DELETION_COLORS) > 0


def test_language_samples_available():
    """LANGUAGE_SAMPLES should be importable and non-empty."""
    from code_puppy.command_line.diff_menu import LANGUAGE_SAMPLES

    assert isinstance(LANGUAGE_SAMPLES, dict)
    assert "python" in LANGUAGE_SAMPLES
