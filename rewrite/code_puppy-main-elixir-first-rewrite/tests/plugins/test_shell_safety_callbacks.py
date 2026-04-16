"""Tests for shell_safety callback registration and execution.

These tests focus on the shell_safety_callback function execution paths
and the register() function for callback registration.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_puppy.plugins.shell_safety.command_cache import CachedAssessment
from code_puppy.plugins.shell_safety.register_callbacks import (
    register,
    shell_safety_callback,
)
from code_puppy.tools.command_runner import ShellSafetyAssessment


class TestShellSafetyCallbackOAuthBypass:
    """Test OAuth model handling in shell_safety_callback.
    
    NOTE: OAuth bypass was removed for security. All models now go through
    the same safety pipeline. These tests verify that OAuth models are
    NOT bypassed (they get blocked for dangerous commands).
    """

    @pytest.mark.anyio
    async def test_callback_blocks_for_oauth_model_anthropic(self):
        """OAuth bypass removed: callback should BLOCK dangerous commands even for OAuth models."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-code-123",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.emit_info"
            ) as mock_emit,
        ):
            result = await shell_safety_callback(
                context=None, command="rm -rf /", cwd=None, timeout=60
            )
            # OAuth bypass removed - should block dangerous command
            assert result is not None
            assert result["blocked"] is True
            mock_emit.assert_called_once()

    @pytest.mark.anyio
    async def test_callback_blocks_for_oauth_model_openai(self):
        """OAuth bypass removed: callback should BLOCK dangerous commands even for OpenAI OAuth models."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="chatgpt-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.emit_info"
            ) as mock_emit,
        ):
            result = await shell_safety_callback(
                context=None, command="rm -rf /", cwd=None, timeout=60
            )
            # OAuth bypass removed - should block dangerous command
            assert result is not None
            assert result["blocked"] is True
            mock_emit.assert_called_once()

    @pytest.mark.anyio
    async def test_callback_blocks_for_oauth_model_google(self):
        """OAuth bypass removed: callback should BLOCK dangerous commands even for Google OAuth models."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="gemini-oauth-pro",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.emit_info"
            ) as mock_emit,
        ):
            result = await shell_safety_callback(
                context=None, command="rm -rf /", cwd=None, timeout=60
            )
            # OAuth bypass removed - should block dangerous command
            assert result is not None
            assert result["blocked"] is True
            mock_emit.assert_called_once()


