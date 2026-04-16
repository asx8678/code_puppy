"""Integration tests for turbo_parse plugin with both Rust-available and fallback paths.

This module provides comprehensive integration tests that verify the turbo_parse plugin
works correctly in both scenarios:
1. When the turbo_parse Rust module is available (uses actual Rust parsing)
2. When the module is absent (uses fallback stubs)

These tests use mocking to simulate both environments without requiring the actual
turbo_parse Rust module to be installed.
"""

import sys
from pathlib import Path
from typing import Generator
from unittest import mock

import pytest

from code_puppy.turbo_parse_bridge import TURBO_PARSE_AVAILABLE


# ============================================================================
# Test Fixtures (module-level)
# ============================================================================


@pytest.fixture
def sample_python_code() -> str:
    """Return sample Python code for parsing tests."""
    return """
def hello_world():
    \"\"\"A greeting function.\"\"\"
    return "Hello, World!"

class MyClass:
    def __init__(self, value: int):
        self.value = value
    
    def get_value(self) -> int:
        return self.value
        
    @property
    def doubled(self) -> int:
        return self.value * 2
"""


@pytest.fixture
def sample_rust_code() -> str:
    """Return sample Rust code for parsing tests."""
    return """
fn main() {
    println!("Hello, Rust!");
}

fn add(a: i32, b: i32) -> i32 {
    a + b
}

struct Point {
    x: f64,
    y: f64,
}

impl Point {
    fn new(x: f64, y: f64) -> Self {
        Point { x, y }
    }
}
"""


@pytest.fixture
def sample_javascript_code() -> str:
    """Return sample JavaScript code for parsing tests."""
    return """
function greet(name) {
    return `Hello, ${name}!`;
}

class User {
    constructor(name, age) {
        this.name = name;
        this.age = age;
    }
    
    greet() {
        return greet(this.name);
    }
}

const arrow = (x) => x * 2;
"""


@pytest.fixture
def temp_python_file(tmp_path: Path, sample_python_code: str) -> str:
    """Create a temporary Python file for testing."""
    file_path = tmp_path / "test_sample.py"
    file_path.write_text(sample_python_code)
    return str(file_path)


@pytest.fixture
def temp_rust_file(tmp_path: Path, sample_rust_code: str) -> str:
    """Create a temporary Rust file for testing."""
    file_path = tmp_path / "test_sample.rs"
    file_path.write_text(sample_rust_code)
    return str(file_path)


@pytest.fixture
def temp_javascript_file(tmp_path: Path, sample_javascript_code: str) -> str:
    """Create a temporary JavaScript file for testing."""
    file_path = tmp_path / "test_sample.js"
    file_path.write_text(sample_javascript_code)
    return str(file_path)


@pytest.fixture
def mock_turbo_parse_available() -> Generator[mock.MagicMock, None, None]:
    """Fixture that mocks turbo_parse module as available.

    Yields a mock module that can be customized for testing.
    """
    mock_module = mock.MagicMock()
    mock_module.__version__ = "1.0.0-test"
    mock_module.health_check.return_value = {
        "available": True,
        "version": "1.0.0-test",
        "languages": ["python", "rust", "javascript", "typescript"],
        "cache_available": True,
    }
    mock_module.stats.return_value = {
        "total_parses": 100,
        "average_parse_time_ms": 5.5,
        "languages_used": {"python": 60, "rust": 40},
        "cache_hits": 80,
        "cache_misses": 20,
        "cache_evictions": 5,
        "cache_hit_ratio": 0.8,
    }
    mock_module.is_language_supported.return_value = True
    mock_module.supported_languages.return_value = {
        "languages": ["python", "rust", "javascript", "typescript"],
        "count": 4,
    }

    # Mock parsing functions
    mock_module.parse_source.return_value = {
        "success": True,
        "tree": {"type": "module", "children": []},
        "parse_time_ms": 5.0,
        "language": "python",
        "errors": [],
    }
    mock_module.parse_file.return_value = {
        "success": True,
        "tree": {"type": "module", "children": []},
        "parse_time_ms": 8.0,
        "language": "python",
        "errors": [],
    }
    mock_module.parse_files_batch.return_value = {
        "results": [],
        "total_time_ms": 0.0,
        "files_processed": 0,
        "success_count": 0,
        "error_count": 0,
        "all_succeeded": True,
    }
    mock_module.extract_symbols.return_value = {
        "success": True,
        "symbols": [
            {"name": "hello_world", "kind": "function", "start_line": 2, "end_line": 4},
            {"name": "MyClass", "kind": "class", "start_line": 6, "end_line": 16},
        ],
        "extraction_time_ms": 2.0,
    }
    mock_module.extract_symbols_from_file.return_value = {
        "success": True,
        "symbols": [
            {"name": "hello_world", "kind": "function", "start_line": 2, "end_line": 4},
        ],
        "extraction_time_ms": 2.0,
    }
    mock_module.extract_syntax_diagnostics.return_value = {
        "diagnostics": [],
        "error_count": 0,
        "warning_count": 0,
    }
    mock_module.get_language.return_value = {
        "name": "python",
        "supported": True,
        "version": "3.x",
    }

    with mock.patch.dict("sys.modules", {"turbo_parse": mock_module}):
        yield mock_module


