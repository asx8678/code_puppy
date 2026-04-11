"""Smoke tests for critical module imports.

These tests catch forward-reference and import-time errors that can
block the application from starting. See BUG-01 in the security audit.
"""

import pytest


class TestImportSmoke:
    """Verify critical modules import without errors."""

    def test_session_storage_imports(self):
        """BUG-01: session_storage must import without NameError.
        
        The module uses SessionHistory and TokenEstimator type aliases
        in function annotations before they are defined. This requires
        `from __future__ import annotations` for deferred evaluation.
        """
        import code_puppy.session_storage
        
        # Verify the type aliases exist
        assert hasattr(code_puppy.session_storage, 'SessionHistory')
        assert hasattr(code_puppy.session_storage, 'TokenEstimator')

    def test_config_imports(self):
        """config.py eagerly imports from session_storage.
        
        This test catches any import-time failures that propagate
        through the config module's import chain.
        """
        import code_puppy.config

    def test_main_imports(self):
        """Verify the main entry point imports cleanly."""
        import code_puppy.main

    def test_turbo_executor_orchestrator_imports(self):
        """Verify turbo_executor orchestrator imports.
        
        This module has optional turbo_ops imports that should
        gracefully fall back if Rust modules aren't available.
        """
        from code_puppy.plugins.turbo_executor import orchestrator
        
        # Should have the availability flag
        assert hasattr(orchestrator, 'TURBO_OPS_AVAILABLE')