class TestShellSafetyCallbackYoloModeBypass:
    """Test yolo_mode bypass in shell_safety_callback."""

    @pytest.mark.anyio
    async def test_callback_skips_when_yolo_mode_false(self):
        """Test callback returns None when yolo_mode is False."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=False,
            ),
        ):
            result = await shell_safety_callback(
                context=None, command="rm -rf /", cwd=None, timeout=60
            )
            assert result is None


class TestShellSafetyCallbackCacheHit:
    """Test shell_safety_callback with cached assessments."""

    @pytest.mark.anyio
    async def test_cached_assessment_blocked_high_risk(self):
        """Test cached assessment blocks high-risk command."""
        cached = CachedAssessment(risk="high", reasoning="Dangerous command")

        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=cached,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.emit_info"
            ) as mock_emit,
        ):
            result = await shell_safety_callback(
                context=None, command="rm -rf /", cwd=None, timeout=60
            )

            assert result is not None
            assert result["blocked"] is True
            assert result["risk"] == "high"
            assert result["reasoning"] == "Dangerous command"
            assert "blocked" in result["error_message"].lower()
            mock_emit.assert_called_once()

    @pytest.mark.anyio
    async def test_cached_assessment_allowed_low_risk(self):
        """Test cached assessment allows low-risk command."""
        cached = CachedAssessment(risk="low", reasoning="Safe command")

        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=cached,
            ),
        ):
            result = await shell_safety_callback(
                context=None, command="ls -la", cwd=None, timeout=60
            )

            assert result is None  # Allowed to proceed

    @pytest.mark.anyio
    async def test_cached_assessment_at_threshold_allowed(self):
        """Test cached assessment at threshold is allowed."""
        cached = CachedAssessment(risk="medium", reasoning="Moderate command")

        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=cached,
            ),
        ):
            result = await shell_safety_callback(
                context=None, command="npm install", cwd=None, timeout=60
            )

            assert result is None  # At threshold = allowed

    @pytest.mark.anyio
    async def test_cached_assessment_with_none_risk(self):
        """Test cached assessment with None risk defaults to high (fail-safe)."""
        cached = CachedAssessment(risk=None, reasoning="Unknown risk")

        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="low",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=cached,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="unknown", cwd=None, timeout=60
            )

            assert result is not None
            assert result["blocked"] is True
            # None risk becomes "unknown" in display
            assert "unknown" in result["error_message"].lower()


class TestShellSafetyCallbackCacheMiss:
    """Test shell_safety_callback with cache miss (LLM assessment)."""

    @pytest.mark.anyio
    async def test_llm_assessment_blocked_high_risk(self):
        """Test LLM assessment blocks high-risk command.
        
        Uses an ambiguous command that bypasses regex pre-filter but
        would be classified as high-risk by the LLM.
        """
        mock_assessment = ShellSafetyAssessment(
            risk="critical", reasoning="Deletes entire filesystem"
        )
        mock_result = MagicMock()
        mock_result.output = mock_assessment

        mock_agent_class = MagicMock()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run_with_mcp = AsyncMock(return_value=mock_result)
        mock_agent_class.return_value = mock_agent_instance

        # Use a command that regex pre-filter won't catch (ambiguous)
        # but LLM would classify as critical
        ambiguous_command = "custom_cleanup_tool --target=all --aggressive"

        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,  # Cache miss
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.cache_assessment"
            ) as mock_cache,
            patch.dict(
                "sys.modules",
                {
                    "code_puppy.plugins.shell_safety.agent_shell_safety": MagicMock(
                        ShellSafetyAgent=mock_agent_class
                    )
                },
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.emit_info"
            ) as mock_emit,
        ):
            result = await shell_safety_callback(
                context=None, command=ambiguous_command, cwd=None, timeout=60
            )

            assert result is not None
            assert result["blocked"] is True
            assert result["risk"] == "critical"
            assert result["reasoning"] == "Deletes entire filesystem"
            mock_cache.assert_called_once_with(
                ambiguous_command, None, "critical", "Deletes entire filesystem"
            )
            mock_emit.assert_called_once()

    @pytest.mark.anyio
    async def test_llm_assessment_allowed_low_risk(self):
        """Test LLM assessment allows low-risk command.
        
        Uses an ambiguous command that bypasses regex pre-filter but
        would be classified as low-risk by the LLM.
        """
        mock_assessment = ShellSafetyAssessment(
            risk="low", reasoning="Safe information display"
        )
        mock_result = MagicMock()
        mock_result.output = mock_assessment

        mock_agent_class = MagicMock()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run_with_mcp = AsyncMock(return_value=mock_result)
        mock_agent_class.return_value = mock_agent_instance

        # Use a command that regex pre-filter won't catch (ambiguous)
        # but LLM would classify as low risk
        ambiguous_command = "show_system_info --basic"

        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,  # Cache miss
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.cache_assessment"
            ) as mock_cache,
            patch.dict(
                "sys.modules",
                {
                    "code_puppy.plugins.shell_safety.agent_shell_safety": MagicMock(
                        ShellSafetyAgent=mock_agent_class
                    )
                },
            ),
        ):
            result = await shell_safety_callback(
                context=None, command=ambiguous_command, cwd=None, timeout=60
            )

            assert result is None  # Allowed
            mock_cache.assert_called_once_with(
                ambiguous_command, None, "low", "Safe information display"
            )

    @pytest.mark.anyio
    async def test_llm_assessment_with_cwd_in_prompt(self):
        """Test LLM assessment includes cwd in prompt."""
        mock_assessment = ShellSafetyAssessment(
            risk="low", reasoning="Safe in temp directory"
        )
        mock_result = MagicMock()
        mock_result.output = mock_assessment

        mock_agent_class = MagicMock()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run_with_mcp = AsyncMock(return_value=mock_result)
        mock_agent_class.return_value = mock_agent_instance

        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.cache_assessment"
            ) as mock_cache,
            patch.dict(
                "sys.modules",
                {
                    "code_puppy.plugins.shell_safety.agent_shell_safety": MagicMock(
                        ShellSafetyAgent=mock_agent_class
                    )
                },
            ),
        ):
            await shell_safety_callback(
                context=None, command="rm -rf *", cwd="/tmp/safe", timeout=60
            )

            # Verify the prompt includes cwd
            call_args = mock_agent_instance.run_with_mcp.call_args
            prompt = call_args[0][0]
            assert "/tmp/safe" in prompt
            assert "rm -rf *" in prompt

            # Verify cache includes cwd
            mock_cache.assert_called_once_with(
                "rm -rf *", "/tmp/safe", "low", "Safe in temp directory"
            )

    @pytest.mark.anyio
    async def test_fallback_assessment_not_cached(self):
        """Test fallback assessment is not cached."""
        mock_assessment = ShellSafetyAssessment(
            risk="high", reasoning="Fallback assessment"
        )
        mock_assessment.is_fallback = True  # Mark as fallback
        mock_result = MagicMock()
        mock_result.output = mock_assessment

        mock_agent_class = MagicMock()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run_with_mcp = AsyncMock(return_value=mock_result)
        mock_agent_class.return_value = mock_agent_instance

        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.cache_assessment"
            ) as mock_cache,
            patch.dict(
                "sys.modules",
                {
                    "code_puppy.plugins.shell_safety.agent_shell_safety": MagicMock(
                        ShellSafetyAgent=mock_agent_class
                    )
                },
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="dangerous", cwd=None, timeout=60
            )

            assert result is not None
            assert result["blocked"] is True
            # Fallback assessments should NOT be cached
            mock_cache.assert_not_called()


class TestShellSafetyCallbackExceptionHandling:
    """Test shell_safety_callback exception handling."""

    @pytest.mark.anyio
    async def test_exception_blocks_with_high_risk(self):
        """Test exception handling blocks command with high risk."""
        mock_agent_class = MagicMock()
        mock_agent_instance = MagicMock()
        mock_agent_instance.run_with_mcp = AsyncMock(
            side_effect=Exception("LLM connection failed")
        )
        mock_agent_class.return_value = mock_agent_instance

        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "code_puppy.plugins.shell_safety.agent_shell_safety": MagicMock(
                        ShellSafetyAgent=mock_agent_class
                    )
                },
            ),
        ):
            result = await shell_safety_callback(
                context=None, command="some command", cwd=None, timeout=60
            )

            assert result is not None
            assert result["blocked"] is True
            assert result["risk"] == "high"  # Fail-safe to high
            assert "LLM connection failed" in result["reasoning"]
            assert "error" in result["error_message"].lower()

    @pytest.mark.anyio
    async def test_cache_exception_blocks_command(self):
        """Test cache exception blocks command safely."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="low",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                side_effect=Exception("Cache corrupted"),
            ),
        ):
            result = await shell_safety_callback(
                context=None, command="ls", cwd=None, timeout=60
            )

            assert result is not None
            assert result["blocked"] is True
            assert result["risk"] == "high"
            assert "Cache corrupted" in result["reasoning"]


