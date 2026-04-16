"""Comprehensive tests for GAC (Git Auto Commit) Context Guard.

Tests the fail-closed safety mechanisms that prevent git mutations in unsafe contexts:
- Sub-agent contexts (depth >= 1)
- Non-interactive terminals (no TTY)
- Nested agent contexts (depth > 1)

All tests use mocking to avoid depending on actual execution context.
"""

import asyncio
import inspect
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.plugins.git_auto_commit.context_guard import (
    GACContextError,
    REASON_NON_INTERACTIVE,
    REASON_NESTED_AGENT,
    REASON_SUBAGENT,
    check_gac_context,
    is_gac_safe,
    require_interactive_context,
)


class TestGACContextError:
    """Test GACContextError exception class."""

    def test_inherits_from_runtime_error(self):
        """GACContextError should inherit from RuntimeError."""
        err = GACContextError("test message")
        assert isinstance(err, RuntimeError)

    def test_stores_reason_attribute(self):
        """Error should store the reason attribute."""
        err = GACContextError("test", reason=REASON_SUBAGENT)
        assert err.reason == REASON_SUBAGENT

    def test_stores_agent_name_attribute(self):
        """Error should store the agent_name attribute."""
        err = GACContextError("test", agent_name="retriever")
        assert err.agent_name == "retriever"

    def test_stores_depth_attribute(self):
        """Error should store the depth attribute."""
        err = GACContextError("test", depth=2)
        assert err.depth == 2

    def test_all_attributes_together(self):
        """Error should store all attributes together."""
        err = GACContextError(
            "test message",
            reason=REASON_NESTED_AGENT,
            agent_name="terrier",
            depth=3,
        )
        assert err.reason == REASON_NESTED_AGENT
        assert err.agent_name == "terrier"
        assert err.depth == 3
        assert str(err) == "test message"


