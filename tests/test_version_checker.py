from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import httpx

from code_puppy.version_checker import (
    default_version_mismatch_behavior,
    fetch_latest_version,
    normalize_version,
    versions_are_equal,
)


def test_normalize_version():
    """Test version string normalization."""
    assert normalize_version("v1.2.3") == "1.2.3"
    assert normalize_version("1.2.3") == "1.2.3"
    assert normalize_version("v0.0.78") == "0.0.78"
    assert normalize_version("0.0.78") == "0.0.78"
    assert normalize_version("") == ""
    assert normalize_version(None) is None
    assert normalize_version("vvv1.2.3") == "1.2.3"  # Multiple v's


def test_versions_are_equal():
    """Test version equality comparison."""
    # Same versions with and without v prefix
    assert versions_are_equal("1.2.3", "v1.2.3") is True
    assert versions_are_equal("v1.2.3", "1.2.3") is True
    assert versions_are_equal("v1.2.3", "v1.2.3") is True
    assert versions_are_equal("1.2.3", "1.2.3") is True

    # The specific case from our API
    assert versions_are_equal("0.0.78", "v0.0.78") is True
    assert versions_are_equal("v0.0.78", "0.0.78") is True

    # Different versions
    assert versions_are_equal("1.2.3", "1.2.4") is False
    assert versions_are_equal("v1.2.3", "v1.2.4") is False
    assert versions_are_equal("1.2.3", "v1.2.4") is False

    # Edge cases
    assert versions_are_equal("", "") is True
    assert versions_are_equal(None, None) is True
    assert versions_are_equal("1.2.3", "") is False
    assert versions_are_equal("", "1.2.3") is False


def _fresh_cache(version: str) -> dict:
    """Build a cache dict that looks freshly written."""
    return {
        "version": version,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


class TestFetchLatestVersion:
    """Test fetch_latest_version function."""

    @patch("code_puppy.version_checker._read_cache")
    @patch("code_puppy.version_checker.httpx.get")
    def test_fetch_latest_version_success(self, mock_get, mock_cache):
        """Test successful version fetch from PyPI when cache is empty."""
        mock_cache.return_value = None
        mock_response = MagicMock()
        mock_response.json.return_value = {"info": {"version": "1.2.3"}}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        version = fetch_latest_version("test-package")

        assert version == "1.2.3"
        mock_get.assert_called_once()

    @patch("code_puppy.version_checker._read_cache")
    def test_fetch_latest_version_cache_hit(self, mock_cache):
        """Test that cache hit skips network call."""
        mock_cache.return_value = _fresh_cache("1.2.3")

        version = fetch_latest_version("test-package")

        assert version == "1.2.3"

    @patch("code_puppy.version_checker._read_cache")
    @patch("code_puppy.version_checker.httpx.get")
    def test_fetch_latest_version_http_error(self, mock_get, mock_cache):
        """Test version fetch with HTTP error."""
        mock_cache.return_value = None
        mock_get.side_effect = httpx.HTTPError("Connection failed")

        version = fetch_latest_version("test-package")

        assert version is None

    @patch("code_puppy.version_checker._read_cache")
    @patch("code_puppy.version_checker.httpx.get")
    def test_fetch_latest_version_invalid_json(self, mock_get, mock_cache):
        """Test version fetch with invalid JSON response."""
        mock_cache.return_value = None
        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        version = fetch_latest_version("test-package")

        assert version is None

    @patch("code_puppy.version_checker._read_cache")
    @patch("code_puppy.version_checker.httpx.get")
    def test_fetch_latest_version_missing_info_key(self, mock_get, mock_cache):
        """Test version fetch with missing 'info' key."""
        mock_cache.return_value = None
        mock_response = MagicMock()
        mock_response.json.return_value = {"releases": {}}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        version = fetch_latest_version("test-package")

        assert version is None

    @patch("code_puppy.version_checker._read_cache")
    @patch("code_puppy.version_checker.httpx.get")
    def test_fetch_latest_version_status_error(self, mock_get, mock_cache):
        """Test version fetch with HTTP status error."""
        mock_cache.return_value = None
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=MagicMock(), response=MagicMock()
        )
        mock_get.return_value = mock_response

        version = fetch_latest_version("nonexistent-package")

        assert version is None