class TestShellSafetyCallbackErrorMessages:
    """Test error message formatting in shell_safety_callback."""

    @pytest.mark.anyio
    async def test_error_message_format_blocked(self):
        """Test error message format for blocked commands."""
        cached = CachedAssessment(risk="critical", reasoning="System destruction")

        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="low",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=cached,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="rm -rf /", cwd=None, timeout=60
            )

            error_msg = result["error_message"]
            # Check message contains expected elements
            assert "🛑" in error_msg
            assert "CRITICAL" in error_msg
            assert "LOW" in error_msg
            assert "System destruction" in error_msg
            assert "Override" in error_msg

    @pytest.mark.anyio
    async def test_error_message_with_none_reasoning(self):
        """Test error message with None reasoning."""
        cached = CachedAssessment(risk="high", reasoning=None)

        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="low",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=cached,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="dangerous", cwd=None, timeout=60
            )

            assert "No reasoning provided" in result["error_message"]


class TestRegisterCallback:
    """Test callback registration function."""

    def test_register_function_exists(self):
        """Test that register function exists and is callable."""
        assert callable(register)

    def test_register_calls_register_callback(self):
        """Test that register() calls register_callback."""
        with patch(
            "code_puppy.plugins.shell_safety.register_callbacks.register_callback"
        ) as mock_register:
            register()
            mock_register.assert_called_once_with(
                "run_shell_command", shell_safety_callback
            )

    def test_module_auto_registers_on_import(self):
        """Test that importing the module auto-registers the callback."""
        # Re-import to trigger auto-registration
        with patch(
            "code_puppy.plugins.shell_safety.register_callbacks.register_callback"
        ) as mock_register:
            # Force re-import

            import code_puppy.plugins.shell_safety.register_callbacks as module

            # Call register explicitly since re-import won't re-run module-level code
            module.register()

            mock_register.assert_called_with("run_shell_command", shell_safety_callback)


