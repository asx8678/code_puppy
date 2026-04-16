"""Tests for code_puppy/tui/screens/agent_screen.py.

Verifies:
- AgentScreen can be imported and instantiated
- AgentScreen is a MenuScreen subclass
- Correct key bindings are present
- ModelPinScreen can be imported and instantiated
"""



# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


def test_agent_screen_importable() -> None:
    """AgentScreen can be imported without errors."""
    from code_puppy.tui.screens.agent_screen import AgentScreen  # noqa: F401

    assert AgentScreen is not None


def test_agent_screen_is_menu_screen() -> None:
    """AgentScreen inherits from MenuScreen."""
    from code_puppy.tui.base_screen import MenuScreen
    from code_puppy.tui.screens.agent_screen import AgentScreen

    assert issubclass(AgentScreen, MenuScreen)


def test_agent_screen_instantiates() -> None:
    """AgentScreen can be instantiated without arguments."""
    from code_puppy.tui.screens.agent_screen import AgentScreen

    screen = AgentScreen()
    assert screen is not None


# ---------------------------------------------------------------------------
# Binding tests
# ---------------------------------------------------------------------------


def _binding_keys(screen_cls) -> set[str]:
    """Return set of key strings declared in a screen's BINDINGS."""
    return {b.key for b in screen_cls.BINDINGS}


def test_agent_screen_has_enter_binding() -> None:
    from code_puppy.tui.screens.agent_screen import AgentScreen

    assert "enter" in _binding_keys(AgentScreen)


def test_agent_screen_has_p_binding() -> None:
    from code_puppy.tui.screens.agent_screen import AgentScreen

    assert "p" in _binding_keys(AgentScreen)


def test_agent_screen_has_c_binding() -> None:
    from code_puppy.tui.screens.agent_screen import AgentScreen

    assert "c" in _binding_keys(AgentScreen)


def test_agent_screen_has_d_binding() -> None:
    from code_puppy.tui.screens.agent_screen import AgentScreen

    assert "d" in _binding_keys(AgentScreen)


def test_agent_screen_has_escape_binding() -> None:
    """Inherited from MenuScreen."""
    from code_puppy.tui.screens.agent_screen import AgentScreen

    assert "escape" in _binding_keys(AgentScreen)


# ---------------------------------------------------------------------------
# ModelPinScreen tests
# ---------------------------------------------------------------------------


def test_model_pin_screen_importable() -> None:
    from code_puppy.tui.screens.model_pin_screen import ModelPinScreen  # noqa: F401

    assert ModelPinScreen is not None


def test_model_pin_screen_is_menu_screen() -> None:
    from code_puppy.tui.base_screen import MenuScreen
    from code_puppy.tui.screens.model_pin_screen import ModelPinScreen

    assert issubclass(ModelPinScreen, MenuScreen)


def test_model_pin_screen_instantiates() -> None:
    from code_puppy.tui.screens.model_pin_screen import ModelPinScreen

    screen = ModelPinScreen(
        agent_name="test-agent",
        model_names=["gpt-4o", "claude-3-5-sonnet"],
        current_pinned=None,
    )
    assert screen._agent_name == "test-agent"
    assert "gpt-4o" in screen._model_names


def test_model_pin_screen_has_enter_binding() -> None:
    from code_puppy.tui.screens.model_pin_screen import ModelPinScreen

    assert "enter" in _binding_keys(ModelPinScreen)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_get_agent_entries_returns_list() -> None:
    """_get_agent_entries should return a non-empty list of 3-tuples."""
    from code_puppy.tui.screens.agent_screen import _get_agent_entries

    entries = _get_agent_entries()
    assert isinstance(entries, list)
    assert len(entries) > 0
    for entry in entries:
        assert len(entry) == 3, "Each entry must be (name, display_name, description)"
        name, display_name, description = entry
        assert isinstance(name, str) and name
        assert isinstance(display_name, str)
        assert isinstance(description, str)


def test_get_agent_entries_sorted() -> None:
    """_get_agent_entries should return entries sorted alphabetically by name."""
    from code_puppy.tui.screens.agent_screen import _get_agent_entries

    entries = _get_agent_entries()
    names = [e[0].lower() for e in entries]
    assert names == sorted(names), "Agent entries should be sorted by name"


def test_get_pinned_model_returns_none_or_str() -> None:
    """_get_pinned_model returns None or a str for any agent name."""
    from code_puppy.tui.screens.agent_screen import (
        _get_agent_entries,
        _get_pinned_model,
    )

    entries = _get_agent_entries()
    if entries:
        name, _, _ = entries[0]
        result = _get_pinned_model(name)
        assert result is None or isinstance(result, str)