class TestDefaultVersionMismatchBehavior:
    """Test default_version_mismatch_behavior function."""

    @patch("code_puppy.version_checker.get_message_bus")
    @patch("code_puppy.version_checker.emit_success")
    @patch("code_puppy.version_checker.emit_warning")
    @patch("code_puppy.version_checker.emit_info")
    @patch("code_puppy.version_checker._read_cache")
    def test_version_mismatch_shows_update_message(
        self, mock_cache, mock_emit_info, mock_emit_warning, mock_emit_success, mock_bus
    ):
        """Test that update message is shown when versions differ."""
        mock_cache.return_value = _fresh_cache("2.0.0")

        default_version_mismatch_behavior("1.0.0")

        # Should emit current version info
        mock_emit_info.assert_any_call("Current version: 1.0.0")
        # Should emit latest version info
        mock_emit_info.assert_any_call("Latest version: 2.0.0")
        # Should emit warning about new version
        mock_emit_warning.assert_called()
        # Should emit success message about updating
        mock_emit_success.assert_called()

    @patch("code_puppy.version_checker.get_message_bus")
    @patch("code_puppy.version_checker.emit_success")
    @patch("code_puppy.version_checker.emit_warning")
    @patch("code_puppy.version_checker.emit_info")
    @patch("code_puppy.version_checker._read_cache")
    def test_version_match_still_shows_current_version(
        self, mock_cache, mock_emit_info, mock_emit_warning, mock_emit_success, mock_bus
    ):
        """Test that current version is still shown when versions match."""
        mock_cache.return_value = _fresh_cache("1.0.0")

        default_version_mismatch_behavior("1.0.0")

        # Should emit current version info
        mock_emit_info.assert_any_call("Current version: 1.0.0")
        # Should NOT emit warning or success when versions match
        mock_emit_warning.assert_not_called()
        mock_emit_success.assert_not_called()

    @patch("code_puppy.version_checker.get_message_bus")
    @patch("code_puppy.version_checker.emit_success")
    @patch("code_puppy.version_checker.emit_warning")
    @patch("code_puppy.version_checker.emit_info")
    @patch("code_puppy.version_checker._read_cache")
    def test_cache_miss_shows_current_version_no_warning(
        self, mock_cache, mock_emit_info, mock_emit_warning, mock_emit_success, mock_bus
    ):
        """Test behavior when cache is empty (no network call, no warning)."""
        mock_cache.return_value = None

        default_version_mismatch_behavior("1.0.0")

        # Should still emit current version info even when cache miss
        mock_emit_info.assert_called_once_with("Current version: 1.0.0")
        # Should NOT emit warning or success when cache miss
        mock_emit_warning.assert_not_called()
        mock_emit_success.assert_not_called()

    @patch("code_puppy.version_checker.get_message_bus")
    @patch("code_puppy.version_checker.emit_success")
    @patch("code_puppy.version_checker.emit_warning")
    @patch("code_puppy.version_checker.emit_info")
    @patch("code_puppy.version_checker._read_cache")
    def test_update_message_content(
        self, mock_cache, mock_emit_info, mock_emit_warning, mock_emit_success, mock_bus
    ):
        """Test the exact content of update messages."""
        mock_cache.return_value = _fresh_cache("2.5.0")

        default_version_mismatch_behavior("2.0.0")

        # Check warning contains new version info
        warning_calls = [str(call) for call in mock_emit_warning.call_args_list]
        assert any("2.5.0" in str(call) for call in warning_calls)

    @patch("code_puppy.version_checker.get_message_bus")
    @patch("code_puppy.version_checker.emit_success")
    @patch("code_puppy.version_checker.emit_warning")
    @patch("code_puppy.version_checker.emit_info")
    @patch("code_puppy.version_checker._read_cache")
    def test_none_current_version_handled_gracefully(
        self, mock_cache, mock_emit_info, mock_emit_warning, mock_emit_success, mock_bus
    ):
        """Test that None current_version is handled gracefully."""
        mock_cache.return_value = _fresh_cache("1.0.0")

        # This should not raise an exception
        default_version_mismatch_behavior(None)

        # Should emit warning about unknown version
        mock_emit_warning.assert_any_call(
            "Could not detect current version, using fallback"
        )
        # Should use fallback version in info message
        mock_emit_info.assert_any_call("Current version: 0.0.0-unknown")
