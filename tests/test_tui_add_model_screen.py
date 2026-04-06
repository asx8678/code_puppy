"""Tests for the AddModelScreen Textual screen.

Covers:
- Module and class imports
- Screen instantiation and inheritance
- Expected key bindings
- Helper module-level functions
- App.py wiring for /add_model
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _binding_keys(screen_cls) -> set[str]:
    """Return the set of key strings declared in a screen's BINDINGS."""
    return {b.key for b in screen_cls.BINDINGS}


# ===========================================================================
# Import / class tests
# ===========================================================================


class TestAddModelScreenImports:
    def test_screen_importable(self) -> None:
        from code_puppy.tui.screens.add_model_screen import AddModelScreen  # noqa: F401

        assert AddModelScreen is not None

    def test_helper_load_registry_importable(self) -> None:
        from code_puppy.tui.screens.add_model_screen import _load_registry  # noqa: F401

        assert _load_registry is not None

    def test_helper_add_model_to_config_importable(self) -> None:
        from code_puppy.tui.screens.add_model_screen import _add_model_to_config  # noqa: F401

        assert _add_model_to_config is not None

    def test_helper_format_provider_details_importable(self) -> None:
        from code_puppy.tui.screens.add_model_screen import (  # noqa: F401
            _format_provider_details,
        )

        assert _format_provider_details is not None

    def test_helper_format_model_details_importable(self) -> None:
        from code_puppy.tui.screens.add_model_screen import (  # noqa: F401
            _format_model_details,
        )

        assert _format_model_details is not None


# ===========================================================================
# Inheritance & instantiation
# ===========================================================================


class TestAddModelScreenClass:
    def test_is_menu_screen(self) -> None:
        from code_puppy.tui.base_screen import MenuScreen
        from code_puppy.tui.screens.add_model_screen import AddModelScreen

        assert issubclass(AddModelScreen, MenuScreen)

    def test_instantiates(self) -> None:
        from code_puppy.tui.screens.add_model_screen import AddModelScreen

        screen = AddModelScreen()
        assert screen is not None

    def test_initial_step_is_providers(self) -> None:
        from code_puppy.tui.screens.add_model_screen import AddModelScreen

        screen = AddModelScreen()
        assert screen._step == "providers"

    def test_initial_provider_is_none(self) -> None:
        from code_puppy.tui.screens.add_model_screen import AddModelScreen

        screen = AddModelScreen()
        assert screen._selected_provider is None

    def test_initial_registry_is_none(self) -> None:
        from code_puppy.tui.screens.add_model_screen import AddModelScreen

        screen = AddModelScreen()
        assert screen._registry is None


# ===========================================================================
# Bindings
# ===========================================================================


class TestAddModelScreenBindings:
    def test_has_escape_binding(self) -> None:
        from code_puppy.tui.screens.add_model_screen import AddModelScreen

        assert "escape" in _binding_keys(AddModelScreen)

    def test_has_enter_binding(self) -> None:
        from code_puppy.tui.screens.add_model_screen import AddModelScreen

        assert "enter" in _binding_keys(AddModelScreen)


# ===========================================================================
# Helper functions
# ===========================================================================


class TestFormatHelpers:
    def test_format_provider_details_includes_name(self) -> None:
        from unittest.mock import MagicMock

        from code_puppy.tui.screens.add_model_screen import _format_provider_details

        provider = MagicMock()
        provider.name = "TestProvider"
        provider.id = "test-provider"
        provider.model_count = 5
        provider.api = "https://api.test.com/v1"
        provider.env = ["TEST_API_KEY"]
        provider.doc = "https://docs.test.com"

        result = _format_provider_details(provider)

        assert "TestProvider" in result
        assert "test-provider" in result
        assert "5" in result
        assert "TEST_API_KEY" in result

    def test_format_provider_details_no_env(self) -> None:
        from unittest.mock import MagicMock

        from code_puppy.tui.screens.add_model_screen import _format_provider_details

        provider = MagicMock()
        provider.name = "Minimal"
        provider.id = "minimal"
        provider.model_count = 1
        provider.api = ""
        provider.env = []
        provider.doc = None

        result = _format_provider_details(provider)
        assert "Minimal" in result

    def test_format_model_details_includes_model_name(self) -> None:
        from unittest.mock import MagicMock

        from code_puppy.tui.screens.add_model_screen import _format_model_details

        model = MagicMock()
        model.name = "gpt-99"
        model.model_id = "gpt-99"
        model.context_length = 128000
        model.max_output = 4096
        model.tool_call = True
        model.reasoning = False
        model.attachment = False
        model.structured_output = True
        model.has_vision = False
        model.cost_input = 0.001
        model.cost_output = 0.002
        model.knowledge = "2025-01"

        provider = MagicMock()
        provider.name = "OpenAI"

        result = _format_model_details(model, provider)

        assert "gpt-99" in result
        assert "128k" in result
        assert "tools" in result
        assert "structured-output" in result
        assert "OpenAI" in result

    def test_format_model_details_no_cost(self) -> None:
        from unittest.mock import MagicMock

        from code_puppy.tui.screens.add_model_screen import _format_model_details

        model = MagicMock()
        model.name = "free-model"
        model.model_id = "free-model"
        model.context_length = 0
        model.max_output = 0
        model.tool_call = False
        model.reasoning = False
        model.attachment = False
        model.structured_output = False
        model.has_vision = False
        model.cost_input = None
        model.cost_output = None
        model.knowledge = None

        provider = MagicMock()
        provider.name = "FreeProvider"

        result = _format_model_details(model, provider)
        assert "free-model" in result


# ===========================================================================
# _load_registry
# ===========================================================================


class TestLoadRegistry:
    @pytest.mark.asyncio
    async def test_load_registry_returns_registry_or_none(self) -> None:
        from code_puppy.tui.screens.add_model_screen import _load_registry

        result = await _load_registry()
        # Either succeeds (ModelsDevRegistry) or returns None gracefully
        assert result is None or hasattr(result, "get_providers")

    @pytest.mark.asyncio
    async def test_load_registry_does_not_raise(self) -> None:
        from code_puppy.tui.screens.add_model_screen import _load_registry

        try:
            await _load_registry()
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"_load_registry raised unexpectedly: {exc}")


# ===========================================================================
# _add_model_to_config safety
# ===========================================================================


class TestAddModelToConfig:
    def test_bad_model_returns_false(self) -> None:
        """Passing None for model/provider should return False, not raise."""
        from code_puppy.tui.screens.add_model_screen import _add_model_to_config

        result = _add_model_to_config(None, None)
        assert result is False


# ===========================================================================
# App.py wiring
# ===========================================================================


class TestAppWiring:
    def test_app_handles_add_model_command(self) -> None:
        """app.py _handle_slash_command references AddModelScreen for /add_model."""
        from pathlib import Path

        source = (
            Path(__file__).parent.parent / "code_puppy" / "tui" / "app.py"
        ).read_text()

        assert "AddModelScreen" in source
        assert "/add_model" in source

    def test_app_imports_add_model_screen_module(self) -> None:
        """The import path used in app.py is correct."""
        from pathlib import Path

        source = (
            Path(__file__).parent.parent / "code_puppy" / "tui" / "app.py"
        ).read_text()

        assert "tui.screens.add_model_screen" in source
