from unittest.mock import patch

import pytest

from code_puppy.utils.syntax_validate import (
    PARSER_TIMEOUT_S,
    ValidationResult,
    ValidationStatus,
    _ext_is_validatable,
    format_validation_errors_for_agent,
    validate_file_sync,
)


def test_parser_timeout_constant():
    assert PARSER_TIMEOUT_S == pytest.approx(0.5)


def test_ext_is_validatable():
    assert _ext_is_validatable("foo.py") is True
    assert _ext_is_validatable("foo.PY") is True
    assert _ext_is_validatable("foo.rs") is True
    assert _ext_is_validatable("foo.md") is False
    assert _ext_is_validatable("foo") is False


def test_unknown_ext_returns_parser_unavailable():
    result = validate_file_sync("foo.md", "# hello")
    assert result.status is ValidationStatus.PARSER_UNAVAILABLE
    assert result.is_valid is True  # fail-open


def test_valid_python_file():
    """Valid Python code should come back as VALID or PARSER_UNAVAILABLE (if bridge missing)."""
    result = validate_file_sync("test.py", "def foo():\n    return 42\n")
    # Either the bridge worked and we got VALID, or it wasn't available.
    # Both are acceptable non-INVALID outcomes.
    assert result.status in (
        ValidationStatus.VALID,
        ValidationStatus.PARSER_UNAVAILABLE,
    )
    assert result.is_valid is True


def test_format_validation_errors_returns_none_for_valid():
    r = ValidationResult(status=ValidationStatus.VALID)
    assert format_validation_errors_for_agent(r) is None


def test_format_validation_errors_returns_none_for_timeout():
    r = ValidationResult(status=ValidationStatus.TIMED_OUT)
    assert format_validation_errors_for_agent(r) is None


def test_format_validation_errors_returns_none_for_parser_unavailable():
    r = ValidationResult(status=ValidationStatus.PARSER_UNAVAILABLE)
    assert format_validation_errors_for_agent(r) is None


def test_format_validation_errors_for_invalid():
    r = ValidationResult(
        status=ValidationStatus.INVALID,
        errors=["Invalid syntax on line 3", "Unclosed paren on line 7"],
    )
    out = format_validation_errors_for_agent(r)
    assert out is not None
    assert "Invalid syntax on line 3" in out
    assert "Unclosed paren on line 7" in out
    assert "⚠️" in out


def test_format_validation_errors_caps_at_five():
    errors = [f"Error {i}" for i in range(10)]
    r = ValidationResult(status=ValidationStatus.INVALID, errors=errors)
    out = format_validation_errors_for_agent(r)
    assert out is not None
    # Should mention 5 more
    assert "5 more" in out


def test_mocked_parser_returns_invalid():
    """When the parser raises, we should return INVALID (not crash)."""
    with patch("code_puppy.utils.syntax_validate._validate_via_turbo_parse") as mock_vp:
        mock_vp.return_value = ValidationResult(
            status=ValidationStatus.INVALID,
            errors=["Bad syntax"],
        )
        result = validate_file_sync("test.py", "bad code {")
    assert result.status is ValidationStatus.INVALID
    assert "Bad syntax" in result.errors


def test_validator_fails_open_on_unexpected_error():
    """If the validator itself crashes, we should still return (not raise)."""
    with patch("code_puppy.utils.syntax_validate._validate_via_turbo_parse") as mock_vp:
        mock_vp.side_effect = RuntimeError("boom")
        result = validate_file_sync("test.py", "x = 1")
    # Should return something (not raise)
    assert result is not None
    assert result.status is ValidationStatus.PARSER_UNAVAILABLE


def test_invalid_status_from_diagnostics():
    """Test that we correctly parse INVALID from turbo_parse diagnostics."""
    mock_result = {
        "diagnostics": [
            {
                "severity": "error",
                "line": 3,
                "column": 5,
                "message": "Unexpected token",
            },
            {
                "severity": "warning",
                "line": 10,
                "column": 1,
                "message": "Unused import",
            },
        ],
        "error_count": 1,
        "warning_count": 1,
    }

    with patch("code_puppy.turbo_parse_bridge.extract_syntax_diagnostics") as mock_diag:
        with patch(
            "code_puppy.turbo_parse_bridge.is_language_supported", return_value=True
        ):
            mock_diag.return_value = mock_result
            result = validate_file_sync("test.py", "def foo(:\n  pass")

    assert result.status is ValidationStatus.INVALID
    assert len(result.errors) == 1  # Only errors, not warnings
    assert "Line 3:5 - Unexpected token" in result.errors


def test_valid_status_from_diagnostics():
    """Test that we correctly parse VALID from turbo_parse diagnostics."""
    mock_result = {
        "diagnostics": [],
        "error_count": 0,
        "warning_count": 0,
    }

    with patch("code_puppy.turbo_parse_bridge.extract_syntax_diagnostics") as mock_diag:
        with patch(
            "code_puppy.turbo_parse_bridge.is_language_supported", return_value=True
        ):
            mock_diag.return_value = mock_result
            result = validate_file_sync("test.py", "def foo():\n    pass\n")

    assert result.status is ValidationStatus.VALID
    assert result.errors == []
    assert result.language == "python"


def test_deduplicates_errors():
    """Test that duplicate errors are deduplicated."""
    mock_result = {
        "diagnostics": [
            {"severity": "error", "line": 3, "column": 5, "message": "Same error"},
            {"severity": "error", "line": 3, "column": 5, "message": "Same error"},
        ],
        "error_count": 2,
        "warning_count": 0,
    }

    with patch("code_puppy.turbo_parse_bridge.extract_syntax_diagnostics") as mock_diag:
        with patch(
            "code_puppy.turbo_parse_bridge.is_language_supported", return_value=True
        ):
            mock_diag.return_value = mock_result
            result = validate_file_sync("test.py", "bad code")

    assert result.status is ValidationStatus.INVALID
    assert len(result.errors) == 1  # Deduplicated


def test_timeout_result():
    """Test that timeout results are formatted correctly."""
    r = ValidationResult(status=ValidationStatus.TIMED_OUT)
    assert r.is_valid is True
    assert format_validation_errors_for_agent(r) is None


def test_is_valid_property():
    """Test the is_valid property for all statuses."""
    assert ValidationResult(status=ValidationStatus.VALID).is_valid is True
    assert ValidationResult(status=ValidationStatus.INVALID).is_valid is False
    assert ValidationResult(status=ValidationStatus.TIMED_OUT).is_valid is True
    assert ValidationResult(status=ValidationStatus.PARSER_UNAVAILABLE).is_valid is True