@pytest.fixture
def mock_turbo_parse_unavailable() -> Generator[None, None, None]:
    """Fixture that ensures turbo_parse module is unavailable.

    This is useful for testing the fallback path.
    """
    # Save original state
    original_module = sys.modules.pop("turbo_parse", None)

    # Also need to remove turbo_parse_bridge if it was already imported
    bridge_module = sys.modules.pop("code_puppy.turbo_parse_bridge", None)
    bridge_backup = None
    if bridge_module:
        bridge_backup = bridge_module

    with mock.patch("importlib.util.find_spec", return_value=None):
        yield

    # Restore original state
    if original_module:
        sys.modules["turbo_parse"] = original_module
    if bridge_backup:
        sys.modules["code_puppy.turbo_parse_bridge"] = bridge_backup


@pytest.fixture
def fresh_bridge_with_turbo_parse(
    mock_turbo_parse_available: mock.MagicMock,
) -> Generator:
    """Provide a fresh import of turbo_parse_bridge with mocked turbo_parse available.

    This ensures we test the Rust-available path even if the real module isn't installed.
    """
    # Remove existing import to force reimport
    original_bridge = sys.modules.pop("code_puppy.turbo_parse_bridge", None)
    # Also need to remove code_puppy module itself to ensure clean state
    original_code_puppy = sys.modules.pop("code_puppy", None)

    # Mock find_spec to return a spec for turbo_parse
    mock_spec = mock.MagicMock()
    with mock.patch("importlib.util.find_spec", return_value=mock_spec):
        try:
            # First ensure code_puppy exists
            if original_code_puppy:
                sys.modules["code_puppy"] = original_code_puppy

            # Import the bridge fresh
            from code_puppy import turbo_parse_bridge

            yield turbo_parse_bridge
        finally:
            # Restore original modules
            if original_bridge:
                sys.modules["code_puppy.turbo_parse_bridge"] = original_bridge
            elif "code_puppy.turbo_parse_bridge" in sys.modules:
                sys.modules.pop("code_puppy.turbo_parse_bridge")


@pytest.fixture
def fresh_bridge_without_turbo_parse() -> Generator:
    """Provide a fresh import of turbo_parse_bridge with turbo_parse unavailable.

    This ensures we test the fallback path.
    """
    # Remove existing imports to force reimport
    original_bridge = sys.modules.pop("code_puppy.turbo_parse_bridge", None)
    # Also need to remove code_puppy module itself to ensure clean state
    original_code_puppy = sys.modules.pop("code_puppy", None)

    # Mock find_spec to return None (turbo_parse not available)
    with mock.patch("importlib.util.find_spec", return_value=None):
        try:
            # First ensure code_puppy exists
            if original_code_puppy:
                sys.modules["code_puppy"] = original_code_puppy

            # Import the bridge fresh
            from code_puppy import turbo_parse_bridge

            yield turbo_parse_bridge
        finally:
            # Restore original modules
            if original_bridge:
                sys.modules["code_puppy.turbo_parse_bridge"] = original_bridge
            elif "code_puppy.turbo_parse_bridge" in sys.modules:
                sys.modules.pop("code_puppy.turbo_parse_bridge")


# ============================================================================
# Tests for the Rust-available path (using mocking)
# ============================================================================