class TestCheckGacContextSafe:
    """Test check_gac_context() passes in safe contexts."""

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_passes_in_safe_context(self, mock_stdin, mock_is_subagent):
        """Should pass silently in main agent + TTY context."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.return_value = True

        # Should not raise
        result = check_gac_context()
        assert result is None


class TestCheckGacContextSubagent:
    """Test check_gac_context() raises in sub-agent contexts."""

    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_depth")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_name")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_raises_in_subagent_context(
        self, mock_stdin, mock_is_subagent, mock_get_name, mock_get_depth
    ):
        """Should raise GACContextError when is_subagent() returns True."""
        mock_is_subagent.return_value = True
        mock_get_name.return_value = "retriever"
        mock_get_depth.return_value = 1
        mock_stdin.isatty.return_value = True

        with pytest.raises(GACContextError) as exc_info:
            check_gac_context()

        assert REASON_SUBAGENT in str(exc_info.value)
        assert "retriever" in str(exc_info.value)
        assert "depth=1" in str(exc_info.value)
        assert exc_info.value.reason == REASON_SUBAGENT
        assert exc_info.value.agent_name == "retriever"
        assert exc_info.value.depth == 1

    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_depth")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_name")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_error_includes_actionable_message(
        self, mock_stdin, mock_is_subagent, mock_get_name, mock_get_depth
    ):
        """Error message should tell user what to do."""
        mock_is_subagent.return_value = True
        mock_get_name.return_value = "code-puppy"
        mock_get_depth.return_value = 1
        mock_stdin.isatty.return_value = True

        with pytest.raises(GACContextError) as exc_info:
            check_gac_context()

        error_msg = str(exc_info.value)
        assert "GAC refused" in error_msg
        assert "running in" in error_msg
        assert "Git mutations require" in error_msg
        assert "Run this command from the main agent" in error_msg

    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_depth")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_name")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_nested_agent_context_depth_greater_than_one(
        self, mock_stdin, mock_is_subagent, mock_get_name, mock_get_depth
    ):
        """Should report nested agent reason when depth > 1."""
        mock_is_subagent.return_value = True
        mock_get_name.return_value = "terrier"
        mock_get_depth.return_value = 2
        mock_stdin.isatty.return_value = True

        with pytest.raises(GACContextError) as exc_info:
            check_gac_context()

        assert exc_info.value.reason == REASON_NESTED_AGENT
        assert "depth=2" in str(exc_info.value)
        assert "nested" in str(exc_info.value).lower()

    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_depth")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_name")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_very_deeply_nested_agent(
        self, mock_stdin, mock_is_subagent, mock_get_name, mock_get_depth
    ):
        """Should handle deeply nested agents (depth >> 1)."""
        mock_is_subagent.return_value = True
        mock_get_name.return_value = "deep_agent"
        mock_get_depth.return_value = 5
        mock_stdin.isatty.return_value = True

        with pytest.raises(GACContextError) as exc_info:
            check_gac_context()

        assert exc_info.value.reason == REASON_NESTED_AGENT
        assert "depth=5" in str(exc_info.value)

    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_depth")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_name")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_subagent_without_name(
        self, mock_stdin, mock_is_subagent, mock_get_name, mock_get_depth
    ):
        """Should handle sub-agent with no name."""
        mock_is_subagent.return_value = True
        mock_get_name.return_value = None
        mock_get_depth.return_value = 1
        mock_stdin.isatty.return_value = True

        with pytest.raises(GACContextError) as exc_info:
            check_gac_context()

        # Should not crash, just have no agent info
        assert "None" not in str(exc_info.value)  # No raw None in message


class TestCheckGacContextNonInteractive:
    """Test check_gac_context() raises in non-interactive contexts."""

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_raises_when_not_tty(self, mock_stdin, mock_is_subagent):
        """Should raise GACContextError when isatty() returns False."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.return_value = False

        with pytest.raises(GACContextError) as exc_info:
            check_gac_context()

        assert REASON_NON_INTERACTIVE in str(exc_info.value)
        assert exc_info.value.reason == REASON_NON_INTERACTIVE

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_non_interactive_error_is_actionable(self, mock_stdin, mock_is_subagent):
        """Non-interactive error should tell user to use interactive terminal."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.return_value = False

        with pytest.raises(GACContextError) as exc_info:
            check_gac_context()

        error_msg = str(exc_info.value)
        assert "GAC refused" in error_msg
        assert "interactive TTY" in error_msg
        assert "Run this command in an interactive terminal" in error_msg


class TestCheckGacContextFailClosed:
    """Test fail-closed behavior when detection fails."""

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_fails_closed_if_is_subagent_raises(self, mock_stdin, mock_is_subagent):
        """Should raise if is_subagent() raises an exception."""
        mock_is_subagent.side_effect = RuntimeError("context var error")
        mock_stdin.isatty.return_value = True

        with pytest.raises(GACContextError) as exc_info:
            check_gac_context()

        assert "unable to verify" in str(exc_info.value)
        assert "RuntimeError" in str(exc_info.value)

    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_depth")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_fails_closed_if_get_depth_raises(
        self, mock_stdin, mock_is_subagent, mock_get_depth
    ):
        """Should raise if get_subagent_depth() raises an exception."""
        mock_is_subagent.return_value = True
        mock_get_depth.side_effect = AttributeError("missing context")
        mock_stdin.isatty.return_value = True

        with pytest.raises(GACContextError) as exc_info:
            check_gac_context()

        assert "unable to verify" in str(exc_info.value)

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_fails_closed_if_isatty_raises(self, mock_stdin, mock_is_subagent):
        """Should raise if isatty() raises an exception."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.side_effect = OSError("bad file descriptor")

        with pytest.raises(GACContextError) as exc_info:
            check_gac_context()

        assert "unable to verify terminal interactivity" in str(exc_info.value)
        assert "OSError" in str(exc_info.value)

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_fails_closed_if_stdin_has_no_isatty(self, mock_stdin, mock_is_subagent):
        """Should raise if stdin doesn't have isatty method."""
        mock_is_subagent.return_value = False
        del mock_stdin.isatty  # Remove the attribute

        with pytest.raises(GACContextError) as exc_info:
            check_gac_context()

        assert "unable to verify terminal interactivity" in str(exc_info.value)
        assert "AttributeError" in str(exc_info.value)


