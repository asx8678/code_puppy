"""Test coverage for app_runner.py entry points.

This module covers:
- Entry point modules (__main__.py, main.py)
- main_entry() function tests
"""

from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Entry Point Module Tests
# =============================================================================


class TestEntryPoints:
    """Test __main__.py and main.py entry point modules."""

    def test_main_py_imports(self):
        """Test that main.py can be imported and exports main_entry."""
        # Must import from cli_runner due to import-time side effects
        from code_puppy.main import main_entry

        assert callable(main_entry)

    def test_main_py_module_execution(self):
        """Test main.py __name__ == '__main__' branch is covered."""
        # We can't actually run the __main__ block, but we can verify the structure
        import code_puppy.main as main_module

        # The file should have main_entry callable
        assert hasattr(main_module, "main_entry")

    def test_dunder_main_module_execution(self):
        """Test __main__.py imports main_entry from main module."""
        from code_puppy.__main__ import main_entry

        assert callable(main_entry)


# =============================================================================
# CLI Entry Points Direct Tests
# =============================================================================


class TestMainEntry:
    """Test main_entry() function for proper entry point coverage."""

    @patch("asyncio.run")
    def test_main_entry_normal_execution(self, mock_run):
        """Test main_entry() under normal execution."""
        from code_puppy.cli_runner import main_entry

        mock_run.return_value = None
        with patch("code_puppy.cli_runner.reset_unix_terminal"):
            main_entry()

        mock_run.assert_called_once()

    @patch("asyncio.run", side_effect=KeyboardInterrupt)
    def test_main_entry_keyboard_interrupt_no_dbos(self, mock_run):
        """Test main_entry() with KeyboardInterrupt when DBOS is disabled."""
        from code_puppy.cli_runner import main_entry

        with patch("code_puppy.cli_runner.reset_unix_terminal"):
            with patch("code_puppy.cli_runner.get_use_dbos", return_value=False):
                result = main_entry()

        assert result == 0

    @patch("asyncio.run", side_effect=KeyboardInterrupt)
    def test_main_entry_keyboard_interrupt_with_dbos(self, mock_run):
        """Test main_entry() with KeyboardInterrupt when DBOS is enabled."""
        from code_puppy.cli_runner import main_entry

        mock_dbos_module = MagicMock()
        mock_dbos_cls = MagicMock()
        mock_dbos_module.DBOS = mock_dbos_cls

        with patch("code_puppy.cli_runner.reset_unix_terminal"):
            with patch("code_puppy.cli_runner.get_use_dbos", return_value=True):
                with patch.dict("sys.modules", {"dbos": mock_dbos_module}):
                    result = main_entry()

        assert result == 0
        mock_dbos_cls.destroy.assert_called_once()

    @patch("asyncio.run", side_effect=RuntimeError("unexpected"))
    def test_main_entry_unexpected_error(self, mock_run):
        """Test main_entry() with unexpected error."""
        from code_puppy.cli_runner import main_entry

        with patch("code_puppy.cli_runner.reset_unix_terminal"):
            # Should propagate the error (no return value in that branch)
            with pytest.raises(RuntimeError, match="unexpected"):
                main_entry()
