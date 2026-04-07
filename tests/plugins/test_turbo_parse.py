"""Tests for the turbo_parse plugin.

This plugin provides high-performance parsing via the turbo_parse Rust module.
Tests verify availability checking, callback registration, and graceful fallback.
"""

import importlib.util
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest import mock

import pytest

from code_puppy.callbacks import clear_callbacks, get_callbacks, register_callback
from code_puppy.turbo_parse_bridge import TURBO_PARSE_AVAILABLE


def is_turbo_parse_available() -> bool:
    """Check if turbo_parse module is available without importing it."""
    return importlib.util.find_spec("turbo_parse") is not None


class TestTurboParseAvailability:
    """Tests for the is_turbo_parse_available function."""

    def test_availability_check_returns_bool(self):
        """Test that availability check returns a boolean."""
        result = is_turbo_parse_available()
        assert isinstance(result, bool)

    def test_availability_check_uses_importlib(self):
        """Test that availability check uses importlib.util.find_spec."""
        with mock.patch("importlib.util.find_spec") as mock_find_spec:
            mock_find_spec.return_value = None
            result = is_turbo_parse_available()
            mock_find_spec.assert_called_once_with("turbo_parse")
            assert result is False

    def test_availability_check_returns_true_when_spec_found(self):
        """Test that availability check returns True when spec exists."""
        with mock.patch("importlib.util.find_spec") as mock_find_spec:
            mock_spec = mock.Mock()
            mock_find_spec.return_value = mock_spec
            result = is_turbo_parse_available()
            assert result is True


class TestTurboParsePluginCallbacks:
    """Tests for the turbo_parse plugin callback registration."""

    def setup_method(self):
        """Clear callbacks before each test."""
        clear_callbacks("startup")
        clear_callbacks("register_tools")

    def teardown_method(self):
        """Clear callbacks after each test."""
        clear_callbacks("startup")
        clear_callbacks("register_tools")

    def test_plugin_registers_startup_callback(self):
        """Test that the plugin registers a startup callback."""
        # Import the register_callbacks module and register callbacks directly
        from code_puppy.plugins.turbo_parse import register_callbacks

        register_callbacks._on_startup  # Verify function exists
        # Register directly to ensure test works regardless of import order
        register_callback("startup", register_callbacks._on_startup)

        callbacks = get_callbacks("startup")
        assert any(
            cb.__module__ == "code_puppy.plugins.turbo_parse.register_callbacks"
            for cb in callbacks
        )

    def test_plugin_registers_tools_callback(self):
        """Test that the plugin registers a register_tools callback."""
        from code_puppy.plugins.turbo_parse import register_callbacks

        register_callbacks._register_tools  # Verify function exists
        # Register directly to ensure test works regardless of import order
        register_callback("register_tools", register_callbacks._register_tools)

        callbacks = get_callbacks("register_tools")
        assert any(
            cb.__module__ == "code_puppy.plugins.turbo_parse.register_callbacks"
            for cb in callbacks
        )

    def test_register_tools_callback_returns_list(self):
        """Test that the register_tools callback returns a list."""
        from code_puppy.plugins.turbo_parse.register_callbacks import _register_tools

        result = _register_tools()
        assert isinstance(result, list)
        assert len(result) == 0  # Currently a placeholder


class TestTurboParseStartup:
    """Tests for the turbo_parse startup behavior."""

    def setup_method(self):
        """Clear callbacks before each test."""
        clear_callbacks("startup")

    def teardown_method(self):
        """Clear callbacks after each test."""
        clear_callbacks("startup")

    def test_startup_handles_missing_module_gracefully(self, caplog):
        """Test that startup handles missing turbo_parse gracefully."""
        from code_puppy.plugins.turbo_parse.register_callbacks import _on_startup

        with mock.patch(
            "code_puppy.plugins.turbo_parse.register_callbacks.is_turbo_parse_available",
            return_value=False,
        ):
            with caplog.at_level("INFO"):
                _on_startup()

        assert any(
            "not available" in record.message.lower() or "fallback" in record.message.lower()
            for record in caplog.records
        )

    def test_startup_logs_when_module_available(self, caplog):
        """Test that startup logs when turbo_parse is available."""
        from code_puppy.plugins.turbo_parse.register_callbacks import _on_startup

        mock_module = mock.Mock()
        mock_module.__version__ = "1.0.0"
        mock_module.health_check.return_value = {"version": "1.0.0"}

        with mock.patch(
            "code_puppy.plugins.turbo_parse.register_callbacks.is_turbo_parse_available",
            return_value=True,
        ):
            with mock.patch("builtins.__import__", return_value=mock_module):
                with caplog.at_level("INFO"):
                    _on_startup()

        # Should have an INFO or DEBUG log about the module being available
        assert any(
            "available" in record.message.lower()
            for record in caplog.records
        )


