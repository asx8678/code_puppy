"""Tests for plugin menu Textual screens.

Covers:
- SkillsScreen
- SkillsInstallScreen
- HooksScreen
- SchedulerScreen
- SchedulerWizardScreen

Verifies: import, instantiation, inheritance, key bindings, and
helper-function contracts. No actual Textual app loop is started.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _binding_keys(screen_cls) -> set[str]:
    """Return all key strings from a screen's BINDINGS list."""
    return {b.key for b in screen_cls.BINDINGS}


# ===========================================================================
# SkillsScreen
# ===========================================================================


class TestSkillsScreen:
    def test_importable(self) -> None:
        from code_puppy.tui.screens.skills_screen import SkillsScreen

        assert SkillsScreen is not None

    def test_is_menu_screen(self) -> None:
        from code_puppy.tui.base_screen import MenuScreen
        from code_puppy.tui.screens.skills_screen import SkillsScreen

        assert issubclass(SkillsScreen, MenuScreen)

    def test_instantiates(self) -> None:
        from code_puppy.tui.screens.skills_screen import SkillsScreen

        screen = SkillsScreen()
        assert screen is not None

    def test_has_escape_binding(self) -> None:
        from code_puppy.tui.screens.skills_screen import SkillsScreen

        assert "escape" in _binding_keys(SkillsScreen)

    def test_has_enter_binding(self) -> None:
        from code_puppy.tui.screens.skills_screen import SkillsScreen

        assert "enter" in _binding_keys(SkillsScreen)

    def test_has_t_binding(self) -> None:
        from code_puppy.tui.screens.skills_screen import SkillsScreen

        assert "t" in _binding_keys(SkillsScreen)

    def test_has_i_binding(self) -> None:
        from code_puppy.tui.screens.skills_screen import SkillsScreen

        assert "i" in _binding_keys(SkillsScreen)

    def test_load_skills_data_returns_tuple(self) -> None:
        from code_puppy.tui.screens.skills_screen import _load_skills_data

        result = _load_skills_data()
        assert isinstance(result, tuple)
        assert len(result) == 3
        skills, disabled, enabled = result
        assert isinstance(skills, list)
        assert isinstance(disabled, set)
        assert isinstance(enabled, bool)

    def test_get_skill_name_with_no_metadata(self) -> None:
        from code_puppy.tui.screens.skills_screen import _get_skill_name

        class FakeSkill:
            name = "my-skill"
            path = "/nonexistent/path"

        name = _get_skill_name(FakeSkill())
        assert isinstance(name, str)
        assert len(name) > 0

    def test_initial_state(self) -> None:
        from code_puppy.tui.screens.skills_screen import SkillsScreen

        screen = SkillsScreen()
        assert screen._skills == []
        assert screen._disabled == set()
        assert screen._system_enabled is False

    def test_has_refresh_binding(self) -> None:
        from code_puppy.tui.screens.skills_screen import SkillsScreen

        assert "r" in _binding_keys(SkillsScreen)

    def test_has_action_toggle_skill(self) -> None:
        from code_puppy.tui.screens.skills_screen import SkillsScreen

        assert callable(getattr(SkillsScreen, "action_toggle_skill", None))

    def test_has_action_toggle_system(self) -> None:
        from code_puppy.tui.screens.skills_screen import SkillsScreen

        assert callable(getattr(SkillsScreen, "action_toggle_system", None))

    def test_has_action_open_install(self) -> None:
        from code_puppy.tui.screens.skills_screen import SkillsScreen

        assert callable(getattr(SkillsScreen, "action_open_install", None))


# ===========================================================================
# SkillsInstallScreen
# ===========================================================================


