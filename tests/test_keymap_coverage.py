"""Test coverage for code_puppy/keymap.py.

This module tests keyboard shortcut configuration including:
- Cancel agent key retrieval and validation
- Character code mapping
- Display name formatting
- Windows/uvx detection integration
"""

from unittest.mock import patch

import pytest

from code_puppy.keymap import (
    DEFAULT_CANCEL_AGENT_KEY,
    KEY_CODES,
    VALID_CANCEL_KEYS,
    KeymapError,
    cancel_agent_uses_signal,
    get_cancel_agent_char_code,
    get_cancel_agent_display_name,
    get_cancel_agent_key,
    validate_cancel_agent_key,
)


class TestKeymapConstants:
    """Test keymap constants are properly defined."""

    @pytest.mark.parametrize("key", ["ctrl+c", "ctrl+k", "ctrl+q", "escape"])
    def test_key_codes_contains_ctrl_keys(self, key):
        """KEY_CODES should contain all ctrl+letter combinations."""
        assert key in KEY_CODES

    @pytest.mark.parametrize(
        "key,code",
        [("ctrl+c", "\x03"), ("ctrl+k", "\x0b"), ("escape", "\x1b")],
    )
    def test_key_codes_values_are_control_chars(self, key, code):
        """KEY_CODES values should be control characters."""
        assert KEY_CODES[key] == code

    def test_valid_cancel_keys_is_subset_of_key_codes(self):
        """All valid cancel keys should exist in KEY_CODES."""
        for key in VALID_CANCEL_KEYS:
            assert key in KEY_CODES

    def test_default_cancel_agent_key_is_valid(self):
        """Default cancel key should be in valid keys."""
        assert DEFAULT_CANCEL_AGENT_KEY in VALID_CANCEL_KEYS


class TestKeymapError:
    """Test KeymapError exception."""

    def test_keymap_error_is_exception(self):
        """KeymapError should be an Exception subclass."""
        assert issubclass(KeymapError, Exception)

    def test_keymap_error_with_message_and_raisable(self):
        """KeymapError should preserve its message and be raisable."""
        error = KeymapError("Invalid key configuration")
        assert str(error) == "Invalid key configuration"
        with pytest.raises(KeymapError, match="test error"):
            raise KeymapError("test error")


class TestGetCancelAgentKey:
    """Test get_cancel_agent_key function."""

    @patch("code_puppy.uvx_detection.should_use_alternate_cancel_key")
    @patch("code_puppy.config.get_value")
    def test_returns_ctrl_k_on_windows_uvx(self, mock_get_value, mock_should_use_alt):
        """Should return ctrl+k when Windows+uvx detection is true."""
        mock_should_use_alt.return_value = True
        mock_get_value.return_value = "ctrl+c"  # Config says ctrl+c

        result = get_cancel_agent_key()

        assert result == "ctrl+k"
        # get_value should NOT be called when uvx detection triggers
        mock_get_value.assert_not_called()

    @pytest.mark.parametrize(
        "config_value,expected",
        [
            (None, DEFAULT_CANCEL_AGENT_KEY),
            ("   ", DEFAULT_CANCEL_AGENT_KEY),  # Whitespace only
            ("  CTRL+K  ", "ctrl+k"),  # Stripped and lowercased
        ],
    )
    @patch("code_puppy.uvx_detection.should_use_alternate_cancel_key")
    @patch("code_puppy.config.get_value")
    def test_returns_normalized_config_or_default(
        self, mock_get_value, mock_should_use_alt, config_value, expected
    ):
        """Should normalize the configured key, falling back to default."""
        mock_should_use_alt.return_value = False
        mock_get_value.return_value = config_value

        result = get_cancel_agent_key()

        assert result == expected


class TestValidateCancelAgentKey:
    """Test validate_cancel_agent_key function."""

    @patch("code_puppy.keymap.get_cancel_agent_key")
    def test_valid_key_does_not_raise(self, mock_get_key):
        """Should not raise for valid keys."""
        for key in VALID_CANCEL_KEYS:
            mock_get_key.return_value = key
            # Should not raise
            validate_cancel_agent_key()

    @patch("code_puppy.keymap.get_cancel_agent_key")
    def test_invalid_key_raises_keymap_error(self, mock_get_key):
        """Should raise KeymapError naming the bad key and valid options."""
        mock_get_key.return_value = "ctrl+z"  # Not in VALID_CANCEL_KEYS

        with pytest.raises(KeymapError) as exc_info:
            validate_cancel_agent_key()

        error_msg = str(exc_info.value)
        assert "ctrl+z" in error_msg
        assert "Invalid cancel_agent_key" in error_msg
        # Error message should list valid key options
        assert "ctrl+c" in error_msg or "ctrl+k" in error_msg


class TestCancelAgentUsesSignal:
    """Test cancel_agent_uses_signal function."""

    @pytest.mark.parametrize(
        "key,expected",
        [("ctrl+c", True), ("ctrl+k", False), ("ctrl+q", False)],
    )
    @patch("code_puppy.keymap.get_cancel_agent_key")
    def test_returns_true_only_for_ctrl_c(self, mock_get_key, key, expected):
        """Should return True only when cancel key is ctrl+c."""
        mock_get_key.return_value = key

        assert cancel_agent_uses_signal() is expected


class TestGetCancelAgentCharCode:
    """Test get_cancel_agent_char_code function."""

    @pytest.mark.parametrize(
        "key,code",
        [("ctrl+c", "\x03"), ("ctrl+k", "\x0b")],
    )
    @patch("code_puppy.keymap.get_cancel_agent_key")
    def test_returns_correct_char_code(self, mock_get_key, key, code):
        """Should return correct character code for known keys."""
        mock_get_key.return_value = key

        assert get_cancel_agent_char_code() == code

    @patch("code_puppy.keymap.get_cancel_agent_key")
    def test_raises_for_unknown_key(self, mock_get_key):
        """Should raise KeymapError for unknown key."""
        mock_get_key.return_value = "unknown_key"

        with pytest.raises(KeymapError) as exc_info:
            get_cancel_agent_char_code()

        assert "unknown_key" in str(exc_info.value)
        assert "no character code mapping" in str(exc_info.value)


class TestGetCancelAgentDisplayName:
    """Test get_cancel_agent_display_name function."""

    @pytest.mark.parametrize(
        "key,expected",
        [
            ("ctrl+c", "Ctrl+C"),
            ("ctrl+k", "Ctrl+K"),
            ("escape", "ESCAPE"),
            ("somekey", "SOMEKEY"),  # Non-ctrl keys uppercased
        ],
    )
    @patch("code_puppy.keymap.get_cancel_agent_key")
    def test_formats_display_name(self, mock_get_key, key, expected):
        """Should format ctrl keys as Ctrl+X and others uppercased."""
        mock_get_key.return_value = key

        assert get_cancel_agent_display_name() == expected
