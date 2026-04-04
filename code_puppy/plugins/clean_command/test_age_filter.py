"""Tests for the clean command age filter module."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from code_puppy.plugins.clean_command._age_filter import (
    _human_age,
    _is_older_than,
    _parse_args,
    _parse_duration,
)


class TestParseDuration:
    """Tests for _parse_duration function."""

    @pytest.mark.parametrize(
        "input_str,expected",
        [
            ("7d", 7 * 86400),
            ("30d", 30 * 86400),
            ("24h", 24 * 3600),
            ("1h", 3600),
            ("1w", 7 * 86400),
            ("2w", 14 * 86400),
            ("12m", 12 * 60),
            ("30m", 30 * 60),
            ("30s", 30),
            ("1s", 1),
            # Test with whitespace
            ("  7d  ", 7 * 86400),
            (" 24h", 24 * 3600),
            # Test uppercase (should be converted to lowercase)
            ("7D", 7 * 86400),
            ("24H", 24 * 3600),
            ("1W", 7 * 86400),
            ("12M", 12 * 60),
            ("30S", 30),
        ],
    )
    def test_valid_inputs(self, input_str, expected):
        """Test valid duration strings."""
        assert _parse_duration(input_str) == expected

    @pytest.mark.parametrize(
        "input_str",
        [
            "abc",
            "",
            "7",  # missing unit
            "d",  # missing number
            "7x",  # invalid unit
            "-7d",  # negative number
            "7.5d",  # decimal not supported
        ],
    )
    def test_invalid_inputs(self, input_str):
        """Test invalid duration strings raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            _parse_duration(input_str)
        assert "Invalid duration format" in str(exc_info.value)

    def test_zero_duration(self):
        """Test zero duration - edge case."""
        assert _parse_duration("0s") == 0
        assert _parse_duration("0d") == 0
        assert _parse_duration("0h") == 0


class TestHumanAge:
    """Tests for _human_age function."""

    @pytest.mark.parametrize(
        "seconds,expected",
        [
            # Seconds
            (0, "0s"),
            (1, "1s"),
            (30, "30s"),
            (59, "59s"),
            # Minutes
            (60, "1m"),
            (120, "2m"),
            (3599, "59m"),
            # Hours
            (3600, "1h"),
            (7200, "2h"),
            (86399, "23h"),
            # Days
            (86400, "1d"),
            (172800, "2d"),
            (604799, "6d"),
            # Weeks
            (604800, "1w"),
            (1209600, "2w"),
            (2419200, "4w"),
        ],
    )
    def test_human_age(self, seconds, expected):
        """Test human-readable age formatting."""
        assert _human_age(seconds) == expected


class TestIsOlderThan:
    """Tests for _is_older_than function."""

    def test_file_exists_and_old(self, tmp_path):
        """Test file that exists and is older than threshold."""
        test_file = tmp_path / "old_file.txt"
        test_file.write_text("content")

        # Set mtime to 10 seconds ago
        old_time = time.time() - 10
        test_file.touch()
        import os

        os.utime(test_file, (old_time, old_time))

        # File is older than 5 seconds
        assert _is_older_than(test_file, 5) is True

    def test_file_exists_and_new(self, tmp_path):
        """Test file that exists but is newer than threshold."""
        test_file = tmp_path / "new_file.txt"
        test_file.write_text("content")

        # File is newer than 1 hour (created just now)
        assert _is_older_than(test_file, 3600) is False

    def test_file_missing(self, tmp_path):
        """Test file that does not exist."""
        missing_file = tmp_path / "missing.txt"

        # Should return False for missing files
        assert _is_older_than(missing_file, 5) is False

    def test_zero_threshold(self, tmp_path):
        """Test edge case with zero threshold."""
        test_file = tmp_path / "any_file.txt"
        test_file.write_text("content")

        # Even a brand new file is "older than 0 seconds"
        assert _is_older_than(test_file, 0) is True

    def test_oserror_handling(self, tmp_path):
        """Test that OSError during stat is handled gracefully."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        # Mock path.stat() to raise OSError
        with patch.object(Path, "stat", side_effect=OSError("Permission denied")):
            assert _is_older_than(test_file, 5) is False


class TestParseArgs:
    """Tests for _parse_args function."""

    def test_parse_args_with_older_than_before_subcommand(self):
        """Test --older-than before subcommand (e.g., --older-than 7d all)."""
        parts = ["--older-than", "7d", "all"]
        args, dry_run, max_age = _parse_args(parts)

        assert args == ["all"]
        assert dry_run is False
        assert max_age == 7 * 86400

    def test_parse_args_with_older_than_after_subcommand(self):
        """Test --older-than after subcommand (e.g., sessions --older-than 7d)."""
        parts = ["sessions", "--older-than", "24h"]
        args, dry_run, max_age = _parse_args(parts)

        assert args == ["sessions"]
        assert dry_run is False
        assert max_age == 24 * 3600

    def test_parse_args_with_dry_run(self):
        """Test --dry-run flag."""
        parts = ["--dry-run", "sessions"]
        args, dry_run, max_age = _parse_args(parts)

        assert args == ["sessions"]
        assert dry_run is True
        assert max_age is None

    def test_parse_args_with_both_flags(self):
        """Test both --dry-run and --older-than."""
        parts = ["--dry-run", "--older-than", "1w", "cache"]
        args, dry_run, max_age = _parse_args(parts)

        assert args == ["cache"]
        assert dry_run is True
        assert max_age == 7 * 86400

    def test_parse_args_missing_duration(self):
        """Test error when --older-than is missing its duration argument."""
        parts = ["--older-than"]

        with pytest.raises(ValueError) as exc_info:
            _parse_args(parts)
        assert "--older-than requires a duration" in str(exc_info.value)

    def test_parse_args_invalid_duration(self):
        """Test error when --older-than has an invalid duration."""
        parts = ["--older-than", "abc", "all"]

        with pytest.raises(ValueError) as exc_info:
            _parse_args(parts)
        assert "Invalid duration format" in str(exc_info.value)

    def test_parse_args_no_flags(self):
        """Test parsing with no flags."""
        parts = ["status"]
        args, dry_run, max_age = _parse_args(parts)

        assert args == ["status"]
        assert dry_run is False
        assert max_age is None

    def test_parse_args_empty(self):
        """Test parsing empty args."""
        parts = []
        args, dry_run, max_age = _parse_args(parts)

        assert args == []
        assert dry_run is False
        assert max_age is None

    def test_parse_args_different_units(self):
        """Test parsing with different duration units."""
        test_cases = [
            (["--older-than", "30s", "logs"], 30),
            (["--older-than", "12m", "logs"], 12 * 60),
            (["--older-than", "24h", "logs"], 24 * 3600),
            (["--older-than", "7d", "logs"], 7 * 86400),
            (["--older-than", "1w", "logs"], 7 * 86400),
        ]

        for parts, expected in test_cases:
            args, dry_run, max_age = _parse_args(parts)
            assert max_age == expected, f"Failed for {parts}"

    def test_parse_args_zero_duration(self):
        """Test edge case with zero duration."""
        parts = ["--older-than", "0s", "all"]
        args, dry_run, max_age = _parse_args(parts)

        assert max_age == 0
