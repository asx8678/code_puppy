"""Shared pytest fixtures for plugin tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Generator
from unittest import mock

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.models import ModelRequestParameters


# Workaround for pydantic/MCP compatibility issue during pytest collection:
# Skip antigravity tests if pydantic/MCP conflict is detected
def pytest_configure(config):
    """Configure pytest with compatibility workarounds."""
    # Pre-patch sys.modules to provide a mock mcp.types during collection
    # This prevents the ValueError in pydantic's RootModel metaclass
    if "mcp" not in sys.modules:
        mcp_mock = MagicMock()
        mcp_mock.types = MagicMock()
        sys.modules["mcp"] = mcp_mock
        sys.modules["mcp.types"] = mcp_mock.types
        sys.modules["mcp.client"] = MagicMock()
        sys.modules["mcp.client.session"] = MagicMock()


class ClientShim:
    """A shim that makes client._api_client._async_httpx_client point to model._http_client."""

    def __init__(self, model):
        self._model = model
        self._api_client = ApiClientShim(model)


class ApiClientShim:
    """Inner shim for _api_client."""

    def __init__(self, model):
        self._model = model

    @property
    def _async_httpx_client(self):
        return self._model._http_client

    @_async_httpx_client.setter
    def _async_httpx_client(self, value):
        self._model._http_client = value


@pytest.fixture
def mock_google_model():
    """Create a mock AntigravityModel instance for testing."""
    # Lazy import to avoid pydantic/MCP conflicts during conftest load
    from code_puppy.plugins.antigravity_oauth.antigravity_model import AntigravityModel

    # Create the model with required api_key
    model = AntigravityModel(
        model_name="gemini-1.5-pro",
        api_key="test-api-key",
        base_url="https://generativelanguage.googleapis.com/v1beta",
    )

    # Set up an initial mock HTTP client
    model._http_client = AsyncMock()

    # Create a shim that keeps client._api_client._async_httpx_client in sync with _http_client
    model.client = ClientShim(model)

    return model


@pytest.fixture
def mock_httpx_client() -> AsyncMock:
    """Create a mock httpx client."""
    return AsyncMock()


@pytest.fixture
def model_request_params() -> ModelRequestParameters:
    """Create model request parameters fixture."""
    return ModelRequestParameters(
        function_tools=[],
    )


# ============================================================================
# Turbo Parse Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def turbo_parse_available() -> bool:
    """Detect if the turbo_parse Rust module is available.

    Returns True if the turbo_parse module is installed and functional,
    False otherwise.
    """
    return importlib.util.find_spec("turbo_parse") is not None


@pytest.fixture
def mock_turbo_parse_present() -> Generator[mock.MagicMock, None, None]:
    """Fixture that mocks the turbo_parse module as present.

    This is useful for testing the Rust-available path without requiring
    the actual Rust module to be installed.

    Yields:
        MagicMock: A mock turbo_parse module with realistic behavior.
    """
    # Create a realistic mock of the turbo_parse module
    mock_module = mock.MagicMock()
    mock_module.__version__ = "1.0.0-mock"
    mock_module.health_check.return_value = {
        "available": True,
        "version": "1.0.0-mock",
        "languages": ["python", "rust", "javascript", "typescript", "tsx", "elixir"],
        "cache_available": True,
    }
    mock_module.stats.return_value = {
        "total_parses": 42,
        "average_parse_time_ms": 5.0,
        "languages_used": {"python": 30, "rust": 12},
        "cache_hits": 35,
        "cache_misses": 7,
        "cache_evictions": 0,
        "cache_hit_ratio": 0.83,
    }
    mock_module.is_language_supported.return_value = True
    mock_module.supported_languages.return_value = {
        "languages": ["python", "rust", "javascript", "typescript", "tsx", "elixir"],
        "count": 6,
    }
    mock_module.get_language.return_value = {
        "name": "python",
        "supported": True,
        "version": "3.x",
    }

    # Mock parsing functions with realistic responses
    def mock_parse_source(source: str, language: str) -> dict:
        return {
            "language": language,
            "tree": {"type": "module", "children": []},
            "parse_time_ms": 5.0,
            "success": True,
            "errors": [],
        }

    def mock_parse_file(path: str, language: str | None = None) -> dict:
        return {
            "language": language or Path(path).suffix.lstrip(".") or "unknown",
            "tree": {"type": "module", "children": []},
            "parse_time_ms": 8.0,
            "success": True,
            "errors": [],
        }

    def mock_parse_files_batch(paths, max_workers=None, timeout_ms=None) -> dict:
        return {
            "results": [
                {
                    "file_path": p,
                    "language": Path(p).suffix.lstrip(".") or "unknown",
                    "tree": {"type": "module"},
                    "parse_time_ms": 7.0,
                    "success": True,
                    "errors": [],
                }
                for p in paths
            ],
            "total_time_ms": len(paths) * 7.0,
            "files_processed": len(paths),
            "success_count": len(paths),
            "error_count": 0,
            "all_succeeded": True,
        }

    def mock_extract_symbols(source: str, language: str) -> dict:
        return {
            "symbols": [
                {
                    "name": "test_func",
                    "kind": "function",
                    "start_line": 1,
                    "end_line": 2,
                },
            ],
            "extraction_time_ms": 2.0,
            "success": True,
        }

    def mock_extract_symbols_from_file(path: str, language: str | None = None) -> dict:
        return {
            "symbols": [
                {
                    "name": "test_func",
                    "kind": "function",
                    "start_line": 1,
                    "end_line": 2,
                },
            ],
            "extraction_time_ms": 2.0,
            "success": True,
        }

    def mock_extract_syntax_diagnostics(source: str, language: str) -> dict:
        return {
            "diagnostics": [],
            "error_count": 0,
            "warning_count": 0,
        }

    mock_module.parse_source = mock_parse_source
    mock_module.parse_file = mock_parse_file
    mock_module.parse_files_batch = mock_parse_files_batch
    mock_module.extract_symbols = mock_extract_symbols
    mock_module.extract_symbols_from_file = mock_extract_symbols_from_file
    mock_module.extract_syntax_diagnostics = mock_extract_syntax_diagnostics

    # Add the mock to sys.modules
    with mock.patch.dict("sys.modules", {"turbo_parse": mock_module}):
        # Also mock find_spec to return a valid spec
        mock_spec = mock.MagicMock()
        with mock.patch("importlib.util.find_spec", return_value=mock_spec):
            yield mock_module


@pytest.fixture
def mock_turbo_parse_absent() -> Generator[None, None, None]:
    """Fixture that ensures turbo_parse is unavailable.

    This is useful for testing the fallback path even if the actual
    turbo_parse Rust module is installed.
    """
    # Remove turbo_parse from sys.modules if present
    original_module = sys.modules.pop("turbo_parse", None)

    # Mock find_spec to return None (module not found)
    with mock.patch("importlib.util.find_spec", return_value=None):
        yield

    # Restore original module if it was present
    if original_module:
        sys.modules["turbo_parse"] = original_module


@pytest.fixture
def disable_turbo_parse() -> Generator[None, None, None]:
    """Fixture to temporarily disable turbo_parse for fallback testing.

    Unlike mock_turbo_parse_absent which mocks module discovery,
    this fixture works with the already-imported bridge module.

    Example:
        def test_something(disable_turbo_parse):
            # turbo_parse is temporarily disabled here
            result = parse_source("def test(): pass", "python")
            # result will show fallback behavior
    """
    from code_puppy import turbo_parse_bridge

    # Save original state
    original_available = turbo_parse_bridge.TURBO_PARSE_AVAILABLE
    original_enabled = turbo_parse_bridge._turbo_parse_user_enabled

    # Disable at both levels
    turbo_parse_bridge.TURBO_PARSE_AVAILABLE = False
    turbo_parse_bridge._turbo_parse_user_enabled = False

    yield

    # Restore original state
    turbo_parse_bridge.TURBO_PARSE_AVAILABLE = original_available
    turbo_parse_bridge._turbo_parse_user_enabled = original_enabled


@pytest.fixture
def test_python_file(tmp_path: Path) -> str:
    """Create a temporary Python file for testing.

    Returns:
        str: Path to the created temporary file.
    """
    test_file = tmp_path / "test_code.py"
    test_file.write_text("""
def hello():
    \"\"\"A greeting function.\"\"\"
    return "Hello, World!"

class MyClass:
    def method(self):
        return 42
""")
    return str(test_file)


@pytest.fixture
def test_rust_file(tmp_path: Path) -> str:
    """Create a temporary Rust file for testing.

    Returns:
        str: Path to the created temporary file.
    """
    test_file = tmp_path / "test_code.rs"
    test_file.write_text("""
fn main() {
    println!("Hello, Rust!");
}

fn add(a: i32, b: i32) -> i32 {
    a + b
}
""")
    return str(test_file)


@pytest.fixture
def test_javascript_file(tmp_path: Path) -> str:
    """Create a temporary JavaScript file for testing.

    Returns:
        str: Path to the created temporary file.
    """
    test_file = tmp_path / "test_code.js"
    test_file.write_text("""
function greet(name) {
    return `Hello, ${name}!`;
}

const double = (x) => x * 2;
""")
    return str(test_file)
