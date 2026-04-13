"""Python 3.14 compatibility tests.

Ensures all core modules import without NameError or SyntaxError,
verifying forward references and modern type syntax work correctly.
"""

import pytest


class TestCoreModuleImports:
    """Test that core modules with forward references import correctly."""

    def test_run_context_imports(self):
        """run_context.py uses RunContext | None before class definition."""
        import code_puppy.run_context
        
        # Verify key exports
        assert hasattr(code_puppy.run_context, 'RunContext')
        assert hasattr(code_puppy.run_context, 'get_current_run_context')
        assert hasattr(code_puppy.run_context, 'RunContextManager')

    def test_concurrency_limits_imports(self):
        """concurrency_limits.py uses TrackedSemaphore | None before definition."""
        import code_puppy.concurrency_limits
        
        # Verify key exports
        assert hasattr(code_puppy.concurrency_limits, 'TrackedSemaphore')
        assert hasattr(code_puppy.concurrency_limits, 'ConcurrencyConfig')
        assert hasattr(code_puppy.concurrency_limits, 'FileOpsLimiter')

    def test_callbacks_imports(self):
        """callbacks.py uses PEP 695 type alias syntax."""
        import code_puppy.callbacks
        
        # Verify key exports
        assert hasattr(code_puppy.callbacks, 'register_callback')
        assert hasattr(code_puppy.callbacks, 'on_startup')
        assert hasattr(code_puppy.callbacks, 'on_shutdown')

    def test_agent_manager_imports(self):
        """agent_manager.py with session ID fix."""
        import code_puppy.agents.agent_manager
        
        # Verify the function exists and returns expected format
        session_id = code_puppy.agents.agent_manager.get_terminal_session_id()
        assert session_id.startswith('session_')
        # New format: session_{ppid}_{pid}
        parts = session_id.split('_')
        assert len(parts) == 3, f"Expected session_ppid_pid format, got {session_id}"


class TestCodeContextPackage:
    """Test that code_context package works after removing shadowed module."""

    def test_code_context_package_imports(self):
        """Verify code_context package exports work."""
        from code_puppy.code_context import (
            CodeContext,
            CodeExplorer,
            FileOutline,
            SymbolInfo,
        )
        
        assert CodeContext is not None
        assert CodeExplorer is not None
        assert FileOutline is not None
        assert SymbolInfo is not None