class TestTurboParseAvailablePath:
    """Tests that verify behavior when turbo_parse Rust module IS available."""

    def test_bridge_shows_available_when_module_present(
        self, mock_turbo_parse_available
    ):
        """Test that the bridge correctly shows TURBO_PARSE_AVAILABLE=True when module present."""
        # Remove and reimport to test the import block
        sys.modules.pop("code_puppy.turbo_parse_bridge", None)

        mock_spec = mock.MagicMock()
        with mock.patch("importlib.util.find_spec", return_value=mock_spec):
            from code_puppy.turbo_parse_bridge import TURBO_PARSE_AVAILABLE

            assert TURBO_PARSE_AVAILABLE is True

    def test_is_turbo_parse_enabled_returns_true(self, mock_turbo_parse_available):
        """Test is_turbo_parse_enabled() returns True when module available."""
        sys.modules.pop("code_puppy.turbo_parse_bridge", None)

        mock_spec = mock.MagicMock()
        with mock.patch("importlib.util.find_spec", return_value=mock_spec):
            from code_puppy.turbo_parse_bridge import is_turbo_parse_enabled

            assert is_turbo_parse_enabled() is True

    def test_get_turbo_parse_status_with_module(self, mock_turbo_parse_available):
        """Test get_turbo_parse_status() with available module."""
        sys.modules.pop("code_puppy.turbo_parse_bridge", None)

        mock_spec = mock.MagicMock()
        with mock.patch("importlib.util.find_spec", return_value=mock_spec):
            from code_puppy.turbo_parse_bridge import get_turbo_parse_status

            status = get_turbo_parse_status()
            assert status["installed"] is True
            assert status["enabled"] is True
            assert status["active"] is True

    def test_set_turbo_parse_enabled_toggle(self, mock_turbo_parse_available):
        """Test toggling turbo_parse enabled/disabled state."""
        sys.modules.pop("code_puppy.turbo_parse_bridge", None)

        mock_spec = mock.MagicMock()
        with mock.patch("importlib.util.find_spec", return_value=mock_spec):
            from code_puppy.turbo_parse_bridge import (
                is_turbo_parse_enabled,
                set_turbo_parse_enabled,
                get_turbo_parse_status,
            )

            # Initially enabled
            assert is_turbo_parse_enabled() is True

            # Disable
            set_turbo_parse_enabled(False)
            assert is_turbo_parse_enabled() is False
            status = get_turbo_parse_status()
            assert status["enabled"] is False
            assert status["active"] is False

            # Re-enable
            set_turbo_parse_enabled(True)
            assert is_turbo_parse_enabled() is True


# ============================================================================
# Tests for the fallback path (when turbo_parse is absent)
# ============================================================================