class TestSkillsInstallScreen:
    def test_importable(self) -> None:
        from code_puppy.tui.screens.skills_install_screen import SkillsInstallScreen

        assert SkillsInstallScreen is not None

    def test_is_menu_screen(self) -> None:
        from code_puppy.tui.base_screen import MenuScreen
        from code_puppy.tui.screens.skills_install_screen import SkillsInstallScreen

        assert issubclass(SkillsInstallScreen, MenuScreen)

    def test_instantiates(self) -> None:
        from code_puppy.tui.screens.skills_install_screen import SkillsInstallScreen

        screen = SkillsInstallScreen()
        assert screen is not None

    def test_has_escape_binding(self) -> None:
        from code_puppy.tui.screens.skills_install_screen import SkillsInstallScreen

        assert "escape" in _binding_keys(SkillsInstallScreen)

    def test_has_enter_binding(self) -> None:
        from code_puppy.tui.screens.skills_install_screen import SkillsInstallScreen

        assert "enter" in _binding_keys(SkillsInstallScreen)

    def test_initial_state(self) -> None:
        from code_puppy.tui.screens.skills_install_screen import SkillsInstallScreen

        screen = SkillsInstallScreen()
        assert screen._catalog_skills == []

    def test_load_catalog_skills_returns_list(self) -> None:
        from code_puppy.tui.screens.skills_install_screen import _load_catalog_skills

        result = _load_catalog_skills()
        assert isinstance(result, list)

    def test_is_installed_unknown_returns_false(self) -> None:
        from code_puppy.tui.screens.skills_install_screen import _is_installed

        assert _is_installed("this-skill-does-not-exist-xyz-abc") is False

    def test_format_bytes_zero(self) -> None:
        from code_puppy.tui.screens.skills_install_screen import _format_bytes

        assert _format_bytes(0) == "0 B"

    def test_format_bytes_kilobytes(self) -> None:
        from code_puppy.tui.screens.skills_install_screen import _format_bytes

        result = _format_bytes(2048)
        assert "KB" in result

    def test_format_bytes_megabytes(self) -> None:
        from code_puppy.tui.screens.skills_install_screen import _format_bytes

        result = _format_bytes(1024 * 1024 * 2)
        assert "MB" in result

    def test_category_icons_defined(self) -> None:
        from code_puppy.tui.screens.skills_install_screen import CATEGORY_ICONS

        assert isinstance(CATEGORY_ICONS, dict)
        assert len(CATEGORY_ICONS) > 0

    def test_has_action_install_skill(self) -> None:
        from code_puppy.tui.screens.skills_install_screen import SkillsInstallScreen

        assert callable(getattr(SkillsInstallScreen, "action_install_skill", None))


# ===========================================================================
# HooksScreen
# ===========================================================================


class TestHooksScreen:
    def test_importable(self) -> None:
        from code_puppy.tui.screens.hooks_screen import HooksScreen

        assert HooksScreen is not None

    def test_is_menu_screen(self) -> None:
        from code_puppy.tui.base_screen import MenuScreen
        from code_puppy.tui.screens.hooks_screen import HooksScreen

        assert issubclass(HooksScreen, MenuScreen)

    def test_instantiates(self) -> None:
        from code_puppy.tui.screens.hooks_screen import HooksScreen

        screen = HooksScreen()
        assert screen is not None

    def test_has_escape_binding(self) -> None:
        from code_puppy.tui.screens.hooks_screen import HooksScreen

        assert "escape" in _binding_keys(HooksScreen)

    def test_has_refresh_binding(self) -> None:
        from code_puppy.tui.screens.hooks_screen import HooksScreen

        assert "r" in _binding_keys(HooksScreen)

    def test_initial_state(self) -> None:
        from code_puppy.tui.screens.hooks_screen import HooksScreen

        screen = HooksScreen()
        assert screen._hooks == []

    def test_load_hooks_returns_list(self) -> None:
        from code_puppy.tui.screens.hooks_screen import _load_hooks

        result = _load_hooks()
        assert isinstance(result, list)

    def test_has_action_refresh(self) -> None:
        from code_puppy.tui.screens.hooks_screen import HooksScreen

        assert callable(getattr(HooksScreen, "action_refresh", None))

    def test_no_edit_bindings(self) -> None:
        """HooksScreen is read-only — no delete/toggle bindings expected."""
        from code_puppy.tui.screens.hooks_screen import HooksScreen

        keys = _binding_keys(HooksScreen)
        # Should NOT have edit-specific bindings
        assert "d" not in keys
        assert "enter" not in keys


