"""Tests for MCPScreen and MCPFormScreen Textual screens.

Verifies:
- Both screens can be imported and instantiated
- Both screens inherit from MenuScreen
- Expected key bindings are present
- Helper functions work correctly (data loading, validation)
- Constants and data structures are defined
"""

import json

import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _binding_keys(screen_cls) -> set[str]:
    """Return the set of key strings declared in a screen's BINDINGS."""
    return {b.key for b in screen_cls.BINDINGS}


# ===========================================================================
# mcp_screen.py
# ===========================================================================


class TestMCPScreen:
    def test_importable(self) -> None:
        from code_puppy.tui.screens.mcp_screen import MCPScreen  # noqa: F401

        assert MCPScreen is not None

    def test_is_menu_screen(self) -> None:
        from code_puppy.tui.base_screen import MenuScreen
        from code_puppy.tui.screens.mcp_screen import MCPScreen

        assert issubclass(MCPScreen, MenuScreen)

    def test_instantiates(self) -> None:
        from code_puppy.tui.screens.mcp_screen import MCPScreen

        screen = MCPScreen()
        assert screen is not None

    def test_has_escape_binding(self) -> None:
        from code_puppy.tui.screens.mcp_screen import MCPScreen

        assert "escape" in _binding_keys(MCPScreen)

    def test_has_enter_binding(self) -> None:
        from code_puppy.tui.screens.mcp_screen import MCPScreen

        assert "enter" in _binding_keys(MCPScreen)

    def test_has_i_binding(self) -> None:
        from code_puppy.tui.screens.mcp_screen import MCPScreen

        assert "i" in _binding_keys(MCPScreen)

    def test_category_icons_defined(self) -> None:
        from code_puppy.tui.screens.mcp_screen import CATEGORY_ICONS

        assert isinstance(CATEGORY_ICONS, dict)
        assert len(CATEGORY_ICONS) > 0
        # Spot-check a few expected categories
        assert "Code" in CATEGORY_ICONS
        assert "Database" in CATEGORY_ICONS

    def test_type_icons_defined(self) -> None:
        from code_puppy.tui.screens.mcp_screen import TYPE_ICONS

        assert "stdio" in TYPE_ICONS
        assert "http" in TYPE_ICONS
        assert "sse" in TYPE_ICONS

    def test_load_catalog_servers_returns_list(self) -> None:
        from code_puppy.tui.screens.mcp_screen import _load_catalog_servers

        result = _load_catalog_servers()
        assert isinstance(result, list)

    def test_get_server_by_id_unknown_returns_none(self) -> None:
        from code_puppy.tui.screens.mcp_screen import _get_server_by_id

        result = _get_server_by_id("this-id-definitely-does-not-exist-xyz")
        assert result is None

    def test_get_server_by_id_known_server(self) -> None:
        """If the catalog loads, a known server should be findable."""
        from code_puppy.tui.screens.mcp_screen import (
            _get_server_by_id,
            _load_catalog_servers,
        )

        servers = _load_catalog_servers()
        if servers:
            first = servers[0]
            result = _get_server_by_id(first.id)
            assert result is not None
            assert result.id == first.id

    def test_catalog_servers_have_required_attrs(self) -> None:
        from code_puppy.tui.screens.mcp_screen import _load_catalog_servers

        servers = _load_catalog_servers()
        for server in servers[:5]:  # Only check first 5 for speed
            assert hasattr(server, "id")
            assert hasattr(server, "display_name")
            assert hasattr(server, "description")
            assert hasattr(server, "type")
            assert hasattr(server, "category")
            assert hasattr(server, "tags")

    def test_get_mcp_manager_does_not_raise(self) -> None:
        """_get_mcp_manager should return something or None, never raise."""
        from code_puppy.tui.screens.mcp_screen import _get_mcp_manager

        # Should not raise
        result = _get_mcp_manager()
        # Result can be None or a manager object — just ensure no exception


# ===========================================================================
# mcp_form_screen.py
# ===========================================================================