class TestTurboParseFallbackPath:
    """Tests that verify fallback behavior when turbo_parse Rust module is NOT available."""

    def test_bridge_shows_unavailable_when_module_absent(
        self, fresh_bridge_without_turbo_parse
    ):
        """Test that the bridge correctly shows TURBO_PARSE_AVAILABLE=False when module absent."""
        from code_puppy.turbo_parse_bridge import TURBO_PARSE_AVAILABLE

        assert TURBO_PARSE_AVAILABLE is False

    def test_parse_source_returns_error_stub(self, fresh_bridge_without_turbo_parse):
        """Test parse_source returns error structure when module unavailable."""
        from code_puppy.turbo_parse_bridge import parse_source

        result = parse_source("def test(): pass", "python")

        assert result["success"] is False
        assert result["tree"] is None
        assert result["parse_time_ms"] == 0.0
        assert len(result["errors"]) > 0
        assert "not available" in result["errors"][0]["message"].lower()

    def test_parse_file_returns_error_stub(self, fresh_bridge_without_turbo_parse):
        """Test parse_file returns error structure when module unavailable."""
        from code_puppy.turbo_parse_bridge import parse_file

        result = parse_file("/path/to/file.py")

        assert result["success"] is False
        assert result["tree"] is None
        assert len(result["errors"]) > 0
        assert "not available" in result["errors"][0]["message"].lower()

    def test_extract_symbols_returns_error_stub(self, fresh_bridge_without_turbo_parse):
        """Test extract_symbols returns error structure when module unavailable."""
        from code_puppy.turbo_parse_bridge import extract_symbols

        result = extract_symbols("def test(): pass", "python")

        assert result["success"] is False
        assert result["symbols"] == []
        assert "not available" in result["error"].lower()

    def test_extract_symbols_from_file_returns_error_stub(
        self, fresh_bridge_without_turbo_parse
    ):
        """Test extract_symbols_from_file returns error structure when module unavailable."""
        from code_puppy.turbo_parse_bridge import extract_symbols_from_file

        result = extract_symbols_from_file("/path/to/file.py")

        assert result["success"] is False
        assert result["symbols"] == []
        assert "not available" in result["error"].lower()

    def test_extract_syntax_diagnostics_returns_error_stub(
        self, fresh_bridge_without_turbo_parse
    ):
        """Test extract_syntax_diagnostics returns error structure when module unavailable."""
        from code_puppy.turbo_parse_bridge import extract_syntax_diagnostics

        result = extract_syntax_diagnostics("def test(): pass", "python")

        assert result["diagnostics"] == []
        assert result["error_count"] == 0
        assert result["warning_count"] == 0
        assert "not available" in result["error"].lower()

    def test_parse_files_batch_returns_error_stub(
        self, fresh_bridge_without_turbo_parse
    ):
        """Test parse_files_batch returns error structure when module unavailable."""
        from code_puppy.turbo_parse_bridge import parse_files_batch

        result = parse_files_batch(["file1.py", "file2.py"])

        assert result["files_processed"] == 2
        assert result["success_count"] == 0
        assert result["error_count"] == 2
        assert result["all_succeeded"] is False
        assert len(result["results"]) == 2

        for r in result["results"]:
            assert r["success"] is False
            assert (
                "not available"
                in str(r.get("errors", [{}])[0].get("message", "")).lower()
            )

    def test_health_check_returns_unavailable_status(
        self, fresh_bridge_without_turbo_parse
    ):
        """Test health_check returns unavailable status when module unavailable."""
        from code_puppy.turbo_parse_bridge import health_check

        result = health_check()

        assert result["available"] is False
        assert result["version"] is None
        assert result["languages"] == []
        assert result["cache_available"] is False

    def test_stats_returns_zero_values(self, fresh_bridge_without_turbo_parse):
        """Test stats returns zero/empty values when module unavailable."""
        from code_puppy.turbo_parse_bridge import stats

        result = stats()

        assert result["total_parses"] == 0
        assert result["average_parse_time_ms"] == 0.0
        assert result["languages_used"] == {}
        assert result["cache_hits"] == 0
        assert result["cache_misses"] == 0
        assert result["cache_evictions"] == 0
        assert result["cache_hit_ratio"] == 0.0

    def test_is_language_supported_returns_false(
        self, fresh_bridge_without_turbo_parse
    ):
        """Test is_language_supported always returns False when module unavailable."""
        from code_puppy.turbo_parse_bridge import is_language_supported

        assert is_language_supported("python") is False
        assert is_language_supported("rust") is False
        assert is_language_supported("any_language") is False

    def test_supported_languages_returns_empty(self, fresh_bridge_without_turbo_parse):
        """Test supported_languages returns empty list when module unavailable."""
        from code_puppy.turbo_parse_bridge import supported_languages

        result = supported_languages()

        assert result["languages"] == []
        assert result["count"] == 0

    def test_get_language_returns_unsupported(self, fresh_bridge_without_turbo_parse):
        """Test get_language returns unsupported status when module unavailable."""
        from code_puppy.turbo_parse_bridge import get_language

        result = get_language("python")

        assert result["name"] == "python"
        assert result["supported"] is False
        assert "not available" in result["error"].lower()

    def test_is_turbo_parse_enabled_returns_false_when_unavailable(
        self, fresh_bridge_without_turbo_parse
    ):
        """Test is_turbo_parse_enabled returns False when module unavailable."""
        from code_puppy.turbo_parse_bridge import is_turbo_parse_enabled

        # Should be False regardless of _turbo_parse_user_enabled
        assert is_turbo_parse_enabled() is False

    def test_get_turbo_parse_status_when_unavailable(
        self, fresh_bridge_without_turbo_parse
    ):
        """Test get_turbo_parse_status when module unavailable."""
        from code_puppy.turbo_parse_bridge import get_turbo_parse_status

        status = get_turbo_parse_status()

        assert status["installed"] is False
        assert status["active"] is False
        # enabled should still be True by default, just not active
        assert status["enabled"] is True


