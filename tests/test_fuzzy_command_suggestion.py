"""Tests for fuzzy 'did you mean?' suggestions on unknown slash commands."""

from unittest.mock import patch

from code_puppy.command_line.command_handler import handle_command


def _run_unknown_command(cmd: str) -> list[str]:
    """Run an unknown command and return all warning message strings emitted."""
    warnings: list[str] = []

    def capture_warning(msg):
        warnings.append(str(msg))

    with patch("code_puppy.messaging.emit_warning", side_effect=capture_warning):
        with patch("code_puppy.messaging.emit_info"):
            handle_command(cmd)

    return warnings


def test_hepl_suggests_help():
    """/hepl is a close misspelling — should suggest /help."""
    warnings = _run_unknown_command("/hepl")
    assert warnings, "Expected a warning for unknown command"
    combined = " ".join(warnings)
    assert "Did you mean" in combined, f"Expected suggestion, got: {combined}"
    assert "/help" in combined, f"Expected /help suggestion, got: {combined}"


def test_totally_wrong_command_shows_no_suggestions():
    """/xyzzy is totally unrelated — should show the generic help message."""
    warnings = _run_unknown_command("/xyzzy")
    assert warnings, "Expected a warning for unknown command"
    combined = " ".join(warnings)
    assert "Type /help for options" in combined, (
        f"Expected fallback message, got: {combined}"
    )
    assert "Did you mean" not in combined, (
        f"Should not suggest anything for /xyzzy, got: {combined}"
    )


def test_modle_suggests_model():
    """/modle is a close misspelling — should suggest /model."""
    warnings = _run_unknown_command("/modle")
    assert warnings, "Expected a warning for unknown command"
    combined = " ".join(warnings)
    assert "Did you mean" in combined, f"Expected suggestion, got: {combined}"
    assert "/model" in combined, f"Expected /model suggestion, got: {combined}"
