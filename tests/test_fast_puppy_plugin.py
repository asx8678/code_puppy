"""Tests for code_puppy.plugins.fast_puppy.register_callbacks.

bd-50: Rust integration removed - tests simplified.
"""

from code_puppy.plugins.fast_puppy.register_callbacks import _on_custom_command

# ---------------------------------------------------------------------------
# _on_custom_command()
# ---------------------------------------------------------------------------


class TestOnCustomCommand:
    """_on_custom_command handles /fast_puppy command."""

    def test_returns_none_for_unrelated_command(self) -> None:
        result = _on_custom_command("/something_else", "something_else")
        assert result is None

    def test_returns_removal_message_for_fast_puppy(self) -> None:
        result = _on_custom_command("/fast_puppy", "fast_puppy")
        assert result is not None
        assert "removed" in result.lower()