# ============================================================================
# Tests for graceful degradation scenarios
# ============================================================================


class TestGracefulDegradation:
    """Tests for verifying the bridge degrades gracefully between states."""

    def test_error_structure_consistency_across_paths(self):
        """Test that error structures are consistent between available and fallback paths."""
        from code_puppy.turbo_parse_bridge import parse_source

        # Test that result structure is consistent
        result = parse_source("def test(): pass", "python")

        # Both paths should return these keys
        assert "success" in result
        assert "tree" in result
        assert "parse_time_ms" in result
        assert "language" in result
        assert "errors" in result

        # Values should have consistent types
        assert isinstance(result["success"], bool)
        assert isinstance(result["parse_time_ms"], (int, float))
        assert isinstance(result["errors"], list)

    def test_language_preservation_in_errors(self, fresh_bridge_without_turbo_parse):
        """Test that language parameter is preserved in error responses."""
        from code_puppy.turbo_parse_bridge import (
            parse_source,
            parse_file,
            get_language,
        )

        # parse_source preserves language
        result = parse_source("code", "rust")
        assert result["language"] == "rust"

        # parse_file preserves provided language
        result = parse_file("/path", language="javascript")
        assert result["language"] == "javascript"

        # get_language preserves name
        result = get_language("elixir")
        assert result["name"] == "elixir"

    def test_timing_values_are_non_negative(self, fresh_bridge_without_turbo_parse):
        """Test that timing values are always non-negative."""
        from code_puppy.turbo_parse_bridge import parse_source, parse_file, stats

        result = parse_source("def test(): pass", "python")
        assert result["parse_time_ms"] >= 0.0

        result = parse_file("/path/file.py")
        assert result["parse_time_ms"] >= 0.0

        result = stats()
        assert result["average_parse_time_ms"] >= 0.0

    def test_no_exceptions_in_fallback(self, fresh_bridge_without_turbo_parse):
        """Test that fallback stubs never raise exceptions."""
        from code_puppy.turbo_parse_bridge import (
            parse_source,
            parse_file,
            parse_files_batch,
            extract_symbols,
            extract_symbols_from_file,
            extract_syntax_diagnostics,
            health_check,
            stats,
            get_language,
            is_language_supported,
            supported_languages,
        )

        # None of these should raise exceptions
        try:
            parse_source("", "python")
            parse_source("invalid!!", "rust")
            parse_source("x" * 1000000, "javascript")  # Very long source

            parse_file("/nonexistent/path.py")
            parse_file("")  # Empty path

            parse_files_batch([])
            parse_files_batch(["/nonexistent/1.py", "/nonexistent/2.rs"])

            extract_symbols("", "python")
            extract_symbols("code", "unsupported_lang")

            extract_symbols_from_file("/nonexistent.py")

            extract_syntax_diagnostics("def broken(", "python")
            extract_syntax_diagnostics("", "")

            health_check()
            stats()
            get_language("")
            get_language("unsupported")
            is_language_supported("")
            supported_languages()
        except Exception as e:
            pytest.fail(f"Fallback stub raised exception: {e}")


# ============================================================================
# Tests for plugin startup behavior in both scenarios
# ============================================================================


