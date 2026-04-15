"""Regression tests for bd-111: repo_index status misreports Elixir backend.

Ensures get_indexer_status() reports the actual repo_index backend source,
not the file_ops source.
"""

import pytest

from code_puppy.native_backend import BackendPreference, NativeBackend


@pytest.fixture(autouse=True)
def _reset_native_backend():
    """Reset NativeBackend state between tests."""
    saved = {
        "_last_source": dict(NativeBackend._last_source),
        "_backend_preference": NativeBackend._backend_preference,
    }
    yield
    NativeBackend._last_source = saved["_last_source"]
    NativeBackend._backend_preference = saved["_backend_preference"]


def _import_get_indexer_status():
    from code_puppy.plugins.repo_compass.turbo_indexer_bridge import (
        get_indexer_status,
    )

    return get_indexer_status


def test_indexer_status_python_only_mode():
    """PYTHON_ONLY => backend should be 'python'."""
    get_indexer_status = _import_get_indexer_status()
    NativeBackend._backend_preference = BackendPreference.PYTHON_ONLY
    NativeBackend._last_source[NativeBackend.Capabilities.REPO_INDEX] = "python"

    status = get_indexer_status()

    assert status["backend"] == "python"


def test_indexer_status_elixir_success():
    """When _last_source[REPO_INDEX] = 'elixir', backend should be 'elixir'."""
    get_indexer_status = _import_get_indexer_status()
    NativeBackend._last_source[NativeBackend.Capabilities.REPO_INDEX] = "elixir"

    status = get_indexer_status()

    assert status["backend"] == "elixir"


def test_indexer_status_elixir_available_but_repo_index_fallback():
    """Elixir configured/available but repo_index fell back to Python => backend python.

    This is the core bd-111 scenario: Elixir is generally available (e.g. for
    file_ops), but repo_index specifically used Python. The old code called
    _get_file_ops_source() which would report 'elixir' — wrong.
    """
    get_indexer_status = _import_get_indexer_status()
    NativeBackend._backend_preference = BackendPreference.ELIXIR_FIRST
    # Simulate: elixir is available for file_ops but repo_index fell back
    NativeBackend._last_source[NativeBackend.Capabilities.REPO_INDEX] = "python"

    status = get_indexer_status()

    assert status["backend"] == "python", (
        "bd-111: Must report 'python' when repo_index fell back, "
        "even if Elixir is generally available"
    )


def test_indexer_status_has_elixir_available_field():
    """Result dict should contain elixir_available, not rust_available."""
    get_indexer_status = _import_get_indexer_status()
    NativeBackend._last_source[NativeBackend.Capabilities.REPO_INDEX] = "python"

    status = get_indexer_status()

    assert "elixir_available" in status
    assert "rust_available" not in status


def test_indexer_status_no_rust_available_field():
    """The misleading rust_available field must be removed (bd-111)."""
    get_indexer_status = _import_get_indexer_status()

    status = get_indexer_status()

    assert "rust_available" not in status