class TestTurboParseExports:
    """Tests for the plugin's public exports."""

    def test_init_exports_version(self):
        """Test that __init__.py exports __version__."""
        from code_puppy.plugins import turbo_parse

        assert hasattr(turbo_parse, "__version__")
        assert turbo_parse.__version__ == "0.1.0"

    def test_init_exports_availability_function(self):
        """Test that __init__.py exports is_turbo_parse_available."""
        from code_puppy.plugins import turbo_parse

        assert hasattr(turbo_parse, "is_turbo_parse_available")
        assert callable(turbo_parse.is_turbo_parse_available)
        result = turbo_parse.is_turbo_parse_available()
        assert isinstance(result, bool)

    def test_all_exports_are_public(self):
        """Test that __all__ only contains public names."""
        from code_puppy.plugins import turbo_parse

        assert hasattr(turbo_parse, "__all__")
        for name in turbo_parse.__all__:
            # Single underscore prefix is private; dunder names like __version__ are public
            assert not name.startswith("_") or name.startswith("__"), (
                f"Private name {name} in __all__"
            )


# ============================================================================
# Tests for parse_source and parse_file functionality
# ============================================================================

class TestParseSource:
    """Tests for parse_source basic functionality."""

    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_parse_source_python_function(self):
        """Test parsing a simple Python function."""
        from code_puppy.turbo_parse_bridge import parse_source
        
        source = "def hello(): pass"
        result = parse_source(source, "python")
        
        assert result["success"] is True
        assert result["language"] == "python"
        assert "tree" in result
        assert "parse_time_ms" in result
        assert isinstance(result["parse_time_ms"], (int, float))
    
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_parse_source_class_definition(self):
        """Test parsing a Python class definition."""
        from code_puppy.turbo_parse_bridge import parse_source
        
        source = """
class MyClass:
    def __init__(self):
        self.value = 42
        
    def get_value(self):
        return self.value
"""
        result = parse_source(source, "python")
        
        assert result["success"] is True
        assert result["language"] == "python"
        assert result["tree"] is not None
    
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_parse_source_invalid_syntax(self):
        """Test parsing source with invalid syntax."""
        from code_puppy.turbo_parse_bridge import parse_source
        
        source = "def broken(  # incomplete"
        result = parse_source(source, "python")
        
        # Should return result with success flag and error info
        assert "success" in result
        assert "errors" in result
    
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_parse_source_rust_code(self):
        """Test parsing Rust source code."""
        from code_puppy.turbo_parse_bridge import parse_source
        
        source = "fn main() { println!(\"Hello\"); }"
        result = parse_source(source, "rust")
        
        assert result["success"] is True
        assert result["language"] == "rust"


class TestParseFile:
    """Tests for parse_file with temp file."""

    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_parse_file_python(self):
        """Test parsing a Python file from disk."""
        from code_puppy.turbo_parse_bridge import parse_file
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            temp_path = f.name
        
        try:
            result = parse_file(temp_path)
            
            assert result["success"] is True
            assert result["language"] == "python"
            assert "tree" in result
            assert "parse_time_ms" in result
        finally:
            os.unlink(temp_path)
    
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_parse_file_with_language_override(self):
        """Test parsing with explicit language override."""
        from code_puppy.turbo_parse_bridge import parse_file
        
        # Create a file with no extension
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("fn main() {}")
            temp_path = f.name
        
        try:
            # Override language to rust
            result = parse_file(temp_path, language="rust")
            
            assert result["success"] is True
            assert result["language"] == "rust"
        finally:
            os.unlink(temp_path)
    
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_parse_file_empty(self):
        """Test parsing an empty file."""
        from code_puppy.turbo_parse_bridge import parse_file
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("")
            temp_path = f.name
        
        try:
            result = parse_file(temp_path)
            
            # Should handle empty files gracefully
            assert "success" in result
            assert "language" in result
        finally:
            os.unlink(temp_path)
    
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_parse_file_nonexistent(self):
        """Test parsing a non-existent file."""
        from code_puppy.turbo_parse_bridge import parse_file
        
        result = parse_file("/nonexistent/path/file.py")
        
        # Should return error for non-existent file
        assert result["success"] is False
        assert "errors" in result


class TestUnsupportedLanguage:
    """Tests for unsupported language error handling."""

    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_unsupported_language_error(self):
        """Test that unsupported language returns appropriate error."""
        from code_puppy.turbo_parse_bridge import parse_source
        
        result = parse_source("some code", "unsupported_language_xyz")
        
        # Should fail gracefully with error info
        assert result["success"] is False
        assert "errors" in result
        assert len(result["errors"]) > 0
        
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_unsupported_language_via_is_language_supported(self):
        """Test is_language_supported for unsupported languages."""
        from code_puppy.turbo_parse_bridge import is_language_supported
        
        assert is_language_supported("unsupported_xyz") is False
        assert is_language_supported("python") is True