# ===========================================================================
# SchedulerScreen
# ===========================================================================


class TestSchedulerScreen:
    def test_importable(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import SchedulerScreen

        assert SchedulerScreen is not None

    def test_is_menu_screen(self) -> None:
        from code_puppy.tui.base_screen import MenuScreen
        from code_puppy.tui.screens.scheduler_screen import SchedulerScreen

        assert issubclass(SchedulerScreen, MenuScreen)

    def test_instantiates(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import SchedulerScreen

        screen = SchedulerScreen()
        assert screen is not None

    def test_has_escape_binding(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import SchedulerScreen

        assert "escape" in _binding_keys(SchedulerScreen)

    def test_has_enter_binding(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import SchedulerScreen

        assert "enter" in _binding_keys(SchedulerScreen)

    def test_has_n_binding(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import SchedulerScreen

        assert "n" in _binding_keys(SchedulerScreen)

    def test_has_refresh_binding(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import SchedulerScreen

        assert "r" in _binding_keys(SchedulerScreen)

    def test_initial_state(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import SchedulerScreen

        screen = SchedulerScreen()
        assert screen._tasks == []

    def test_load_tasks_returns_list(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import _load_tasks

        result = _load_tasks()
        assert isinstance(result, list)

    def test_get_daemon_info_returns_tuple(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import _get_daemon_info

        result = _get_daemon_info()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_status_icon_disabled(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import _status_icon

        class FakeTask:
            enabled = False
            last_status = None

        icon, color = _status_icon(FakeTask())
        assert icon == "⏸"
        assert color == "yellow"

    def test_status_icon_success(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import _status_icon

        class FakeTask:
            enabled = True
            last_status = "success"

        icon, color = _status_icon(FakeTask())
        assert icon == "✓"
        assert color == "green"

    def test_status_icon_failed(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import _status_icon

        class FakeTask:
            enabled = True
            last_status = "failed"

        icon, color = _status_icon(FakeTask())
        assert icon == "✗"
        assert color == "red"

    def test_has_action_toggle_task(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import SchedulerScreen

        assert callable(getattr(SchedulerScreen, "action_toggle_task", None))

    def test_has_action_new_task(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import SchedulerScreen

        assert callable(getattr(SchedulerScreen, "action_new_task", None))


# ===========================================================================
# SchedulerWizardScreen
# ===========================================================================


class TestSchedulerWizardScreen:
    def test_importable(self) -> None:
        from code_puppy.tui.screens.scheduler_wizard_screen import (
            SchedulerWizardScreen,
        )

        assert SchedulerWizardScreen is not None

    def test_is_menu_screen(self) -> None:
        from code_puppy.tui.base_screen import MenuScreen
        from code_puppy.tui.screens.scheduler_wizard_screen import (
            SchedulerWizardScreen,
        )

        assert issubclass(SchedulerWizardScreen, MenuScreen)

    def test_instantiates(self) -> None:
        from code_puppy.tui.screens.scheduler_wizard_screen import (
            SchedulerWizardScreen,
        )

        screen = SchedulerWizardScreen()
        assert screen is not None

    def test_has_escape_binding(self) -> None:
        from code_puppy.tui.screens.scheduler_wizard_screen import (
            SchedulerWizardScreen,
        )

        assert "escape" in _binding_keys(SchedulerWizardScreen)

    def test_has_ctrl_s_binding(self) -> None:
        from code_puppy.tui.screens.scheduler_wizard_screen import (
            SchedulerWizardScreen,
        )

        assert "ctrl+s" in _binding_keys(SchedulerWizardScreen)

    def test_has_action_save_task(self) -> None:
        from code_puppy.tui.screens.scheduler_wizard_screen import (
            SchedulerWizardScreen,
        )

        assert callable(getattr(SchedulerWizardScreen, "action_save_task", None))

    def test_parse_schedule_interval(self) -> None:
        from code_puppy.tui.screens.scheduler_wizard_screen import (
            SchedulerWizardScreen,
        )

        screen = SchedulerWizardScreen()
        stype, sval = screen._parse_schedule("1h")
        assert stype == "hourly"
        assert sval == "1h"

    def test_parse_schedule_cron(self) -> None:
        from code_puppy.tui.screens.scheduler_wizard_screen import (
            SchedulerWizardScreen,
        )

        screen = SchedulerWizardScreen()
        stype, sval = screen._parse_schedule("0 9 * * *")
        assert stype == "cron"
        assert sval == "0 9 * * *"

    def test_parse_schedule_custom(self) -> None:
        from code_puppy.tui.screens.scheduler_wizard_screen import (
            SchedulerWizardScreen,
        )

        screen = SchedulerWizardScreen()
        stype, sval = screen._parse_schedule("45m")
        assert stype == "interval"
        assert sval == "45m"

    def test_parse_schedule_empty_defaults(self) -> None:
        from code_puppy.tui.screens.scheduler_wizard_screen import (
            SchedulerWizardScreen,
        )

        screen = SchedulerWizardScreen()
        stype, sval = screen._parse_schedule("")
        assert stype == "interval"
        assert sval == "1h"

    def test_parse_schedule_daily(self) -> None:
        from code_puppy.tui.screens.scheduler_wizard_screen import (
            SchedulerWizardScreen,
        )

        screen = SchedulerWizardScreen()
        stype, sval = screen._parse_schedule("24h")
        assert stype == "daily"

    def test_parse_schedule_15m(self) -> None:
        from code_puppy.tui.screens.scheduler_wizard_screen import (
            SchedulerWizardScreen,
        )

        screen = SchedulerWizardScreen()
        stype, sval = screen._parse_schedule("15m")
        assert stype == "interval"
        assert sval == "15m"


# ===========================================================================
# App wiring
# ===========================================================================


class TestAppWiring:
    def test_skills_screen_importable(self) -> None:
        from code_puppy.tui.screens.skills_screen import SkillsScreen

        assert SkillsScreen is not None

    def test_skills_install_screen_importable(self) -> None:
        from code_puppy.tui.screens.skills_install_screen import SkillsInstallScreen

        assert SkillsInstallScreen is not None

    def test_hooks_screen_importable(self) -> None:
        from code_puppy.tui.screens.hooks_screen import HooksScreen

        assert HooksScreen is not None

    def test_scheduler_screen_importable(self) -> None:
        from code_puppy.tui.screens.scheduler_screen import SchedulerScreen

        assert SchedulerScreen is not None

    def test_scheduler_wizard_screen_importable(self) -> None:
        from code_puppy.tui.screens.scheduler_wizard_screen import (
            SchedulerWizardScreen,
        )

        assert SchedulerWizardScreen is not None

    def test_app_handle_skills_command(self) -> None:
        """app.py source should reference SkillsScreen."""
        import inspect

        from code_puppy.tui import app

        source = inspect.getsource(app)
        assert "SkillsScreen" in source

    def test_app_handle_hooks_command(self) -> None:
        """app.py source should reference HooksScreen."""
        import inspect

        from code_puppy.tui import app

        source = inspect.getsource(app)
        assert "HooksScreen" in source

    def test_app_handle_scheduler_command(self) -> None:
        """app.py source should reference SchedulerScreen."""
        import inspect

        from code_puppy.tui import app

        source = inspect.getsource(app)
        assert "SchedulerScreen" in source