class TestPluginStartupBehavior:
    """Tests for plugin startup callback behavior."""

    def test_startup_logs_when_module_available(
        self, caplog, mock_turbo_parse_available
    ):
        """Test startup logs appropriate message when module is available.

        bd-93: Uses NativeBackend instead of direct module import.
        """
        from code_puppy.plugins.turbo_parse.register_callbacks import _on_startup

        # Mock NativeBackend.parse_health_check to return a valid response
        mock_health = {"version": "1.0.0-test", "available": True}

        with mock.patch(
            "code_puppy.plugins.turbo_parse.register_callbacks.is_turbo_parse_available"
        ) as mock_avail:
            mock_avail.return_value = True

            with mock.patch(
                "code_puppy.plugins.turbo_parse.register_callbacks.NativeBackend.parse_health_check",
                return_value=mock_health,
            ):
                with caplog.at_level("INFO"):
                    _on_startup()

        # Should have logged availability
        availability_logs = [
            r for r in caplog.records if "available" in r.message.lower()
        ]
        assert len(availability_logs) > 0

    def test_startup_logs_fallback_when_module_unavailable(self, caplog):
        """Test startup logs fallback message when module is unavailable."""
        from code_puppy.plugins.turbo_parse.register_callbacks import _on_startup

        with mock.patch(
            "code_puppy.plugins.turbo_parse.register_callbacks.is_turbo_parse_available"
        ) as mock_avail:
            mock_avail.return_value = False

            with caplog.at_level("INFO"):
                _on_startup()

        # Should have logged fallback message
        assert any(
            "not available" in r.message.lower() or "fallback" in r.message.lower()
            for r in caplog.records
        )

    def test_startup_handles_health_check_error_gracefully(
        self, caplog, mock_turbo_parse_available
    ):
        """Test startup handles NativeBackend health check error gracefully.

        bd-93: Uses NativeBackend instead of direct module import, so tests
        health check failures rather than import errors.
        """
        from code_puppy.plugins.turbo_parse.register_callbacks import _on_startup

        with mock.patch(
            "code_puppy.plugins.turbo_parse.register_callbacks.is_turbo_parse_available"
        ) as mock_avail:
            mock_avail.return_value = True

            # Mock NativeBackend.parse_health_check to raise exception
            with mock.patch(
                "code_puppy.plugins.turbo_parse.register_callbacks.NativeBackend.parse_health_check",
                side_effect=Exception("Simulated health check error"),
            ):
                with caplog.at_level("WARNING"):
                    _on_startup()

        # Should have logged warning about error
        assert any("error" in r.message.lower() for r in caplog.records)


# ============================================================================
# Tests for parse_code tool in both scenarios
# ============================================================================


class TestParseCodeToolBothPaths:
    """Tests for parse_code tool behavior in both available and fallback scenarios."""

    def test_parse_code_tool_structure_always_available(self):
        """Test that parse_code tool exists and can be registered regardless of turbo_parse availability.

        bd-93: Now registers 4 tools: parse_code, get_highlights, get_folds, get_outline.
        """
        from code_puppy.plugins.turbo_parse.register_callbacks import (
            _register_tools,
            _register_parse_code_tool,
        )

        tools = _register_tools()
        # bd-93: Should have 4 tools registered
        assert len(tools) == 4
        tool_names = [t["name"] for t in tools]
        assert "parse_code" in tool_names
        assert "get_highlights" in tool_names
        assert "get_folds" in tool_names
        assert "get_outline" in tool_names

        # All tools should have callable register functions
        for tool in tools:
            assert callable(tool["register_func"])

        # Tool registration function exists
        assert callable(_register_parse_code_tool)

    def test_parse_code_tool_fallback_response_structure(
        self, fresh_bridge_without_turbo_parse
    ):
        """Test parse_code tool returns proper structure in fallback mode."""
        from code_puppy.plugins.turbo_parse.register_callbacks import (
            _register_parse_code_tool,
        )
        import asyncio

        mock_agent = mock.MagicMock()
        tools = {}

        def mock_tool_decorator(func):
            tools[func.__name__] = func
            return func

        mock_agent.tool = mock_tool_decorator
        _register_parse_code_tool(mock_agent)

        parse_code = tools["parse_code"]

        result = asyncio.run(
            parse_code(
                context=mock.MagicMock(),
                source="def hello(): pass",
                language="python",
                options=None,
            )
        )

        # Structure should be consistent
        assert "success" in result
        assert "tree" in result
        assert "symbols" in result
        assert "diagnostics" in result
        assert "parse_time_ms" in result
        assert "language" in result
        assert "errors" in result

    def test_parse_code_tool_handles_unsupported_language_in_both_modes(self):
        """Test parse_code tool handles unsupported language in both modes."""
        from code_puppy.plugins.turbo_parse.register_callbacks import (
            _register_parse_code_tool,
        )
        import asyncio

        mock_agent = mock.MagicMock()
        tools = {}

        def mock_tool_decorator(func):
            tools[func.__name__] = func
            return func

        mock_agent.tool = mock_tool_decorator
        _register_parse_code_tool(mock_agent)

        parse_code = tools["parse_code"]

        result = asyncio.run(
            parse_code(
                context=mock.MagicMock(),
                source="some code",
                language="unsupported_lang_xyz",
                options=None,
            )
        )

        # Should fail gracefully
        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_language_normalization_works_in_both_modes(self):
        """Test language normalization works regardless of turbo_parse availability."""
        from code_puppy.plugins.turbo_parse.register_callbacks import (
            _normalize_language,
        )

        # These should work regardless of whether turbo_parse is available
        assert _normalize_language("py") == "python"
        assert _normalize_language("js") == "javascript"
        assert _normalize_language("ts") == "typescript"
        assert _normalize_language("rs") == "rust"
        assert _normalize_language("PYTHON") == "python"
        assert _normalize_language("  python  ") == "python"


