"""Tests for code_puppy.plugins.fast_puppy.register_callbacks.

bd-50: Rust integration removed - tests simplified.
"""

from code_puppy.plugins.fast_puppy.register_callbacks import _on_custom_command

# ---------------------------------------------------------------------------
# _on_custom_command()
# ---------------------------------------------------------------------------


class TestOnCustomCommand:
    """_on_custom_command routes /fast_puppy commands correctly."""

    def test_returns_none_for_unrelated_command(self) -> None:
        result = _on_custom_command("/something_else", "something_else")
        assert result is None

    def test_returns_status_for_fast_puppy_command(self) -> None:
        result = _on_custom_command("/fast_puppy", "fast_puppy")
        assert result is not None
        assert "Fast Puppy Status:" in result
        assert "Native acceleration layer removed" in result

    # bd-86: Tests removed - _core_bridge and native_backend modules deleted.
    # These tests depended on deleted modules. Fast puppy plugin simplified.


# bd-86: TestOnStartup class removed - native_backend module deleted.
# Tests depended on deleted NativeBackend class. _on_startup() simplified.
