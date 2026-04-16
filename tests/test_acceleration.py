"""Tests for the acceleration module (bd-13-fix).

Tests for get_turbo_parse_status semantics and PYTHON_ONLY behavior.
"""

from unittest.mock import patch

import pytest

from code_puppy.acceleration import (
    get_turbo_parse_status,
    get_backend_summary,
    is_rust_enabled,
)
from code_puppy.native_backend import BackendPreference, NativeBackend


@pytest.fixture(autouse=True)
def reset_backend_state():
    """Reset backend state after each test."""
    original_preference = NativeBackend._backend_preference
    original_enabled = NativeBackend._capability_enabled.copy()
    yield
    NativeBackend._backend_preference = original_preference
    NativeBackend._capability_enabled = original_enabled


class TestGetTurboParseStatusSemantics:
    """Tests for get_turbo_parse_status semantics (bd-13-fix).
    
    These tests verify that:
    - installed means turbo_parse Rust backend is available
    - enabled/active are consistent with turbo_parse use
    - The status is turbo_parse-specific, not generic parse routing
    """

    def test_installed_means_rust_backend_available(self):
        """Test that 'installed' means turbo_parse Rust backend is available."""
        # bd-13-fix-semantics: Mock Elixir unavailable so test is environment-independent
        # bd-13-partial-fix: Include parse_file entrypoint to simulate full turbo_parse availability
        with patch.object(NativeBackend, "_is_elixir_available", return_value=False):
            with patch.object(
                NativeBackend,
                "_get_turbo_parse",
                return_value={"available": True, "parse_file": lambda _p, _lang: {"tree": {}}},
            ):
                with patch.object(
                    NativeBackend,
                    "parse_health_check",
                    return_value={
                        "available": True,
                        "version": "1.0.0",
                        "languages": ["python"],
                        "backend": "turbo_parse",
                    },
                ):
                    with patch.object(
                        NativeBackend,
                        "parse_stats",
                        return_value={"total_parses": 10, "backend": "turbo_parse"},
                    ):
                        status = get_turbo_parse_status()

                        assert status["installed"] is True
                        assert status["backend_type"] == "turbo_parse"
                        # When Elixir is unavailable and parse_file available, turbo_parse selected
                        assert status["will_use"] == "turbo_parse"
                        assert status["parse_backend"] == "turbo_parse"

    def test_installed_false_when_turbo_not_available(self):
        """Test that 'installed' is False when turbo_parse is not available."""
        with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": False}):
            status = get_turbo_parse_status()
            
            assert status["installed"] is False
            assert status["backend_type"] == "turbo_parse"
            assert status["will_use"] == "disabled"

    def test_disabled_in_python_only_mode(self):
        """Test that enabled=False and will_use='disabled' in PYTHON_ONLY mode."""
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": True}):
                status = get_turbo_parse_status()
                
                assert status["enabled"] is False
                assert status["active"] is False
                assert status["will_use"] == "disabled"
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_enabled_when_parse_active_and_turbo_available(self):
        """Test enabled/active when parse capability is enabled and turbo available (Elixir unavailable)."""
        # bd-13-fix-semantics: Mock Elixir unavailable so turbo_parse is selected
        # bd-13-partial-fix: Include parse_file entrypoint to simulate full turbo_parse availability
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)

            with patch.object(NativeBackend, "_is_elixir_available", return_value=False):
                with patch.object(
                    NativeBackend,
                    "_get_turbo_parse",
                    return_value={"available": True, "parse_file": lambda _p, _lang: {"tree": {}}},
                ):
                    with patch.object(
                        NativeBackend,
                        "parse_health_check",
                        return_value={
                            "available": True,
                            "version": "1.0.0",
                            "languages": ["python"],
                            "cache_available": True,
                            "backend": "turbo_parse",
                        },
                    ):
                        with patch.object(
                            NativeBackend,
                            "parse_stats",
                            return_value={"total_parses": 10, "backend": "turbo_parse"},
                        ):
                            status = get_turbo_parse_status()

                            assert status["enabled"] is True
                            assert (
                                status["active"] is True
                            )  # turbo_parse IS selected since Elixir unavailable
                            assert status["installed"] is True
                            assert status["will_use"] == "turbo_parse"
                            assert status["parse_backend"] == "turbo_parse"
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_not_active_when_parse_disabled(self):
        """Test that active=False when parse capability is disabled."""
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)
            NativeBackend.disable_capability(NativeBackend.Capabilities.PARSE)
            
            with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": True}):
                status = get_turbo_parse_status()
                
                assert status["enabled"] is False
                assert status["active"] is False
                assert status["will_use"] == "disabled"
                assert status["parse_backend"] == "disabled"
        finally:
            NativeBackend.set_backend_preference(original_pref)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)

    def test_not_active_when_elixir_available_in_elixir_first(self):
        """Test active=False when Elixir is available in ELIXIR_FIRST mode (turbo_parse not selected).
        
        bd-13-fix-semantics: active should only be True when turbo_parse IS the selected backend,
        not just when it's available. In ELIXIR_FIRST mode with Elixir available, Elixir is selected.
        """
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.ELIXIR_FIRST)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            # bd-13-fix-semantics: Mock Elixir AVAILABLE - this means turbo_parse won't be selected
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": True}):
                    status = get_turbo_parse_status()
                    
                    # turbo_parse is installed and enabled as a candidate, but NOT selected
                    assert status["installed"] is True
                    assert status["enabled"] is True  # Allowed as candidate
                    assert status["active"] is False  # But NOT selected - Elixir is
                    assert status["will_use"] == "disabled"  # turbo_parse specifically disabled
                    assert status["parse_backend"] == "elixir"  # The actual selected backend
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_not_active_in_partial_build_parse_source_only(self):
        """Test active=False in partial turbo_parse build where parse_source exists but parse_file missing.

        bd-13-partial-fix-regression: When turbo_parse has available=True (parse_source exists)
        but parse_file entrypoint is missing, get_turbo_parse_status() should NOT report
        active=True / will_use="turbo_parse". This is a conservative, entrypoint-aware status.

        Repro condition: BackendPreference.RUST_FIRST, Elixir available, turbo_parse partial build
        where parse_source exists but parse_file is missing. Runtime parse_file() correctly uses
        Elixir, but status should also reflect that turbo_parse is not the active backend.
        """
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.RUST_FIRST)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)

            # Mock partial turbo_parse: available=True (parse_source exists) but parse_file=None
            with patch.object(NativeBackend, "_is_elixir_available", return_value=True):
                with patch.object(
                    NativeBackend,
                    "_get_turbo_parse",
                    return_value={
                        "available": True,  # True because parse_source exists
                        "parse_file": None,  # But parse_file is missing!
                        "parse_source": lambda _s, _lang: {"tree": {}},  # parse_source exists
                    },
                ):
                    with patch.object(
                        NativeBackend,
                        "parse_health_check",
                        return_value={
                            "available": True,
                            "version": "1.0.0",
                            "languages": ["python"],
                        },
                    ):
                        with patch.object(
                            NativeBackend,
                            "parse_stats",
                            return_value={
                                "total_parses": 10,
                                "backend": "turbo_parse",
                            },
                        ):
                            status = get_turbo_parse_status()

                            # turbo_parse Rust backend is technically available
                            assert status["installed"] is True
                            # Enabled as a candidate (parse enabled, not PYTHON_ONLY)
                            assert status["enabled"] is True
                            # BUT: active should be False because parse_file entrypoint is missing
                            # and RUST_FIRST + Elixir available means Elixir is selected
                            assert (
                                status["active"] is False
                            ), "active should be False when parse_file entrypoint is missing"
                            # will_use should be "disabled" for turbo_parse specifically
                            assert (
                                status["will_use"] == "disabled"
                            ), "will_use should be 'disabled' when parse_file is missing"
                            # parse_backend should show Elixir as the actual selected backend
                            assert (
                                status["parse_backend"] == "elixir"
                            ), "parse_backend should be 'elixir' when turbo missing parse_file"
        finally:
            NativeBackend.set_backend_preference(original_pref)

    def test_python_only_no_native_backends_parse_executes(self):
        """Test parse operations execute Python fallback in PYTHON_ONLY with no native backends.
        
        bd-13-fix-regression: When PARSE capability is enabled, PYTHON_ONLY mode should
        still allow parse operations to execute their Python fallback paths, not return
        early with 'Parse capability not active' error.
        
        This verifies the semantic distinction:
        - is_enabled(): User has enabled the capability -> allow execution attempt
        - is_active(): Native backend is available -> for status reporting only
        """
        original_pref = NativeBackend.get_backend_preference()
        try:
            NativeBackend.set_backend_preference(BackendPreference.PYTHON_ONLY)
            NativeBackend.enable_capability(NativeBackend.Capabilities.PARSE)
            
            # Mock NO native backends available (the regression scenario)
            with patch.object(NativeBackend, "_is_elixir_available", return_value=False):
                with patch.object(NativeBackend, "_get_turbo_parse", return_value={"available": False}):
                    from code_puppy.native_backend import parse_source, extract_symbols
                    
                    # These should execute Python fallback, not return early with capability error
                    result = parse_source("def hello(): pass", "python")
                    # Python fallback returns error about no backend, NOT capability disabled
                    assert result.get("error") != "Parse capability disabled"
                    
                    # extract_symbols should return empty list via Python fallback
                    symbols = extract_symbols("def hello(): pass", "python")
                    assert symbols == []  # Python fallback returns empty list
        finally:
            NativeBackend.set_backend_preference(original_pref)


class TestGetBackendSummary:
    """Tests for get_backend_summary."""

    def test_returns_summary_dict(self):
        """Test that get_backend_summary returns a dict with expected keys."""
        summary = get_backend_summary()
        
        assert isinstance(summary, dict)
        # Should have entries for the main capabilities
        assert "elixir" in summary


class TestIsRustEnabled:
    """Tests for is_rust_enabled."""

    def test_returns_bool(self):
        """Test that is_rust_enabled returns a boolean."""
        result = is_rust_enabled()
        assert isinstance(result, bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