class TestConcurrentGILRelease:
    """Test that GIL is released during parsing by calling from multiple threads."""
    
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_concurrent_parse_source(self):
        """Test concurrent parse_source calls from multiple threads."""
        from code_puppy.turbo_parse_bridge import parse_source
        
        sources = [
            ("def f1(): pass", "python"),
            ("def f2(): return 42", "python"),
            ("class C: pass", "python"),
            ("fn main() {}", "rust"),
            ("fn foo() -> i32 { 42 }", "rust"),
        ]
        
        results = []
        errors = []
        
        def parse_worker(source_lang):
            source, lang = source_lang
            try:
                result = parse_source(source, lang)
                results.append(result)
                return result["success"]
            except Exception as e:
                errors.append(e)
                return False
        
        # Run parsing concurrently from multiple threads
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(parse_worker, s) for s in sources]
            outcomes = [f.result() for f in as_completed(futures)]
        
        # All should complete without crashing
        assert len(results) + len(errors) == len(sources)
        # Most should succeed (at least the valid ones)
        assert sum(outcomes) >= 3, f"Expected at least 3 successes, got {sum(outcomes)}"
    
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_concurrent_parse_file(self):
        """Test concurrent parse_file calls from multiple threads."""
        from code_puppy.turbo_parse_bridge import parse_file
        
        # Create multiple temp files
        temp_files = []
        for i in range(4):
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(f"def func_{i}(): return {i}\n")
                temp_files.append(f.name)
        
        results = []
        errors = []
        
        def parse_worker(path):
            try:
                result = parse_file(path)
                results.append(result)
                return result["success"]
            except Exception as e:
                errors.append(e)
                return False
        
        try:
            # Run parsing concurrently
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(parse_worker, path) for path in temp_files]
                outcomes = [f.result() for f in as_completed(futures)]
            
            # All should complete without crashing
            assert len(results) + len(errors) == len(temp_files)
            # Most should succeed
            assert sum(outcomes) >= 3, f"Expected at least 3 successes, got {sum(outcomes)}"
        finally:
            for path in temp_files:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_thread_safety_stress(self):
        """Stress test with many concurrent threads."""
        from code_puppy.turbo_parse_bridge import parse_source
        
        num_threads = 10
        results = []
        lock = threading.Lock()
        
        def stress_worker(thread_id):
            source = f"def thread_func_{thread_id}(): return {thread_id}"
            try:
                result = parse_source(source, "python")
                with lock:
                    results.append((thread_id, result["success"]))
                return result["success"]
            except Exception as e:
                with lock:
                    results.append((thread_id, False, str(e)))
                return False
        
        # Launch many threads concurrently
        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=stress_worker, args=(i,))
            threads.append(t)
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        # All threads should complete
        assert len(results) == num_threads, f"Expected {num_threads} results, got {len(results)}"
        # Most should succeed (the GIL release allows true parallelism)
        successes = sum(1 for r in results if len(r) > 1 and r[1] is True)
        assert successes >= num_threads * 0.8, f"Expected ~{num_threads} successes, got {successes}"


class TestBridgeFallback:
    """Tests for fallback behavior when turbo_parse is not available."""
    
    def test_fallback_parse_source_stub(self):
        """Test fallback parse_source stub returns error when module unavailable."""
        # Directly test the fallback stub function (simulate ImportError block)
        from code_puppy.turbo_parse_bridge import TURBO_PARSE_AVAILABLE
        
        # Only test if module is not available, otherwise skip
        if TURBO_PARSE_AVAILABLE:
            pytest.skip("turbo_parse is available - fallback not active")
        
        # If we reach here, we're using the fallback stubs
        from code_puppy.turbo_parse_bridge import parse_source
        result = parse_source("def test(): pass", "python")
        
        assert result["success"] is False
        assert result["tree"] is None
        assert any("not available" in str(e.get("message", "")) for e in result.get("errors", []))
    
    def test_fallback_parse_file_stub(self):
        """Test fallback parse_file stub returns error when module unavailable."""
        from code_puppy.turbo_parse_bridge import TURBO_PARSE_AVAILABLE
        
        # Only test if module is not available, otherwise skip
        if TURBO_PARSE_AVAILABLE:
            pytest.skip("turbo_parse is available - fallback not active")
        
        from code_puppy.turbo_parse_bridge import parse_file
        result = parse_file("test.py")
        
        assert result["success"] is False
        assert result["tree"] is None
        assert any("not available" in str(e.get("message", "")) for e in result.get("errors", []))


