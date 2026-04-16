"""Tests for code_puppy/constants.py.

Validates that centralized resource limits have correct values,
correct types, and maintain their documented invariants.
"""

import pytest

from code_puppy.constants import (
    CONTEXT_MAP_MAX_BATCH_BYTES,
    CONTEXT_MAP_MAX_BATCH_SIZE,
    MAX_CONTEXT_BODY_BYTES,
    MAX_CONTEXT_COUNT,
    MAX_CONTEXT_MAP_PATHS,
    MAX_CONTEXT_MAP_SINGLE_INPUT_BYTES,
    MAX_CONTEXT_MAP_TOTAL_INPUT_BYTES,
    MAX_DIFF_CONTEXT_LINES_DEFAULT,
    MAX_GREP_FILE_SIZE_BYTES,
    MAX_GREP_MATCHES,
    MAX_READ_FILE_TOKENS,
    MAX_TOTAL_CONTEXT_BYTES,
    SUMMARIZATION_ABSOLUTE_PROTECTED_DEFAULT,
    SUMMARIZATION_ABSOLUTE_TRIGGER_DEFAULT,
    SUMMARIZATION_KEEP_FRACTION_DEFAULT,
    SUMMARIZATION_MIN_KEEP_TOKENS,
    SUMMARIZATION_MIN_TRIGGER_TOKENS,
    SUMMARIZATION_TRIGGER_FRACTION_DEFAULT,
)


class TestFileContextLimits:
    """Verify file/context size limits match plandex values."""

    def test_max_context_body_is_25mb(self) -> None:
        assert MAX_CONTEXT_BODY_BYTES == 25 * 1024 * 1024

    def test_max_context_count(self) -> None:
        assert MAX_CONTEXT_COUNT == 1_000

    def test_max_context_map_paths(self) -> None:
        assert MAX_CONTEXT_MAP_PATHS == 3_000

    def test_max_context_map_single_input_is_500kb(self) -> None:
        assert MAX_CONTEXT_MAP_SINGLE_INPUT_BYTES == 500 * 1024

    def test_max_context_map_total_input_is_250mb(self) -> None:
        assert MAX_CONTEXT_MAP_TOTAL_INPUT_BYTES == 250 * 1024 * 1024

    def test_max_total_context_is_1gb(self) -> None:
        assert MAX_TOTAL_CONTEXT_BYTES == 1 * 1024 * 1024 * 1024

    def test_batch_bytes_is_10mb(self) -> None:
        assert CONTEXT_MAP_MAX_BATCH_BYTES == 10 * 1024 * 1024

    def test_batch_size(self) -> None:
        assert CONTEXT_MAP_MAX_BATCH_SIZE == 500


class TestTokenToolLimits:
    """Verify token and tool limits."""

    def test_max_read_file_tokens(self) -> None:
        assert MAX_READ_FILE_TOKENS == 10_000

    def test_max_grep_matches(self) -> None:
        assert MAX_GREP_MATCHES == 50

    def test_max_grep_file_size_is_5mb(self) -> None:
        assert MAX_GREP_FILE_SIZE_BYTES == 5 * 1024 * 1024


class TestDisplayDefaults:
    """Verify display defaults."""

    def test_diff_context_lines(self) -> None:
        assert MAX_DIFF_CONTEXT_LINES_DEFAULT == 3


