"""Tests for autosave, onboarding, and UC Textual screens.

Verifies:
- Each screen can be imported and instantiated
- Each screen inherits from MenuScreen
- Expected key bindings are present
- Helper functions exist and behave correctly
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Binding helper
# ---------------------------------------------------------------------------


def _binding_keys(screen_cls) -> set[str]:
    """Return the set of key strings declared in a screen's BINDINGS."""
    return {b.key for b in screen_cls.BINDINGS}


# ===========================================================================
# AutosaveScreen
# ===========================================================================


class TestAutosaveScreen:
    def test_importable(self) -> None:
        from code_puppy.tui.screens.autosave_screen import AutosaveScreen  # noqa: F401

        assert AutosaveScreen is not None

    def test_is_menu_screen(self) -> None:
        from code_puppy.tui.base_screen import MenuScreen
        from code_puppy.tui.screens.autosave_screen import AutosaveScreen

        assert issubclass(AutosaveScreen, MenuScreen)

    def test_instantiates(self) -> None:
        from code_puppy.tui.screens.autosave_screen import AutosaveScreen

        screen = AutosaveScreen()
        assert screen is not None

    def test_has_enter_binding(self) -> None:
        from code_puppy.tui.screens.autosave_screen import AutosaveScreen

        assert "enter" in _binding_keys(AutosaveScreen)

    def test_has_escape_binding(self) -> None:
        from code_puppy.tui.screens.autosave_screen import AutosaveScreen

        assert "escape" in _binding_keys(AutosaveScreen)

    def test_helper_get_session_metadata_missing_returns_empty(self, tmp_path) -> None:
        from code_puppy.tui.screens.autosave_screen import _get_session_metadata

        result = _get_session_metadata(tmp_path, "nonexistent_session")
        assert result == {}

    def test_helper_get_session_entries_empty_dir(self, tmp_path) -> None:
        from code_puppy.tui.screens.autosave_screen import _get_session_entries

        result = _get_session_entries(tmp_path)
        assert isinstance(result, list)
        assert result == []

    def test_helper_get_session_entries_nonexistent_dir(self, tmp_path) -> None:
        from code_puppy.tui.screens.autosave_screen import _get_session_entries

        result = _get_session_entries(tmp_path / "does_not_exist")
        assert result == []

    def test_helper_extract_last_user_message_empty(self) -> None:
        from code_puppy.tui.screens.autosave_screen import _extract_last_user_message

        result = _extract_last_user_message([])
        assert result == "[No messages found]"

    def test_helper_extract_last_user_message_with_content(self) -> None:
        from code_puppy.tui.screens.autosave_screen import _extract_last_user_message

        class FakePart:
            content = "Hello from user"

        class FakeMsg:
            parts = [FakePart()]

        result = _extract_last_user_message([FakeMsg()])
        assert "Hello from user" in result

    def test_base_dir_set_from_autosave_dir(self) -> None:
        """AutosaveScreen uses AUTOSAVE_DIR as its base directory."""
        from pathlib import Path

        from code_puppy.config import AUTOSAVE_DIR
        from code_puppy.tui.screens.autosave_screen import AutosaveScreen

        screen = AutosaveScreen()
        assert screen._base_dir == Path(AUTOSAVE_DIR)


# ===========================================================================
# OnboardingScreen
# ===========================================================================


class TestOnboardingScreen:
    def test_importable(self) -> None:
        from code_puppy.tui.screens.onboarding_screen import OnboardingScreen  # noqa: F401

        assert OnboardingScreen is not None

    def test_is_menu_screen(self) -> None:
        from code_puppy.tui.base_screen import MenuScreen
        from code_puppy.tui.screens.onboarding_screen import OnboardingScreen

        assert issubclass(OnboardingScreen, MenuScreen)

    def test_instantiates(self) -> None:
        from code_puppy.tui.screens.onboarding_screen import OnboardingScreen

        screen = OnboardingScreen()
        assert screen is not None

    def test_has_right_binding(self) -> None:
        from code_puppy.tui.screens.onboarding_screen import OnboardingScreen

        assert "right" in _binding_keys(OnboardingScreen)

    def test_has_left_binding(self) -> None:
        from code_puppy.tui.screens.onboarding_screen import OnboardingScreen

        assert "left" in _binding_keys(OnboardingScreen)

    def test_has_enter_binding(self) -> None:
        from code_puppy.tui.screens.onboarding_screen import OnboardingScreen

        assert "enter" in _binding_keys(OnboardingScreen)

    def test_has_escape_binding(self) -> None:
        from code_puppy.tui.screens.onboarding_screen import OnboardingScreen

        assert "escape" in _binding_keys(OnboardingScreen)

    def test_has_vim_navigation_bindings(self) -> None:
        from code_puppy.tui.screens.onboarding_screen import OnboardingScreen

        keys = _binding_keys(OnboardingScreen)
        assert "j" in keys  # down option
        assert "k" in keys  # up option
        assert "h" in keys  # prev slide
        assert "l" in keys  # next slide

    def test_wizard_initialized(self) -> None:
        from code_puppy.command_line.onboarding_wizard import OnboardingWizard
        from code_puppy.tui.screens.onboarding_screen import OnboardingScreen

        screen = OnboardingScreen()
        assert isinstance(screen._wizard, OnboardingWizard)

    def test_wizard_starts_at_slide_zero(self) -> None:
        from code_puppy.tui.screens.onboarding_screen import OnboardingScreen

        screen = OnboardingScreen()
        assert screen._wizard.current_slide == 0

    def test_total_slides_constant(self) -> None:
        from code_puppy.tui.screens.onboarding_screen import TOTAL_SLIDES

        assert TOTAL_SLIDES == 5