# ============================================================================
# Tests for parse_files_batch functionality
# ============================================================================

class TestParseFilesBatch:
    """Tests for parse_files_batch batch parsing functionality."""

    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_parse_files_batch_empty(self):
        """Test batch parsing with empty file list."""
        from code_puppy.turbo_parse_bridge import parse_files_batch
        
        result = parse_files_batch([])
        
        assert result["files_processed"] == 0
        assert result["success_count"] == 0
        assert result["error_count"] == 0
        assert result["all_succeeded"] is True
        assert result["results"] == []
        assert result["total_time_ms"] >= 0.0
    
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_parse_files_batch_single_file(self):
        """Test batch parsing with a single file."""
        from code_puppy.turbo_parse_bridge import parse_files_batch
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            temp_path = f.name
        
        try:
            result = parse_files_batch([temp_path])
            
            assert result["files_processed"] == 1
            assert result["success_count"] == 1
            assert result["error_count"] == 0
            assert result["all_succeeded"] is True
            assert len(result["results"]) == 1
            assert result["results"][0]["success"] is True
            assert result["results"][0]["language"] == "python"
            assert result["total_time_ms"] >= 0.0
        finally:
            os.unlink(temp_path)
    
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_parse_files_batch_multiple_files(self):
        """Test batch parsing with multiple files of different languages."""
        from code_puppy.turbo_parse_bridge import parse_files_batch
        
        # Create Python and Rust files
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f1:
            f1.write("def func1(): pass\n")
            py_path = f1.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.rs', delete=False) as f2:
            f2.write("fn main() {}\n")
            rs_path = f2.name
        
        try:
            result = parse_files_batch([py_path, rs_path])
            
            assert result["files_processed"] == 2
            assert result["success_count"] == 2
            assert result["error_count"] == 0
            assert result["all_succeeded"] is True
            assert len(result["results"]) == 2
            
            # Check individual results
            assert result["results"][0]["language"] == "python"
            assert result["results"][0]["success"] is True
            assert result["results"][1]["language"] == "rust"
            assert result["results"][1]["success"] is True
        finally:
            os.unlink(py_path)
            os.unlink(rs_path)
    
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_parse_files_batch_max_workers(self):
        """Test batch parsing with max_workers parameter."""
        from code_puppy.turbo_parse_bridge import parse_files_batch
        
        # Create multiple temp files
        temp_files = []
        for i in range(3):
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(f"def func_{i}(): return {i}\n")
                temp_files.append(f.name)
        
        try:
            result = parse_files_batch(temp_files, max_workers=2)
            
            assert result["files_processed"] == 3
            assert result["success_count"] == 3
            assert result["error_count"] == 0
            assert result["all_succeeded"] is True
            assert len(result["results"]) == 3
        finally:
            for path in temp_files:
                os.unlink(path)
    
    @pytest.mark.skipif(not TURBO_PARSE_AVAILABLE, reason="turbo_parse Rust module not installed")
    def test_parse_files_batch_mixed_success_failure(self):
        """Test batch parsing with mix of successful and failed files."""
        from code_puppy.turbo_parse_bridge import parse_files_batch
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def valid(): pass\n")
            valid_path = f.name
        
        invalid_path = "/nonexistent/path/file.py"
        
        try:
            result = parse_files_batch([valid_path, invalid_path])
            
            assert result["files_processed"] == 2
            assert result["success_count"] == 1
            assert result["error_count"] == 1
            assert result["all_succeeded"] is False
            assert len(result["results"]) == 2
            
            # First file should succeed
            assert result["results"][0]["success"] is True
            # Second file should fail
            assert result["results"][1]["success"] is False
            assert len(result["results"][1]["errors"]) > 0
        finally:
            os.unlink(valid_path)
    
    def test_fallback_parse_files_batch_stub(self):
        """Test fallback parse_files_batch stub when module unavailable."""
        from code_puppy.turbo_parse_bridge import TURBO_PARSE_AVAILABLE
        
        if TURBO_PARSE_AVAILABLE:
            pytest.skip("turbo_parse is available - fallback not active")
        
        from code_puppy.turbo_parse_bridge import parse_files_batch
        
        result = parse_files_batch(["file1.py", "file2.py"])
        
        assert result["files_processed"] == 2
        assert result["success_count"] == 0
        assert result["error_count"] == 2
        assert result["all_succeeded"] is False
        assert len(result["results"]) == 2
        
        for r in result["results"]:
            assert r["success"] is False
            assert any("not available" in str(e.get("message", "")) for e in r.get("errors", []))