class TestAllConstantsArePositive:
    """Every limit must be a positive integer."""

    @pytest.mark.parametrize(
        "name,value",
        [
            ("MAX_CONTEXT_BODY_BYTES", MAX_CONTEXT_BODY_BYTES),
            ("MAX_CONTEXT_COUNT", MAX_CONTEXT_COUNT),
            ("MAX_CONTEXT_MAP_PATHS", MAX_CONTEXT_MAP_PATHS),
            ("MAX_CONTEXT_MAP_SINGLE_INPUT_BYTES", MAX_CONTEXT_MAP_SINGLE_INPUT_BYTES),
            ("MAX_CONTEXT_MAP_TOTAL_INPUT_BYTES", MAX_CONTEXT_MAP_TOTAL_INPUT_BYTES),
            ("MAX_TOTAL_CONTEXT_BYTES", MAX_TOTAL_CONTEXT_BYTES),
            ("CONTEXT_MAP_MAX_BATCH_BYTES", CONTEXT_MAP_MAX_BATCH_BYTES),
            ("CONTEXT_MAP_MAX_BATCH_SIZE", CONTEXT_MAP_MAX_BATCH_SIZE),
            ("MAX_READ_FILE_TOKENS", MAX_READ_FILE_TOKENS),
            ("MAX_GREP_MATCHES", MAX_GREP_MATCHES),
            ("MAX_GREP_FILE_SIZE_BYTES", MAX_GREP_FILE_SIZE_BYTES),
            ("MAX_DIFF_CONTEXT_LINES_DEFAULT", MAX_DIFF_CONTEXT_LINES_DEFAULT),
            ("SUMMARIZATION_ABSOLUTE_TRIGGER_DEFAULT", SUMMARIZATION_ABSOLUTE_TRIGGER_DEFAULT),
            ("SUMMARIZATION_ABSOLUTE_PROTECTED_DEFAULT", SUMMARIZATION_ABSOLUTE_PROTECTED_DEFAULT),
            ("SUMMARIZATION_MIN_TRIGGER_TOKENS", SUMMARIZATION_MIN_TRIGGER_TOKENS),
            ("SUMMARIZATION_MIN_KEEP_TOKENS", SUMMARIZATION_MIN_KEEP_TOKENS),
        ],
    )
    def test_positive_int(self, name: str, value: int) -> None:
        assert isinstance(value, int), f"{name} should be int, got {type(value)}"
        assert value > 0, f"{name} should be positive, got {value}"


class TestSizeRelationships:
    """Verify that size relationships between limits are sane."""

    def test_single_input_less_than_total_input(self) -> None:
        assert MAX_CONTEXT_MAP_SINGLE_INPUT_BYTES < MAX_CONTEXT_MAP_TOTAL_INPUT_BYTES

    def test_batch_bytes_less_than_total_context(self) -> None:
        assert CONTEXT_MAP_MAX_BATCH_BYTES < MAX_TOTAL_CONTEXT_BYTES

    def test_body_less_than_total_context(self) -> None:
        assert MAX_CONTEXT_BODY_BYTES < MAX_TOTAL_CONTEXT_BYTES

    def test_total_input_less_than_total_context(self) -> None:
        assert MAX_CONTEXT_MAP_TOTAL_INPUT_BYTES < MAX_TOTAL_CONTEXT_BYTES


class TestSummarizationDefaults:
    """Verify summarization threshold constants."""

    def test_trigger_fraction(self) -> None:
        assert SUMMARIZATION_TRIGGER_FRACTION_DEFAULT == 0.85

    def test_keep_fraction(self) -> None:
        assert SUMMARIZATION_KEEP_FRACTION_DEFAULT == 0.10

    def test_absolute_trigger(self) -> None:
        assert SUMMARIZATION_ABSOLUTE_TRIGGER_DEFAULT == 170_000

    def test_absolute_protected(self) -> None:
        assert SUMMARIZATION_ABSOLUTE_PROTECTED_DEFAULT == 50_000

    def test_min_trigger_tokens(self) -> None:
        assert SUMMARIZATION_MIN_TRIGGER_TOKENS == 1_000

    def test_min_keep_tokens(self) -> None:
        assert SUMMARIZATION_MIN_KEEP_TOKENS == 100

    def test_fractions_are_floats(self) -> None:
        assert isinstance(SUMMARIZATION_TRIGGER_FRACTION_DEFAULT, float)
        assert isinstance(SUMMARIZATION_KEEP_FRACTION_DEFAULT, float)

    def test_fractions_between_0_and_1(self) -> None:
        assert 0.0 < SUMMARIZATION_TRIGGER_FRACTION_DEFAULT <= 1.0
        assert 0.0 < SUMMARIZATION_KEEP_FRACTION_DEFAULT <= 1.0

    def test_trigger_fraction_greater_than_keep(self) -> None:
        """Trigger should fire at a higher threshold than keep."""
        assert SUMMARIZATION_TRIGGER_FRACTION_DEFAULT > SUMMARIZATION_KEEP_FRACTION_DEFAULT

    def test_absolute_trigger_greater_than_protected(self) -> None:
        assert SUMMARIZATION_ABSOLUTE_TRIGGER_DEFAULT > SUMMARIZATION_ABSOLUTE_PROTECTED_DEFAULT

    def test_min_trigger_greater_than_min_keep(self) -> None:
        assert SUMMARIZATION_MIN_TRIGGER_TOKENS > SUMMARIZATION_MIN_KEEP_TOKENS