# ===========================================================================
# UCScreen
# ===========================================================================


class TestUCScreen:
    def test_importable(self) -> None:
        from code_puppy.tui.screens.uc_screen import UCScreen  # noqa: F401

        assert UCScreen is not None

    def test_is_menu_screen(self) -> None:
        from code_puppy.tui.base_screen import MenuScreen
        from code_puppy.tui.screens.uc_screen import UCScreen

        assert issubclass(UCScreen, MenuScreen)

    def test_instantiates(self) -> None:
        from code_puppy.tui.screens.uc_screen import UCScreen

        screen = UCScreen()
        assert screen is not None

    def test_has_enter_binding(self) -> None:
        from code_puppy.tui.screens.uc_screen import UCScreen

        assert "enter" in _binding_keys(UCScreen)

    def test_has_e_binding(self) -> None:
        from code_puppy.tui.screens.uc_screen import UCScreen

        assert "e" in _binding_keys(UCScreen)

    def test_has_d_binding(self) -> None:
        from code_puppy.tui.screens.uc_screen import UCScreen

        assert "d" in _binding_keys(UCScreen)

    def test_has_escape_binding(self) -> None:
        from code_puppy.tui.screens.uc_screen import UCScreen

        assert "escape" in _binding_keys(UCScreen)

    def test_source_screen_importable(self) -> None:
        from code_puppy.tui.screens.uc_screen import SourceScreen  # noqa: F401

        assert SourceScreen is not None

    def test_source_screen_is_menu_screen(self) -> None:
        from code_puppy.tui.base_screen import MenuScreen
        from code_puppy.tui.screens.uc_screen import SourceScreen

        assert issubclass(SourceScreen, MenuScreen)

    def test_helper_get_tool_entries_returns_list(self) -> None:
        from code_puppy.tui.screens.uc_screen import _get_tool_entries

        result = _get_tool_entries()
        assert isinstance(result, list)

    def test_helper_toggle_tool_enabled_bad_path(self) -> None:
        """_toggle_tool_enabled fails gracefully with a bad source path."""
        from unittest.mock import MagicMock

        from code_puppy.tui.screens.uc_screen import _toggle_tool_enabled

        tool = MagicMock()
        tool.source_path = "/nonexistent/path/tool.py"
        tool.meta.enabled = True
        result = _toggle_tool_enabled(tool)
        assert result is False

    def test_helper_delete_tool_nonexistent_path(self) -> None:
        """_delete_tool returns False when source file does not exist."""
        from unittest.mock import MagicMock

        from code_puppy.tui.screens.uc_screen import _delete_tool

        tool = MagicMock()
        tool.source_path = "/nonexistent/path/tool.py"
        result = _delete_tool(tool)
        assert result is False

    def test_uc_screen_starts_with_empty_tools(self) -> None:
        from code_puppy.tui.screens.uc_screen import UCScreen

        screen = UCScreen()
        assert screen._tools == []


# ===========================================================================
# App wiring tests
# ===========================================================================


class TestAppWiring:
    def test_app_handles_autosave_load_command(self) -> None:
        """app.py _handle_slash_command references AutosaveScreen for /autosave_load."""
        import ast
        from pathlib import Path

        source = (
            Path(__file__).parent.parent / "code_puppy" / "tui" / "app.py"
        ).read_text()
        assert "AutosaveScreen" in source
        assert "/autosave_load" in source

    def test_app_handles_tutorial_command(self) -> None:
        """app.py _handle_slash_command references OnboardingScreen for /tutorial."""
        from pathlib import Path

        source = (
            Path(__file__).parent.parent / "code_puppy" / "tui" / "app.py"
        ).read_text()
        assert "OnboardingScreen" in source
        assert "/tutorial" in source

    def test_app_handles_uc_command(self) -> None:
        """app.py _handle_slash_command references UCScreen for /uc."""
        from pathlib import Path

        source = (
            Path(__file__).parent.parent / "code_puppy" / "tui" / "app.py"
        ).read_text()
        assert "UCScreen" in source
        assert '"/uc"' in source