# ============================================================================
# Integration tests with actual module (if available)
# ============================================================================


class TestActualModuleIntegration:
    """Integration tests that use the actual turbo_parse module when available.

    These tests are skipped if the turbo_parse Rust module is not installed.
    They provide end-to-end verification of the actual functionality.
    """

    @pytest.mark.skipif(
        not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed"
    )
    def test_actual_parse_source_python(self, sample_python_code):
        """Test actual parsing of Python code with real module."""
        from code_puppy.turbo_parse_bridge import parse_source

        result = parse_source(sample_python_code, "python")

        assert result["success"] is True
        assert result["language"] == "python"
        assert result["tree"] is not None
        assert result["parse_time_ms"] > 0

    @pytest.mark.skipif(
        not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed"
    )
    def test_actual_parse_source_rust(self, sample_rust_code):
        """Test actual parsing of Rust code with real module."""
        from code_puppy.turbo_parse_bridge import parse_source

        result = parse_source(sample_rust_code, "rust")

        assert result["success"] is True
        assert result["language"] == "rust"
        assert result["tree"] is not None

    @pytest.mark.skipif(
        not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed"
    )
    def test_actual_parse_file(self, temp_python_file):
        """Test actual file parsing with real module."""
        from code_puppy.turbo_parse_bridge import parse_file

        result = parse_file(temp_python_file)

        assert result["success"] is True
        assert result["language"] == "python"
        assert result["tree"] is not None

    @pytest.mark.skipif(
        not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed"
    )
    def test_actual_extract_symbols(self, sample_python_code):
        """Test actual symbol extraction with real module."""
        from code_puppy.turbo_parse_bridge import extract_symbols

        result = extract_symbols(sample_python_code, "python")

        assert result["success"] is True
        assert isinstance(result["symbols"], list)
        assert result["extraction_time_ms"] >= 0.0

        # Verify symbol structure
        for symbol in result["symbols"]:
            assert "name" in symbol
            assert "kind" in symbol

    @pytest.mark.skipif(
        not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed"
    )
    def test_actual_extract_diagnostics(self):
        """Test actual diagnostic extraction with real module."""
        from code_puppy.turbo_parse_bridge import extract_syntax_diagnostics

        code_with_error = "def broken(  # incomplete"
        result = extract_syntax_diagnostics(code_with_error, "python")

        assert "diagnostics" in result
        assert isinstance(result["diagnostics"], list)
        assert isinstance(result["error_count"], int)
        assert isinstance(result["warning_count"], int)

    @pytest.mark.skipif(
        not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed"
    )
    def test_actual_parse_files_batch(self, temp_python_file, temp_rust_file):
        """Test actual batch parsing with real module."""
        from code_puppy.turbo_parse_bridge import parse_files_batch

        result = parse_files_batch([temp_python_file, temp_rust_file])

        assert result["files_processed"] == 2
        assert result["success_count"] == 2
        assert result["error_count"] == 0
        assert result["all_succeeded"] is True
        assert len(result["results"]) == 2
        assert result["total_time_ms"] >= 0.0

    @pytest.mark.skipif(
        not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed"
    )
    def test_actual_health_check(self):
        """Test actual health_check with real module."""
        from code_puppy.turbo_parse_bridge import health_check

        result = health_check()

        assert result["available"] is True
        assert isinstance(result["languages"], list)
        assert len(result["languages"]) > 0

    @pytest.mark.skipif(
        not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed"
    )
    def test_actual_stats(self):
        """Test actual stats with real module."""
        from code_puppy.turbo_parse_bridge import stats

        result = stats()

        assert "total_parses" in result
        assert "average_parse_time_ms" in result
        assert "cache_hit_ratio" in result
        assert 0.0 <= result["cache_hit_ratio"] <= 1.0

    @pytest.mark.skipif(
        not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed"
    )
    def test_actual_language_support(self):
        """Test actual language support checking with real module."""
        from code_puppy.turbo_parse_bridge import (
            is_language_supported,
            supported_languages,
            get_language,
        )

        assert is_language_supported("python") is True
        assert is_language_supported("rust") is True
        assert is_language_supported("unsupported_xyz") is False

        langs = supported_languages()
        assert langs["count"] > 0
        assert len(langs["languages"]) > 0

        lang_info = get_language("python")
        assert lang_info["supported"] is True

    @pytest.mark.skipif(
        not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed"
    )
    def test_parse_code_tool_with_actual_module(self, sample_python_code):
        """Test parse_code tool end-to-end with actual module."""
        from code_puppy.plugins.turbo_parse.register_callbacks import (
            _register_parse_code_tool,
        )
        import asyncio

        mock_agent = mock.MagicMock()
        tools = {}

        def mock_tool_decorator(func):
            tools[func.__name__] = func
            return func

        mock_agent.tool = mock_tool_decorator
        _register_parse_code_tool(mock_agent)

        parse_code = tools["parse_code"]

        result = asyncio.run(
            parse_code(
                context=mock.MagicMock(),
                source=sample_python_code,
                language="python",
                options={"extract_symbols": True},
            )
        )

        assert result["success"] is True
        assert result["tree"] is not None
        assert isinstance(result["symbols"], list)


