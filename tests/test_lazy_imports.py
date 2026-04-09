"""Tests for lazy import functionality in code_puppy package."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest


class TestLazyPackageImports:
    """Test lazy package-level imports via __getattr__."""

    def test_import_code_puppy_succeeds(self):
        """Basic import should work without errors."""
        import code_puppy

        assert code_puppy is not None
        assert isinstance(code_puppy, ModuleType)

    def test_version_eagerly_available(self):
        """__version__ should be accessible eagerly (not lazy)."""
        import code_puppy

        version = code_puppy.__version__
        assert version is not None
        assert isinstance(version, str)
        assert len(version) > 0

    def test_lazy_agents_import(self):
        """Accessing code_puppy.agents should trigger lazy import."""
        import code_puppy

        agents_mod = code_puppy.agents
        assert isinstance(agents_mod, ModuleType)
        assert agents_mod.__name__ == "code_puppy.agents"

    def test_lazy_agents_cached(self):
        """Second access should return same module (cached)."""
        import code_puppy

        first = code_puppy.agents
        second = code_puppy.agents
        assert first is second

    def test_invalid_attribute_raises(self):
        """Accessing non-existent attribute should raise AttributeError."""
        import code_puppy

        with pytest.raises(AttributeError):
            _ = code_puppy.nonexistent_xyz

    def test_dir_includes_lazy(self):
        """dir(code_puppy) should include lazy-loaded names."""
        import code_puppy

        names = dir(code_puppy)
        assert "agents" in names
        assert "messaging" in names
        assert "__version__" in names


class TestHeavyModulesNotImportedEagerly:
    """Test that heavy modules are NOT imported during simple package import."""

    def test_simple_import_fast(self):
        """Simple import should not load heavy deps."""
        # Clear pydantic from modules if present
        pydantic_mods = [k for k in sys.modules.keys() if k.startswith("pydantic")]
        for mod in pydantic_mods:
            del sys.modules[mod]

        import code_puppy

        _ = code_puppy.__version__

        pydantic_loaded = any(k.startswith("pydantic") for k in sys.modules.keys())
        assert not pydantic_loaded