class TestIsGacSafe:
    """Test is_gac_safe() function - non-exception version."""

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_returns_true_none_in_safe_context(self, mock_stdin, mock_is_subagent):
        """Should return (True, None) in safe context."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.return_value = True

        is_safe, reason = is_gac_safe()

        assert is_safe is True
        assert reason is None

    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_depth")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_name")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_returns_false_reason_in_subagent(
        self, mock_stdin, mock_is_subagent, mock_get_name, mock_get_depth
    ):
        """Should return (False, reason) in sub-agent context."""
        mock_is_subagent.return_value = True
        mock_get_name.return_value = "retriever"
        mock_get_depth.return_value = 1
        mock_stdin.isatty.return_value = True

        is_safe, reason = is_gac_safe()

        assert is_safe is False
        assert reason is not None
        assert "retriever" in reason
        assert "depth=1" in reason

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_returns_false_reason_non_interactive(self, mock_stdin, mock_is_subagent):
        """Should return (False, reason) in non-interactive context."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.return_value = False

        is_safe, reason = is_gac_safe()

        assert is_safe is False
        assert reason == REASON_NON_INTERACTIVE

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_returns_false_on_detection_error(self, mock_stdin, mock_is_subagent):
        """Should return (False, reason) when detection fails."""
        mock_is_subagent.side_effect = RuntimeError("detection failed")
        mock_stdin.isatty.return_value = True

        is_safe, reason = is_gac_safe()

        assert is_safe is False
        assert "detection failed" in reason
        assert "RuntimeError" in reason

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_returns_false_on_tty_detection_error(self, mock_stdin, mock_is_subagent):
        """Should return (False, reason) when TTY detection fails."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.side_effect = OSError("bad fd")

        is_safe, reason = is_gac_safe()
        assert is_safe is False
        assert "detection failed" in reason.lower() or "terminal" in reason.lower()


class TestRequireInteractiveContextDecorator:
    """Test @require_interactive_context decorator."""

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_decorated_sync_function_runs_in_safe_context(
        self, mock_stdin, mock_is_subagent
    ):
        """Decorated sync function should run normally in safe context."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.return_value = True

        @require_interactive_context
        def my_git_operation():
            return "committed"

        result = my_git_operation()
        assert result == "committed"

    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_depth")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_name")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_decorated_sync_function_raises_in_subagent(
        self, mock_stdin, mock_is_subagent, mock_get_name, mock_get_depth
    ):
        """Decorated sync function should raise in sub-agent context."""
        mock_is_subagent.return_value = True
        mock_get_name.return_value = "retriever"
        mock_get_depth.return_value = 1
        mock_stdin.isatty.return_value = True

        @require_interactive_context
        def my_git_operation():
            return "committed"

        with pytest.raises(GACContextError):
            my_git_operation()

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_decorated_sync_function_raises_non_interactive(
        self, mock_stdin, mock_is_subagent
    ):
        """Decorated sync function should raise in non-interactive context."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.return_value = False

        @require_interactive_context
        def my_git_operation():
            return "committed"

        with pytest.raises(GACContextError):
            my_git_operation()

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_decorated_async_function_runs_in_safe_context(
        self, mock_stdin, mock_is_subagent
    ):
        """Decorated async function should run normally in safe context."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.return_value = True

        @require_interactive_context
        async def my_async_git_operation():
            await asyncio.sleep(0.001)
            return "async committed"

        result = asyncio.run(my_async_git_operation())
        assert result == "async committed"

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_decorated_async_function_raises_non_interactive(
        self, mock_stdin, mock_is_subagent
    ):
        """Decorated async function should raise in non-interactive context."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.return_value = False

        @require_interactive_context
        async def my_async_git_operation():
            await asyncio.sleep(0.001)
            return "async committed"

        with pytest.raises(GACContextError):
            asyncio.run(my_async_git_operation())

    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_depth")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.get_subagent_name")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_decorated_async_function_raises_in_subagent(
        self, mock_stdin, mock_is_subagent, mock_get_name, mock_get_depth
    ):
        """Decorated async function should raise in sub-agent context."""
        mock_is_subagent.return_value = True
        mock_get_name.return_value = "retriever"
        mock_get_depth.return_value = 1
        mock_stdin.isatty.return_value = True

        @require_interactive_context
        async def my_async_git_operation():
            await asyncio.sleep(0.001)
            return "async committed"

        with pytest.raises(GACContextError):
            asyncio.run(my_async_git_operation())

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_decorator_preserves_function_metadata(self, mock_stdin, mock_is_subagent):
        """Decorator should preserve __name__, __doc__, etc."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.return_value = True

        @require_interactive_context
        def my_git_operation(arg1: str, arg2: int = 10) -> str:
            """My docstring."""
            return f"{arg1}: {arg2}"

        assert my_git_operation.__name__ == "my_git_operation"
        assert my_git_operation.__doc__ == "My docstring."

        # Check signature is preserved
        sig = inspect.signature(my_git_operation)
        params = list(sig.parameters.keys())
        assert "arg1" in params
        assert "arg2" in params

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_decorated_function_passes_args_correctly(
        self, mock_stdin, mock_is_subagent
    ):
        """Decorator should correctly pass through all arguments."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.return_value = True

        @require_interactive_context
        def my_git_operation(message: str, amend: bool = False, **kwargs):
            return {"message": message, "amend": amend, "extra": kwargs}

        result = my_git_operation("test commit", amend=True, author="test")
        assert result["message"] == "test commit"
        assert result["amend"] is True
        assert result["extra"] == {"author": "test"}


class TestIntegrationPatterns:
    """Integration-style tests for common usage patterns."""

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_check_then_proceed_pattern(self, mock_stdin, mock_is_subagent):
        """Common pattern: check safety, then proceed if safe."""
        mock_is_subagent.return_value = False
        mock_stdin.isatty.return_value = True

        # Pattern: check safety first
        is_safe, reason = is_gac_safe()
        if not is_safe:
            raise RuntimeError(f"Unsafe: {reason}")

        # Then do the operation
        check_gac_context()
        # ... git operation would go here ...

    @patch("code_puppy.plugins.git_auto_commit.context_guard.is_subagent")
    @patch("code_puppy.plugins.git_auto_commit.context_guard.sys.stdin")
    def test_early_return_pattern(self, mock_stdin, mock_is_subagent):
        """Common pattern: early return if unsafe."""
        mock_is_subagent.return_value = True
        mock_get_name = MagicMock(return_value="retriever")
        mock_get_depth = MagicMock(return_value=1)

        def git_auto_commit():
            is_safe, reason = is_gac_safe()
            if not is_safe:
                # Early return with helpful message
                return {"success": False, "error": reason, "skipped": True}
            # ... would proceed with commit ...
            return {"success": True}

        with patch(
            "code_puppy.plugins.git_auto_commit.context_guard.get_subagent_name",
            mock_get_name,
        ):
            with patch(
                "code_puppy.plugins.git_auto_commit.context_guard.get_subagent_depth",
                mock_get_depth,
            ):
                result = git_auto_commit()
                assert result["success"] is False
                assert result["skipped"] is True
                assert "retriever" in result["error"]


class TestConstants:
    """Test module constants."""

    def test_reason_constants_exist(self):
        """REASON_* constants should be defined and be strings."""
        assert isinstance(REASON_SUBAGENT, str)
        assert isinstance(REASON_NON_INTERACTIVE, str)
        assert isinstance(REASON_NESTED_AGENT, str)

    def test_reason_constants_are_descriptive(self):
        """REASON_* constants should be human-readable."""
        assert (
            "sub-agent" in REASON_SUBAGENT.lower()
            or "context" in REASON_SUBAGENT.lower()
        )
        assert (
            "interactive" in REASON_NON_INTERACTIVE.lower()
            or "terminal" in REASON_NON_INTERACTIVE.lower()
        )
        assert (
            "nested" in REASON_NESTED_AGENT.lower()
            or "agent" in REASON_NESTED_AGENT.lower()
        )


class TestExports:
    """Test module exports."""

    def test_all_symbols_exported_from_init(self):
        """All expected symbols should be importable from __init__."""
        from code_puppy.plugins.git_auto_commit import (
            GACContextError,
            REASON_NON_INTERACTIVE,  # noqa: F401
            REASON_NESTED_AGENT,  # noqa: F401
            REASON_SUBAGENT,
            check_gac_context,
            is_gac_safe,
            require_interactive_context,
        )

        # Just verify they exist and are the right types
        assert GACContextError is not None
        assert isinstance(REASON_SUBAGENT, str)
        assert callable(check_gac_context)
        assert callable(is_gac_safe)
        assert callable(require_interactive_context)
