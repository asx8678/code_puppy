"""Regression tests for bd-42: Rust-to-Elixir migration.

This module provides comprehensive regression coverage for the Phase 4 migration,
where 6 Rust modules were removed and replaced with Elixir equivalents:
- content_prep → Text.ContentPrep
- path_classify → FileOps.PathClassifier
- line_numbers → Text.LineNumbers
- fuzzy_match → Text.FuzzyMatch
- replace_engine → Text.ReplaceEngine
- unified_diff → Text.Diff

The remaining Rust crate (message_core) should still work.
All edit operations should work with Python fallback.

-bd-42: Regression test suite
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure code_puppy is in path
code_puppy_path = Path(__file__).parent.parent
if str(code_puppy_path) not in sys.path:
    sys.path.insert(0, str(code_puppy_path))

from code_puppy._edit_bridge import (  # noqa: E402
    fuzzy_match_window,
    replace_in_content,
    unified_diff,
)
from code_puppy.native_backend import NativeBackend  # noqa: E402


@pytest.fixture(autouse=True)
def reset_backend_state():
    """Reset NativeBackend state between tests to prevent pollution."""
    original_preference = NativeBackend._backend_preference
    original_enabled = NativeBackend._capability_enabled.copy()
    original_last_source = NativeBackend._last_source.copy()
    yield
    NativeBackend._backend_preference = original_preference
    NativeBackend._capability_enabled = original_enabled
    NativeBackend._last_source = original_last_source


# =============================================================================
# Python Fallback Path Tests
# =============================================================================


class TestPythonFallbackPaths:
    """Verify edit operations work without Rust edit modules."""

    def test_fuzzy_match_window_basic(self) -> None:
        """fuzzy_match_window Python fallback works for basic case."""
        haystack = [
            "def hello():",
            "    return True",
            "",
            "def world():",
            "    return False",
        ]
        span, score = fuzzy_match_window(haystack, "def hello():\n    return True")
        assert span is not None
        assert span == (0, 2)
        assert score >= 0.95

    def test_replace_in_content_basic(self) -> None:
        """replace_in_content Python fallback works for basic case."""
        result = replace_in_content("hello world", [("hello", "goodbye")])
        assert result["success"] is True
        assert result["modified"] == "goodbye world"

    def test_unified_diff_basic(self) -> None:
        """unified_diff Python fallback works for basic case."""
        diff = unified_diff("hello\n", "world\n")
        assert "hello" in diff
        assert "world" in diff
        assert "---" in diff
        assert "+++" in diff


# =============================================================================
# NativeBackend EDIT_OPS Tests
# =============================================================================


class TestNativeBackendEditOps:
    """Verify NativeBackend properly routes EDIT_OPS capability."""

    def test_edit_ops_capability_registered(self) -> None:
        """EDIT_OPS capability should be registered in NativeBackend."""
        status = NativeBackend.get_status()
        assert "edit_ops" in status

    def test_edit_ops_routes_correctly(self) -> None:
        """EDIT_OPS routes to elixir (if available) or python fallback."""
        routing = NativeBackend.get_capability_routing("edit_ops")
        assert routing["will_use"] in ("elixir", "python", "python_fallback")

    def test_profile_elixir_first_has_edit_ops(self) -> None:
        """elixir_first profile should have edit_ops capability."""
        NativeBackend.set_backend_preference("elixir_first")
        status = NativeBackend.get_status()
        assert status["edit_ops"].active is True

    def test_profile_rust_first_has_edit_ops(self) -> None:
        """rust_first profile should have edit_ops capability."""
        NativeBackend.set_backend_preference("rust_first")
        status = NativeBackend.get_status()
        assert status["edit_ops"].active is True

    def test_profile_python_only_has_edit_ops(self) -> None:
        """python_only profile should have edit_ops capability."""
        NativeBackend.set_backend_preference("python_only")
        status = NativeBackend.get_status()
        assert status["edit_ops"].active is True


# =============================================================================
# Profile Switching Tests
# =============================================================================


class TestProfileSwitching:
    """Verify backend profile switching works correctly."""

    def test_all_profiles_switch_without_error(self) -> None:
        """All profiles should switch without raising exceptions."""
        for profile in ["elixir_first", "rust_first", "python_only"]:
            NativeBackend.set_backend_preference(profile)
            assert NativeBackend.get_backend_preference() == profile

    def test_message_core_stays_rust(self) -> None:
        """Message core capability should still route through Rust."""
        from code_puppy._core_bridge import RUST_AVAILABLE

        if not RUST_AVAILABLE:
            pytest.skip("Rust not built — can't verify Rust routing")
        routing = NativeBackend.get_capability_routing("message_core")
        assert routing["will_use"] == "rust"


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Edge cases: UTF-8, empty inputs, large content, no-match."""

    def test_utf8_content(self) -> None:
        """UTF-8 content should be handled correctly."""
        result = replace_in_content("café naïve résumé", [("café", "coffee")])
        assert result["success"] is True
        assert "coffee" in result["modified"]

    def test_empty_inputs(self) -> None:
        """Empty inputs should be handled gracefully."""
        result = replace_in_content("", [])
        assert result["success"] is True

    def test_large_content_fuzzy_match(self) -> None:
        """Large content fuzzy match should work efficiently."""
        large_content = ["line " + str(i) for i in range(10000)]
        span, score = fuzzy_match_window(large_content, "line 5000")
        assert span is not None
        assert span == (5000, 5001)
        assert score >= 0.99

    def test_no_match_returns_none(self) -> None:
        """No-match case should return None span and 0 score."""
        span, score = fuzzy_match_window(["hello"], "completely_different_text_xyzabc")
        assert span is None
        assert score == 0.0

    def test_binary_content_diff(self) -> None:
        """Binary-like content should be handled in diff."""
        diff = unified_diff("hello\x00world", "hello\x00earth")
        assert len(diff) > 0
        assert isinstance(diff, str)


# =============================================================================
# Rust message_core Unchanged Tests
# =============================================================================


class TestRustMessageCore:
    """Verify Rust message_core is unaffected by migration."""

    def test_rust_available(self) -> None:
        """Rust should be available for message_core."""
        from code_puppy._core_bridge import RUST_AVAILABLE

        # Rust may or may not be built, but we test that the bridge loads
        assert isinstance(RUST_AVAILABLE, bool)

    def test_hashline_functions_work(self) -> None:
        """Hashline functions should work if Rust is available."""
        from code_puppy._core_bridge import RUST_AVAILABLE

        if not RUST_AVAILABLE:
            pytest.skip("Rust not built")
        from _code_puppy_core import (
            compute_line_hash,
            format_hashlines,
            strip_hashline_prefixes,
        )

        h = compute_line_hash(1, "test line")
        assert isinstance(h, str)
        formatted = format_hashlines("line1\nline2\nline3", 1)
        stripped = strip_hashline_prefixes(formatted)
        assert "line1" in stripped


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests verifying end-to-end functionality."""

    def test_edit_sequence(self) -> None:
        """Full edit sequence: find, replace, diff."""
        # Step 1: Find content
        haystack = ["def foo():", "    pass", ""]
        span, score = fuzzy_match_window(haystack, "def foo():\n    pass")
        assert span is not None

        # Step 2: Replace content
        result = replace_in_content("\n".join(haystack), [("def foo():", "def bar():")])
        assert result["success"]
        assert "def bar():" in result["modified"]

        # Step 3: Generate diff
        diff = unified_diff("\n".join(haystack), result["modified"])
        assert len(diff) > 0
