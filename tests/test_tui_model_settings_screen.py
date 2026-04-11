"""Tests for the ModelSettingsScreen Textual screen."""



def test_import_screen():
    """Verify the screen module can be imported."""
    from code_puppy.tui.screens.model_settings_screen import ModelSettingsScreen

    assert ModelSettingsScreen is not None


def test_is_menu_screen_subclass():
    """Verify ModelSettingsScreen is a MenuScreen subclass."""
    from code_puppy.tui.base_screen import MenuScreen
    from code_puppy.tui.screens.model_settings_screen import ModelSettingsScreen

    assert issubclass(ModelSettingsScreen, MenuScreen)


def test_screen_has_standard_bindings():
    """Verify ModelSettingsScreen inherits standard MenuScreen bindings."""
    from code_puppy.tui.screens.model_settings_screen import ModelSettingsScreen

    binding_keys = [b.key for b in ModelSettingsScreen.BINDINGS]
    assert "escape" in binding_keys
    assert "q" in binding_keys


def test_screen_has_enter_binding():
    """Verify ModelSettingsScreen has 'enter' binding for model selection."""
    from code_puppy.tui.screens.model_settings_screen import ModelSettingsScreen

    binding_keys = [b.key for b in ModelSettingsScreen.BINDINGS]
    assert "enter" in binding_keys


def test_settings_panel_importable():
    """Verify SettingsPanel widget can be imported."""
    from code_puppy.tui.screens.model_settings_screen import SettingsPanel

    assert SettingsPanel is not None


def test_setting_item_importable():
    """Verify SettingItem can be imported."""
    from code_puppy.tui.screens.model_settings_screen import SettingItem

    assert SettingItem is not None


def test_setting_definitions_imported():
    """Verify SETTING_DEFINITIONS is accessible via the screen module."""
    from code_puppy.command_line.model_settings_menu import SETTING_DEFINITIONS

    # Spot-check a few known settings
    assert "temperature" in SETTING_DEFINITIONS
    assert "seed" in SETTING_DEFINITIONS
    assert "reasoning_effort" in SETTING_DEFINITIONS
    assert "extended_thinking" in SETTING_DEFINITIONS

    temp_def = SETTING_DEFINITIONS["temperature"]
    assert temp_def["type"] == "numeric"
    assert temp_def["min"] == 0.0
    assert temp_def["max"] == 1.0


def test_screen_instantiation():
    """Verify ModelSettingsScreen can be instantiated without error."""
    from code_puppy.tui.screens.model_settings_screen import ModelSettingsScreen

    screen = ModelSettingsScreen()
    assert screen is not None


def test_settings_panel_instantiation():
    """Verify SettingsPanel can be instantiated without error."""
    from code_puppy.tui.screens.model_settings_screen import SettingsPanel

    panel = SettingsPanel(id="test-panel")
    assert panel is not None


def test_settings_panel_has_bindings():
    """Verify SettingsPanel has directional and reset bindings."""
    from code_puppy.tui.screens.model_settings_screen import SettingsPanel

    binding_keys = [b.key for b in SettingsPanel.BINDINGS]
    assert "left" in binding_keys
    assert "right" in binding_keys
    assert "d" in binding_keys
    assert "escape" in binding_keys


def test_focus_constants():
    """Verify focus target constants are defined."""
    from code_puppy.tui.screens.model_settings_screen import (
        _FOCUS_MODELS,
        _FOCUS_SETTINGS,
    )

    assert _FOCUS_MODELS == "models"
    assert _FOCUS_SETTINGS == "settings"
