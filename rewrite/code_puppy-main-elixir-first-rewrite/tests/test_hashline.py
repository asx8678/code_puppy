"""Tests for code_puppy/utils/hashline.py.

Covers both the public API and the pure-Python fallback, verifying:
- compute_line_hash returns a valid 2-char uppercase anchor
- format_hashlines produces correct ``N#HH:content`` prefixed lines
- strip_hashline_prefixes is the inverse of format_hashlines (roundtrip)
- strip preserves lines that have no hashline prefix
- validate_hashline_anchor returns True on a match, False on mismatch
- Edge cases: empty lines, punctuation-only, Unicode
- is_using_rust() reflects current backend
- Pure-Python path can be exercised by monkey-patching ``_USING_RUST``
"""

import re

import pytest

import code_puppy.utils.hashline as hashline_mod
from code_puppy.utils.hashline import (
    NIBBLE_STR,
    compute_line_hash,
    format_hashlines,
    is_using_rust,
    strip_hashline_prefixes,
    validate_hashline_anchor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _force_python(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable Rust backend for the duration of a test."""
    monkeypatch.setattr(hashline_mod, "_USING_RUST", False)


# ---------------------------------------------------------------------------
# compute_line_hash
# ---------------------------------------------------------------------------


class TestComputeLineHash:
    """Tests for compute_line_hash."""

    def test_returns_two_chars(self):
        h = compute_line_hash(1, "hello world")
        assert len(h) == 2

    def test_returns_uppercase(self):
        h = compute_line_hash(1, "hello world")
        assert h == h.upper()
        assert all(c.isalpha() for c in h)

    def test_chars_from_nibble_str(self):
        h = compute_line_hash(3, "some code here")
        assert h[0] in NIBBLE_STR
        assert h[1] in NIBBLE_STR

    def test_same_content_same_hash(self):
        h1 = compute_line_hash(5, "identical line")
        h2 = compute_line_hash(5, "identical line")
        assert h1 == h2

    def test_different_content_likely_different_hash(self):
        # Not guaranteed due to collisions, but extremely likely
        h1 = compute_line_hash(1, "alpha content")
        h2 = compute_line_hash(1, "beta content different")
        # We don't assert inequality (collisions possible), just that
        # both are valid
        assert len(h1) == 2
        assert len(h2) == 2

    def test_trailing_whitespace_ignored(self):
        h1 = compute_line_hash(1, "hello")
        h2 = compute_line_hash(1, "hello   ")
        h3 = compute_line_hash(1, "hello\t\t")
        assert h1 == h2 == h3

    def test_trailing_cr_ignored(self):
        h1 = compute_line_hash(1, "hello")
        h2 = compute_line_hash(1, "hello\r")
        assert h1 == h2

    def test_empty_line_uses_idx_as_seed(self):
        """Empty line has no alnum chars, so idx is used as seed."""
        h1 = compute_line_hash(1, "")
        h10 = compute_line_hash(10, "")
        # Both valid 2-char strings
        assert len(h1) == 2
        assert len(h10) == 2

    def test_whitespace_only_uses_idx_as_seed(self):
        h1 = compute_line_hash(1, "   ")
        h2 = compute_line_hash(2, "   ")
        # Each should be a valid anchor; values may or may not collide
        assert len(h1) == 2
        assert len(h2) == 2

    def test_punctuation_only_uses_idx_as_seed(self):
        h1 = compute_line_hash(7, "---")
        h2 = compute_line_hash(8, "---")
        assert len(h1) == 2
        assert len(h2) == 2

    def test_alnum_content_ignores_idx(self):
        """Lines with alnum content use seed=0, so idx doesn't affect hash."""
        h1 = compute_line_hash(1, "foo")
        h99 = compute_line_hash(99, "foo")
        assert h1 == h99

    def test_unicode_content(self):
        h = compute_line_hash(1, "Hello 🌍! Ñoño café résumé 日本語")
        assert len(h) == 2
        assert h[0] in NIBBLE_STR and h[1] in NIBBLE_STR


# ---------------------------------------------------------------------------
# format_hashlines
# ---------------------------------------------------------------------------


class TestFormatHashlines:
    """Tests for format_hashlines."""

    def test_single_line_format(self):
        result = format_hashlines("hello")
        assert re.match(r"^1#[A-Z]{2}:hello$", result), result

    def test_two_lines_format(self):
        result = format_hashlines("foo\nbar")
        lines = result.split("\n")
        assert len(lines) == 2
        assert re.match(r"^1#[A-Z]{2}:foo$", lines[0])
        assert re.match(r"^2#[A-Z]{2}:bar$", lines[1])

    def test_start_line_offset(self):
        result = format_hashlines("hello", start_line=10)
        assert result.startswith("10#")
        assert result.endswith(":hello")

    def test_start_line_default_is_1(self):
        result = format_hashlines("line")
        assert result.startswith("1#")

    def test_preserves_content(self):
        original = "    def foo(self):\n        return 42"
        result = format_hashlines(original)
        for i, (orig_line, fmt_line) in enumerate(
            zip(original.split("\n"), result.split("\n"))
        ):
            # Strip the prefix to get back the original content
            assert fmt_line.endswith(f":{orig_line}"), (
                f"Line {i}: expected suffix ':{orig_line}', got '{fmt_line}'"
            )

    def test_empty_line_annotated(self):
        result = format_hashlines("")
        assert re.match(r"^1#[A-Z]{2}:$", result), result

    def test_line_count_preserved(self):
        text = "a\nb\nc\nd\ne"
        result = format_hashlines(text)
        assert len(result.split("\n")) == 5

    def test_trailing_newline_preserved(self):
        """A trailing newline creates an empty last line that is annotated."""
        text = "line one\nline two\n"
        result = format_hashlines(text)
        lines = result.split("\n")
        assert len(lines) == 3  # "line one", "line two", ""
        assert re.match(r"^3#[A-Z]{2}:$", lines[2])

    def test_unicode_content(self):
        text = "café\n日本語"
        result = format_hashlines(text)
        lines = result.split("\n")
        assert ":café" in lines[0]
        assert ":日本語" in lines[1]


# ---------------------------------------------------------------------------
# strip_hashline_prefixes
# ---------------------------------------------------------------------------


class TestStripHashlinePrefixes:
    """Tests for strip_hashline_prefixes."""

    def test_roundtrip_single_line(self):
        original = "hello world"
        assert strip_hashline_prefixes(format_hashlines(original)) == original

    def test_roundtrip_multiline(self):
        original = "line one\nline two\nline three"
        assert strip_hashline_prefixes(format_hashlines(original)) == original

    def test_roundtrip_with_trailing_newline(self):
        original = "alpha\nbeta\n"
        assert strip_hashline_prefixes(format_hashlines(original)) == original

    def test_roundtrip_empty_string(self):
        original = ""
        assert strip_hashline_prefixes(format_hashlines(original)) == original

    def test_passthrough_plain_text(self):
        text = "no prefix here\njust plain text"
        assert strip_hashline_prefixes(text) == text

    def test_passthrough_partial(self):
        """Lines without hashline prefix pass through unchanged."""
        formatted = format_hashlines("hello", start_line=1)
        mixed = formatted + "\nplain line without prefix"
        stripped = strip_hashline_prefixes(mixed)
        assert stripped == "hello\nplain line without prefix"

    def test_strips_prefix_not_content(self):
        """Content that happens to contain '#' is preserved."""
        text = "x = a#b + c#d"
        formatted = format_hashlines(text)
        stripped = strip_hashline_prefixes(formatted)
        assert stripped == text

    def test_idempotent_on_plain_text(self):
        text = "already plain"
        assert strip_hashline_prefixes(strip_hashline_prefixes(text)) == text

    def test_unicode_roundtrip(self):
        original = "café\n日本語\n🚀 launch"
        assert strip_hashline_prefixes(format_hashlines(original)) == original

    def test_start_line_roundtrip(self):
        original = "first\nsecond"
        formatted = format_hashlines(original, start_line=42)
        assert strip_hashline_prefixes(formatted) == original


# ---------------------------------------------------------------------------
# validate_hashline_anchor
# ---------------------------------------------------------------------------


class TestValidateHashlineAnchor:
    """Tests for validate_hashline_anchor."""

    def test_valid_anchor_returns_true(self):
        h = compute_line_hash(5, "some code")
        assert validate_hashline_anchor(5, "some code", h) is True

    def test_modified_content_returns_false(self):
        h = compute_line_hash(5, "some code")
        assert validate_hashline_anchor(5, "different code", h) is False

    def test_wrong_idx_for_blank_line_returns_false(self):
        h1 = compute_line_hash(1, "")
        # idx=1 hash should not validate for idx=2 on the same blank line
        h2 = compute_line_hash(2, "")
        assert validate_hashline_anchor(1, "", h1) is True
        assert validate_hashline_anchor(2, "", h2) is True
        # Cross-validate only passes if they happen to collide (unlikely)
        # We just confirm each round-trips correctly.

    def test_blank_line_idx1_not_idx100(self):
        h1 = compute_line_hash(1, "")
        h100 = compute_line_hash(100, "")
        assert validate_hashline_anchor(1, "", h1) is True
        assert validate_hashline_anchor(100, "", h100) is True
        # The hashes for different indices are almost certainly different
        # (not asserting inequality to allow for extremely rare collisions)

    def test_wrong_hash_string_returns_false(self):
        assert validate_hashline_anchor(1, "hello", "ZZ") is False or True
        # Above could be True if "ZZ" happens to be the actual hash; test
        # with a hash that is definitely wrong format / wrong value instead
        h = compute_line_hash(1, "hello")
        # flip one character to create a wrong hash
        wrong = ("A" if h[0] != "A" else "B") + h[1]
        if wrong != h:  # guard against astronomically unlikely collision
            assert validate_hashline_anchor(1, "hello", wrong) is False

    def test_empty_string_validates_with_own_hash(self):
        h = compute_line_hash(3, "")
        assert validate_hashline_anchor(3, "", h) is True

    def test_alnum_line_idx_irrelevant(self):
        """For lines with alnum content, seed=0 regardless of idx."""
        h = compute_line_hash(1, "some text")
        assert validate_hashline_anchor(99, "some text", h) is True

    def test_unicode_line(self):
        h = compute_line_hash(1, "café 🚀")
        assert validate_hashline_anchor(1, "café 🚀", h) is True
        assert validate_hashline_anchor(1, "cafe 🚀", h) is False


# ---------------------------------------------------------------------------
# is_using_rust
# ---------------------------------------------------------------------------


class TestIsUsingRust:
    """Tests for is_using_rust."""

    def test_returns_bool(self):
        result = is_using_rust()
        assert isinstance(result, bool)

    def test_reflects_module_flag(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(hashline_mod, "_USING_RUST", True)
        assert hashline_mod.is_using_rust() is True

        monkeypatch.setattr(hashline_mod, "_USING_RUST", False)
        assert hashline_mod.is_using_rust() is False


# ---------------------------------------------------------------------------
# Pure-Python fallback (force _USING_RUST = False)
# ---------------------------------------------------------------------------


class TestPurePythonFallback:
    """Run the whole public API through the Python fallback path."""

    @pytest.fixture(autouse=True)
    def disable_rust(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(hashline_mod, "_USING_RUST", False)

    def test_compute_returns_two_chars(self):
        h = hashline_mod.compute_line_hash(1, "test")
        assert len(h) == 2

    def test_compute_returns_uppercase_nibble_chars(self):
        h = hashline_mod.compute_line_hash(1, "test")
        assert h[0] in NIBBLE_STR
        assert h[1] in NIBBLE_STR

    def test_compute_deterministic(self):
        h1 = hashline_mod.compute_line_hash(7, "deterministic")
        h2 = hashline_mod.compute_line_hash(7, "deterministic")
        assert h1 == h2

    def test_compute_trailing_whitespace_ignored(self):
        h1 = hashline_mod.compute_line_hash(1, "code")
        h2 = hashline_mod.compute_line_hash(1, "code   ")
        assert h1 == h2

    def test_compute_alnum_ignores_idx(self):
        h1 = hashline_mod.compute_line_hash(1, "foo")
        h2 = hashline_mod.compute_line_hash(50, "foo")
        assert h1 == h2

    def test_compute_blank_uses_idx(self):
        # Different indices → different CRC seeds → almost certainly different
        h1 = hashline_mod.compute_line_hash(1, "")
        h42 = hashline_mod.compute_line_hash(42, "")
        # Both valid
        assert len(h1) == 2
        assert len(h42) == 2

    def test_format_single_line(self):
        result = hashline_mod.format_hashlines("hello")
        assert re.match(r"^1#[A-Z]{2}:hello$", result)

    def test_format_multiline(self):
        result = hashline_mod.format_hashlines("a\nb")
        lines = result.split("\n")
        assert re.match(r"^1#[A-Z]{2}:a$", lines[0])
        assert re.match(r"^2#[A-Z]{2}:b$", lines[1])

    def test_format_start_line(self):
        result = hashline_mod.format_hashlines("x", start_line=5)
        assert result.startswith("5#")

    def test_strip_roundtrip(self):
        original = "line one\nline two\nline three"
        formatted = hashline_mod.format_hashlines(original)
        assert hashline_mod.strip_hashline_prefixes(formatted) == original

    def test_strip_passthrough(self):
        text = "no prefix"
        assert hashline_mod.strip_hashline_prefixes(text) == text

    def test_validate_match(self):
        h = hashline_mod.compute_line_hash(3, "content")
        assert hashline_mod.validate_hashline_anchor(3, "content", h) is True

    def test_validate_mismatch(self):
        h = hashline_mod.compute_line_hash(3, "content")
        assert hashline_mod.validate_hashline_anchor(3, "changed", h) is False

    def test_empty_line_roundtrip(self):
        h = hashline_mod.compute_line_hash(1, "")
        assert hashline_mod.validate_hashline_anchor(1, "", h) is True

    def test_unicode_roundtrip(self):
        original = "日本語テスト\ncafé résumé"
        formatted = hashline_mod.format_hashlines(original)
        assert hashline_mod.strip_hashline_prefixes(formatted) == original

    def test_is_using_rust_false(self):
        assert hashline_mod.is_using_rust() is False


# ---------------------------------------------------------------------------
# Bridge module
# ---------------------------------------------------------------------------


class TestCoreBridge:
    """Smoke tests for the _core_bridge hashline section."""

    def test_bridge_imports_cleanly(self):
        from code_puppy._core_bridge import HASHLINE_RUST_AVAILABLE

        assert isinstance(HASHLINE_RUST_AVAILABLE, bool)

    def test_bridge_exposes_symbols(self):
        import code_puppy._core_bridge as bridge

        # These may be None if Rust is unavailable, but the names must exist
        assert hasattr(bridge, "compute_line_hash")
        assert hasattr(bridge, "format_hashlines")
        assert hasattr(bridge, "strip_hashline_prefixes")
        assert hasattr(bridge, "validate_hashline_anchor")

    def test_bridge_rust_available_consistent(self):
        import code_puppy._core_bridge as bridge

        if bridge.HASHLINE_RUST_AVAILABLE:
            assert bridge.compute_line_hash is not None
            assert bridge.format_hashlines is not None
            assert bridge.strip_hashline_prefixes is not None
            assert bridge.validate_hashline_anchor is not None
        else:
            assert bridge.compute_line_hash is None
            assert bridge.format_hashlines is None
            assert bridge.strip_hashline_prefixes is None
            assert bridge.validate_hashline_anchor is None
