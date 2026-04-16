"""Tests for whitespace normalization helpers."""

from code_puppy.utils.whitespace import strip_added_blank_lines


def test_no_change_preserves_content():
    """When orig == upd, returns upd unchanged."""
    content = "line 1\nline 2\nline 3"
    result = strip_added_blank_lines(content, content)
    assert result == content


def test_strips_added_leading_blanks():
    """orig has 0 leading blanks, upd has 3 → result has 0."""
    orig = "line 1\nline 2"
    upd = "\n\n\nline 1\nline 2"
    result = strip_added_blank_lines(orig, upd)
    assert result == "line 1\nline 2"


def test_strips_added_trailing_blanks():
    """orig has 1 trailing blank, upd has 4 → result has 1."""
    orig = "line 1\nline 2\n"
    upd = "line 1\nline 2\n\n\n\n"
    result = strip_added_blank_lines(orig, upd)
    assert result == "line 1\nline 2\n"


def test_preserves_original_leading_blanks():
    """Both have 2 leading blanks → result has 2."""
    orig = "\n\nline 1\nline 2"
    upd = "\n\nline 1\nline 2 modified"
    result = strip_added_blank_lines(orig, upd)
    assert result == "\n\nline 1\nline 2 modified"


def test_strips_both_leading_and_trailing():
    """Covers both leading and trailing blank stripping at once."""
    orig = "line 1\nline 2"
    upd = "\n\nline 1\nline 2\n\n\n"
    result = strip_added_blank_lines(orig, upd)
    assert result == "line 1\nline 2"


def test_preserves_middle_blank_lines():
    """Blank lines in the middle of content are untouched."""
    orig = "line 1\n\n\nline 2"
    upd = "\n\nline 1\n\n\nline 2\n\n"
    result = strip_added_blank_lines(orig, upd)
    # Leading: orig has 0, upd has 2 → strip 2; Trailing: orig has 0, upd has 2 → strip 2
    assert result == "line 1\n\n\nline 2"


def test_empty_upd_returns_empty():
    """Edge case: empty upd returns empty."""
    orig = "line 1\nline 2"
    upd = ""
    result = strip_added_blank_lines(orig, upd)
    assert result == ""


def test_single_line_no_change():
    """No newlines at all - single line content."""
    orig = "hello world"
    upd = "hello modified world"
    result = strip_added_blank_lines(orig, upd)
    assert result == "hello modified world"


def test_empty_orig_treats_as_single_blank_line():
    """When orig is empty, split produces [''] which counts as 1 blank line.

    This matches Go behavior: strings.Split("", "\n") returns []string{""}.
    So leading_orig=1 and trailing_orig=1, meaning upd keeps 1 leading
    and 1 trailing blank line (the 'surplus' beyond orig's single blank).
    """
    orig = ""
    upd = "\n\n\nactual content\n\n"
    result = strip_added_blank_lines(orig, upd)
    # orig has 1 'blank' line (the empty string from split)
    # upd has 3 leading, 2 trailing blanks
    # Result keeps 1 leading (3-2=1) and 1 trailing (2-1=1)
    assert result == "\nactual content\n"


def test_preserves_trailing_when_orig_has_more():
    """If orig has more trailing blanks than upd, upd is preserved as-is."""
    orig = "line 1\n\n\n"
    upd = "line 1\n"
    result = strip_added_blank_lines(orig, upd)
    assert result == "line 1\n"


def test_preserves_leading_when_orig_has_more():
    """If orig has more leading blanks than upd, upd is preserved as-is."""
    orig = "\n\n\nline 1"
    upd = "\nline 1"
    result = strip_added_blank_lines(orig, upd)
    assert result == "\nline 1"
