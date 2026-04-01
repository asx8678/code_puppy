"""Tests for the TUI foundation module."""

import pytest


def test_tui_imports():
    """Verify all TUI foundation modules can be imported."""
    from code_puppy.tui import MenuScreen, SearchableList, SplitPanel

    assert MenuScreen is not None
    assert SearchableList is not None
    assert SplitPanel is not None


def test_theme_module():
    """Verify theme module loads."""
    from code_puppy.tui.theme import APP_CSS, get_banner_css

    assert isinstance(APP_CSS, str)
    assert len(APP_CSS) > 0
    banner_css = get_banner_css()
    assert isinstance(banner_css, str)


def test_searchable_list_item_creation():
    """Verify SearchableListItem can be constructed."""
    from code_puppy.tui.widgets.searchable_list import SearchableListItem

    item = SearchableListItem(label="test-model", item_id="m1", badge="active")
    assert item.label_text == "test-model"
    assert item.item_id == "m1"
    assert item.badge_text == "active"
    assert not item.item_disabled


def test_searchable_list_item_disabled():
    """Verify disabled state works."""
    from code_puppy.tui.widgets.searchable_list import SearchableListItem

    item = SearchableListItem(label="broken", disabled=True)
    assert item.item_disabled


def test_base_screen_bindings():
    """Verify MenuScreen has standard bindings."""
    from code_puppy.tui.base_screen import MenuScreen

    binding_keys = [b.key for b in MenuScreen.BINDINGS]
    assert "escape" in binding_keys
    assert "q" in binding_keys