# ============================================================================
# Test that both paths have consistent behavior
# ============================================================================


class TestPathConsistency:
    """Tests to ensure both Rust-available and fallback paths behave consistently."""

    def test_result_structure_consistency(self):
        """Verify both paths return results with consistent structure."""
        from code_puppy.turbo_parse_bridge import (
            parse_source,
            parse_file,
            extract_symbols,
            extract_symbols_from_file,
            extract_syntax_diagnostics,
            stats,
            health_check,
            get_language,
            supported_languages,
        )

        # Define expected keys for each function
        expected_keys = {
            "parse_source": ["success", "tree", "parse_time_ms", "language", "errors"],
            "parse_file": ["success", "tree", "parse_time_ms", "language", "errors"],
            "extract_symbols": ["success", "symbols", "extraction_time_ms"],
            "extract_symbols_from_file": ["success", "symbols", "extraction_time_ms"],
            "extract_syntax_diagnostics": [
                "diagnostics",
                "error_count",
                "warning_count",
            ],
            "stats": [
                "total_parses",
                "average_parse_time_ms",
                "languages_used",
                "cache_hits",
                "cache_misses",
                "cache_evictions",
                "cache_hit_ratio",
            ],
            "health_check": ["available", "version", "languages", "cache_available"],
            "get_language": ["name", "supported"],
            "supported_languages": ["languages", "count"],
        }

        functions = {
            "parse_source": lambda: parse_source("def test(): pass", "python"),
            "parse_file": lambda: parse_file("/tmp/test.py"),
            "extract_symbols": lambda: extract_symbols("def test(): pass", "python"),
            "extract_symbols_from_file": lambda: extract_symbols_from_file(
                "/tmp/test.py"
            ),
            "extract_syntax_diagnostics": lambda: extract_syntax_diagnostics(
                "def test(): pass", "python"
            ),
            "stats": stats,
            "health_check": health_check,
            "get_language": lambda: get_language("python"),
            "supported_languages": supported_languages,
        }

        for name, func in functions.items():
            result = func()
            expected = expected_keys[name]

            for key in expected:
                assert key in result, f"{name}() result missing key: {key}"

    def test_error_response_types(self):
        """Verify error responses have consistent types."""
        from code_puppy.turbo_parse_bridge import parse_source

        result = parse_source("def test(): pass", "unsupported_language_xyz")

        assert isinstance(result["success"], bool)
        assert isinstance(result["errors"], list)

        # Each error should have a message
        for error in result["errors"]:
            assert "message" in error