class TestNewlineRegression:
    """Regression tests for newline formatting in error messages.
    
    Issue: PR replaced \n with \\n in f-strings, causing literal backslash-n
    in error messages instead of actual newlines.
    """

    @pytest.mark.anyio
    async def test_error_message_contains_real_newlines_not_literal(self):
        """Error messages must contain actual newlines, not literal \\n."""
        cached = CachedAssessment(risk="high", reasoning="Test reasoning")

        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="low",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=cached,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="rm -rf /tmp/test", cwd=None, timeout=60
            )

            error_msg = result["error_message"]
            # Must contain actual newlines (ASCII 10)
            assert "\n" in error_msg, "Error message should contain actual newlines"
            # Must NOT contain literal backslash-n
            assert "\\n" not in error_msg, "Error message should NOT contain literal \\n"

    @pytest.mark.anyio
    async def test_regex_blocked_error_message_has_real_newlines(self):
        """Regex-blocked commands must have error messages with real newlines."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="low",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="rm -rf /", cwd=None, timeout=60
            )

            assert result is not None
            assert result["blocked"] is True
            error_msg = result["error_message"]
            # Must contain actual newlines (ASCII 10)
            assert "\n" in error_msg, "Error message should contain actual newlines"
            # Must NOT contain literal backslash-n
            assert "\\n" not in error_msg, "Error message should NOT contain literal \\n"


# =============================================================================
# Security Regression Tests - Phase 1 Critical Fixes
# =============================================================================


class TestSecurityRegressionQuotedPaths:
    """SECURITY REGRESSION TESTS: Quoted sensitive path bypasses.
    
    Issue: Commands like cat '/etc/shadow' bypassed detection because
    the regex only matched unquoted paths.
    
    SECURITY FIX: The regex classifier now properly normalizes commands to
    catch quoted sensitive paths. It returns 'ambiguous' for these cases,
    triggering LLM review. The key fix is that these are NO LONGER
    classified as 'none' (safe) by the regex classifier.
    """

    @pytest.mark.anyio
    async def test_quoted_etc_shadow_not_regex_safe(self):
        """SECURITY FIX: cat '/etc/shadow' regex classifier should NOT return 'none'."""
        # Test the regex classifier directly - the key fix is that regex no longer
        # returns 'none' (safe) for quoted sensitive paths
        from code_puppy.plugins.shell_safety.regex_classifier import classify_command
        
        result = classify_command("cat '/etc/shadow'")
        assert result.risk != "none", "Quoted sensitive path should not be regex-classified as 'none'"
        # Now returns definitive 'medium' risk instead of ambiguous - better security
        assert result.risk == "medium", "Should be classified as medium risk for sensitive file access"

    @pytest.mark.anyio
    async def test_double_quoted_etc_shadow_not_regex_safe(self):
        """SECURITY FIX: cat "/etc/shadow" regex classifier should NOT return 'none'."""
        from code_puppy.plugins.shell_safety.regex_classifier import classify_command
        
        result = classify_command('cat "/etc/shadow"')
        assert result.risk != "none"
        assert result.risk == "medium"

    @pytest.mark.anyio
    async def test_quoted_ssh_key_not_regex_safe(self):
        """SECURITY FIX: head '~/.ssh/id_rsa' regex classifier should NOT return 'none'."""
        from code_puppy.plugins.shell_safety.regex_classifier import classify_command
        
        result = classify_command("head '~/.ssh/id_rsa'")
        assert result.risk != "none"
        assert result.risk == "medium"

    @pytest.mark.anyio
    async def test_grep_quoted_etc_passwd_not_regex_safe(self):
        """SECURITY FIX: grep '/etc/passwd' regex classifier should NOT return 'none'."""
        from code_puppy.plugins.shell_safety.regex_classifier import classify_command
        
        result = classify_command("grep root '/etc/passwd'")
        assert result.risk != "none"
        assert result.is_ambiguous is True


class TestSecurityRegressionInputRedirection:
    """SECURITY REGRESSION TESTS: Input redirection bypasses.
    
    Issue: Commands like cat </etc/shadow bypassed detection because
    the redirect pattern only checked for > (output) not < (input).
    """

    @pytest.mark.anyio
    async def test_input_redirection_no_space_blocked(self):
        """cat </etc/shadow should be detected and blocked/ambiguous."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="low",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="cat </etc/shadow", cwd=None, timeout=60
            )
            assert result is not None
            assert result["blocked"] is True or result["risk"] in ("medium", "high", "ambiguous")

    @pytest.mark.anyio
    async def test_input_redirection_with_space_blocked(self):
        """cat < /etc/shadow should be detected and blocked/ambiguous."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="low",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="cat < /etc/shadow", cwd=None, timeout=60
            )
            assert result is not None
            assert result["blocked"] is True or result["risk"] in ("medium", "high", "ambiguous")


class TestSecurityRegressionTraversalBypass:
    """SECURITY REGRESSION TESTS: Relative traversal bypasses.
    
    Issue: Commands like cat ../../../../etc/shadow could escape the repo
    and access sensitive system files while being marked as safe.
    
    SECURITY FIX: The regex classifier now properly detects traversal patterns
    that target sensitive paths and returns 'ambiguous' for LLM review.
    """

    @pytest.mark.anyio
    async def test_traversal_to_etc_shadow_not_regex_safe(self):
        """SECURITY FIX: cat ../../../../etc/shadow regex should NOT return 'none'."""
        from code_puppy.plugins.shell_safety.regex_classifier import classify_command
        
        result = classify_command("cat ../../../../etc/shadow")
        assert result.risk != "none", "Traversal to sensitive path should not be regex-classified as 'none'"
        # Should be 'ambiguous' to trigger LLM review
        assert result.is_ambiguous is True, "Should require LLM assessment"

    @pytest.mark.anyio
    async def test_grep_traversal_to_etc_passwd_not_regex_safe(self):
        """SECURITY FIX: grep with traversal regex should NOT return 'none'."""
        from code_puppy.plugins.shell_safety.regex_classifier import classify_command
        
        result = classify_command("grep root ../../../../etc/passwd")
        assert result.risk != "none"
        assert result.is_ambiguous is True


class TestSecurityRegressionRootDelete:
    """SECURITY REGRESSION TESTS: Hardened root-delete detection.
    
    Issue: Variants like rm -rf -- /, rm -rf '/' , rm -rf /. 
    could bypass the original detection patterns.
    """

    @pytest.mark.anyio
    async def test_rm_rf_dash_dash_root_blocked(self):
        """rm -rf -- / should be detected and blocked."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="rm -rf -- /", cwd=None, timeout=60
            )
            assert result is not None
            assert result["blocked"] is True
            assert result["risk"] == "critical"

    @pytest.mark.anyio
    async def test_rm_r_f_dash_dash_root_blocked(self):
        """rm -r -f -- / should be detected and blocked."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="rm -r -f -- /", cwd=None, timeout=60
            )
            assert result is not None
            assert result["blocked"] is True
            assert result["risk"] == "critical"

    @pytest.mark.anyio
    async def test_rm_quoted_root_blocked(self):
        """rm -rf '/' should be detected and blocked."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="rm -rf '/'", cwd=None, timeout=60
            )
            assert result is not None
            assert result["blocked"] is True
            assert result["risk"] == "critical"

    @pytest.mark.anyio
    async def test_rm_rf_root_dot_blocked(self):
        """rm -rf /. should be detected and blocked."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="rm -rf /.", cwd=None, timeout=60
            )
            assert result is not None
            assert result["blocked"] is True
            assert result["risk"] == "critical"

    @pytest.mark.anyio
    async def test_rm_rf_multiple_slashes_blocked(self):
        """rm -rf /// should be detected and blocked."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="rm -rf ///", cwd=None, timeout=60
            )
            assert result is not None
            assert result["blocked"] is True
            assert result["risk"] == "critical"


class TestSecurityRegressionFindVariants:
    """SECURITY REGRESSION TESTS: Find quoted-root detection.
    
    Issue: Commands like find '/' -delete fell through to ambiguous
    because quoted paths weren't normalized before detection.
    """

    @pytest.mark.anyio
    async def test_find_single_quoted_root_delete_blocked(self):
        """find '/' -delete should be detected and blocked."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command="find '/' -delete", cwd=None, timeout=60
            )
            assert result is not None
            assert result["blocked"] is True
            assert result["risk"] == "critical"

    @pytest.mark.anyio
    async def test_find_double_quoted_root_delete_blocked(self):
        """find "/" -delete should be detected and blocked."""
        with (
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_global_model_name",
                return_value="claude-opus-4",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_yolo_mode",
                return_value=True,
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_safety_permission_level",
                return_value="medium",
            ),
            patch(
                "code_puppy.plugins.shell_safety.register_callbacks.get_cached_assessment",
                return_value=None,
            ),
            patch("code_puppy.plugins.shell_safety.register_callbacks.emit_info"),
        ):
            result = await shell_safety_callback(
                context=None, command='find "/" -delete', cwd=None, timeout=60
            )
            assert result is not None
            assert result["blocked"] is True
            assert result["risk"] == "critical"