class TestMCPFormScreen:
    def test_importable(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import MCPFormScreen  # noqa: F401

        assert MCPFormScreen is not None

    def test_is_menu_screen(self) -> None:
        from code_puppy.tui.base_screen import MenuScreen
        from code_puppy.tui.screens.mcp_form_screen import MCPFormScreen

        assert issubclass(MCPFormScreen, MenuScreen)

    def test_instantiates_default(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import MCPFormScreen

        screen = MCPFormScreen()
        assert screen is not None

    def test_instantiates_edit_mode(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import MCPFormScreen

        screen = MCPFormScreen(
            edit_mode=True,
            existing_name="my-server",
            existing_type="http",
            existing_config={"url": "http://localhost:8080"},
        )
        assert screen is not None
        assert screen._edit_mode is True
        assert screen._existing_name == "my-server"
        assert screen._initial_type == "http"

    def test_has_escape_binding(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import MCPFormScreen

        assert "escape" in _binding_keys(MCPFormScreen)

    def test_has_ctrl_s_binding(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import MCPFormScreen

        assert "ctrl+s" in _binding_keys(MCPFormScreen)

    def test_has_ctrl_n_binding(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import MCPFormScreen

        assert "ctrl+n" in _binding_keys(MCPFormScreen)

    def test_server_types_defined(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import SERVER_TYPES

        assert "stdio" in SERVER_TYPES
        assert "http" in SERVER_TYPES
        assert "sse" in SERVER_TYPES

    def test_server_type_descriptions_defined(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import SERVER_TYPE_DESCRIPTIONS

        for t in ("stdio", "http", "sse"):
            assert t in SERVER_TYPE_DESCRIPTIONS
            assert len(SERVER_TYPE_DESCRIPTIONS[t]) > 0

    def test_examples_are_valid_json(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import _EXAMPLES

        for t, example in _EXAMPLES.items():
            data = json.loads(example)
            assert isinstance(data, dict), f"Example for '{t}' is not a JSON object"

    def test_validate_name_empty(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import _validate_name

        assert _validate_name("") is not None
        assert _validate_name("   ") is not None

    def test_validate_name_valid(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import _validate_name

        assert _validate_name("my-server") is None
        assert _validate_name("server_123") is None
        assert _validate_name("abc") is None

    def test_validate_name_invalid_chars(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import _validate_name

        result = _validate_name("hello world")
        assert result is not None  # spaces not allowed

    def test_validate_name_too_long(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import _validate_name

        long_name = "a" * 65
        result = _validate_name(long_name)
        assert result is not None

    def test_validate_json_valid_stdio(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import _validate_json

        valid = json.dumps({"command": "npx", "args": ["-y", "some-package"]})
        assert _validate_json(valid, "stdio") is None

    def test_validate_json_missing_command(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import _validate_json

        invalid = json.dumps({"args": ["something"]})
        result = _validate_json(invalid, "stdio")
        assert result is not None
        assert "command" in result.lower()

    def test_validate_json_valid_http(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import _validate_json

        valid = json.dumps({"url": "http://localhost:8080"})
        assert _validate_json(valid, "http") is None

    def test_validate_json_missing_url(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import _validate_json

        invalid = json.dumps({"headers": {}})
        result = _validate_json(invalid, "http")
        assert result is not None
        assert "url" in result.lower()

    def test_validate_json_valid_sse(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import _validate_json

        valid = json.dumps({"url": "http://localhost:8080/sse"})
        assert _validate_json(valid, "sse") is None

    def test_validate_json_invalid_syntax(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import _validate_json

        result = _validate_json("{not valid json}", "stdio")
        assert result is not None
        assert "json" in result.lower()

    def test_examples_pass_validation(self) -> None:
        """All built-in examples should pass their own validation."""
        from code_puppy.tui.screens.mcp_form_screen import (
            SERVER_TYPES,
            _EXAMPLES,
            _validate_json,
        )

        for t in SERVER_TYPES:
            example = _EXAMPLES.get(t, "{}")
            err = _validate_json(example, t)
            assert err is None, f"Example for '{t}' failed validation: {err}"


# ===========================================================================
# app.py wiring
# ===========================================================================


class TestAppWiring:
    def test_mcp_screen_importable_from_screens(self) -> None:
        from code_puppy.tui.screens.mcp_screen import MCPScreen

        assert MCPScreen is not None

    def test_mcp_form_screen_importable_from_screens(self) -> None:
        from code_puppy.tui.screens.mcp_form_screen import MCPFormScreen

        assert MCPFormScreen is not None

    def test_app_has_install_helper(self) -> None:
        from code_puppy.tui.app import CodePuppyApp

        assert hasattr(CodePuppyApp, "_install_mcp_server")
        assert callable(CodePuppyApp._install_mcp_server)

    def test_app_has_install_done_helper(self) -> None:
        from code_puppy.tui.app import CodePuppyApp

        assert hasattr(CodePuppyApp, "_on_mcp_install_done")
        assert callable(CodePuppyApp._on_mcp_install_done)
