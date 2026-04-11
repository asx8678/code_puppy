"""Tests for GAC Policy Error Handling (BLK3).

These tests prove that policy-blocked git commands produce clean,
actionable error messages that help users understand WHY a command
was blocked and WHAT they can do about it.
"""

from __future__ import annotations

from code_puppy.plugins.git_auto_commit.policy_errors import (
    DENIAL_SUGGESTIONS,
    GACPolicyError,
    _clean_policy_source,
    classify_policy_denial,
    handle_blocked_result,
)


# =============================================================================
# Tests for GACPolicyError
# =============================================================================


class TestGACPolicyError:
    """Tests for the GACPolicyError exception class."""

    def test_user_message_includes_all_fields(self):
        """Test that user_message includes command, reason, source, suggestion."""
        error = GACPolicyError(
            command="git push",
            reason="Push operations not permitted",
            policy_source="Project policy rules (.code_puppy/policy.json)",
            suggestion="Commit locally and push manually.",
        )
        message = error.user_message

        assert "git push" in message
        assert "denied by policy" in message
        assert "Push operations not permitted" in message
        assert "Project policy rules" in message
        assert "Commit locally and push manually" in message

    def test_user_message_omits_optional_fields_when_none(self):
        """Test that user_message omits source/suggestion when None."""
        error = GACPolicyError(
            command="git status",
            reason="Unknown denial",
            policy_source=None,
            suggestion=None,
        )
        message = error.user_message

        assert "git status" in message
        assert "Unknown denial" in message
        assert "Policy source:" not in message
        assert "To resolve:" not in message

    def test_exception_message_equals_user_message(self):
        """Test that str(error) equals user_message."""
        error = GACPolicyError(
            command="git push",
            reason="Blocked",
            suggestion="Do it manually.",
        )
        assert str(error) == error.user_message

    def test_attributes_stored_correctly(self):
        """Test that all constructor parameters are stored as attributes."""
        error = GACPolicyError(
            command="git checkout main",
            reason="Branch operations blocked",
            policy_source="User policy",
            suggestion="Use your terminal.",
        )

        assert error.command == "git checkout main"
        assert error.reason == "Branch operations blocked"
        assert error.policy_source == "User policy"
        assert error.suggestion == "Use your terminal."


# =============================================================================
# Tests for classify_policy_denial()
# =============================================================================


class TestClassifyPolicyDenial:
    """Tests for classify_policy_denial() function."""

    def test_maps_git_push_to_correct_suggestion(self):
        """Test that 'git push' command gets the correct suggestion."""
        error = classify_policy_denial(
            command="git push origin main",
            raw_reason="Push not allowed",
        )

        assert error.command == "git push origin main"
        assert "GAC v1 does not support push" in error.suggestion

    def test_maps_destructive_reason_to_correct_suggestion(self):
        """Test that 'destructive' in reason gets the correct suggestion."""
        error = classify_policy_denial(
            command="git reset --hard HEAD",
            raw_reason="Command classified as destructive",
        )

        assert "destructive" in error.suggestion.lower()
        assert ".code_puppy/policy.json" in error.suggestion

    def test_maps_git_reset_to_correct_suggestion(self):
        """Test that 'git reset' command gets the reset-specific suggestion."""
        error = classify_policy_denial(
            command="git reset HEAD~1",
            raw_reason="Reset blocked",
        )

        assert "Reset operations are not permitted" in error.suggestion

    def test_maps_git_checkout_to_correct_suggestion(self):
        """Test that 'git checkout' command gets the checkout-specific suggestion."""
        error = classify_policy_denial(
            command="git checkout feature-branch",
            raw_reason="Checkout blocked",
        )

        assert "Branch operations should be done manually" in error.suggestion

    def test_maps_git_rebase_to_correct_suggestion(self):
        """Test that 'git rebase' command gets the rebase-specific suggestion."""
        error = classify_policy_denial(
            command="git rebase main",
            raw_reason="Rebase blocked",
        )

        assert "Rebase operations are not permitted" in error.suggestion

    def test_uses_default_suggestion_when_no_pattern_matches(self):
        """Test that unmatched patterns get a default suggestion."""
        error = classify_policy_denial(
            command="git some-weird-command",
            raw_reason="Some random reason",
        )

        assert ".code_puppy/policy.json" in error.suggestion
        assert "~/.code_puppy/policy.json" in error.suggestion
        assert "run the command manually" in error.suggestion

    def test_cleans_policy_source_names(self):
        """Test that internal source names are mapped to friendly names."""
        error = classify_policy_denial(
            command="git status",
            raw_reason="Blocked",
            raw_source="policy_engine",
        )

        assert "Project policy rules" in (error.policy_source or "")
        assert ".code_puppy/policy.json" in (error.policy_source or "")

    def test_passes_through_unknown_policy_sources(self):
        """Test that unknown source names are passed through unchanged."""
        error = classify_policy_denial(
            command="git status",
            raw_reason="Blocked",
            raw_source="custom_plugin_source",
        )

        assert error.policy_source == "custom_plugin_source"


# =============================================================================
# Tests for handle_blocked_result()
# =============================================================================


class TestHandleBlockedResult:
    """Tests for handle_blocked_result() function."""

    def test_returns_none_for_non_blocked_results(self):
        """Test that non-blocked results return None."""
        result = {
            "success": True,
            "output": "clean",
            "blocked": False,
            "reason": None,
        }

        error = handle_blocked_result("git status", result)
        assert error is None

    def test_returns_none_when_blocked_key_missing(self):
        """Test that results without 'blocked' key return None."""
        result = {
            "success": True,
            "output": "clean",
        }

        error = handle_blocked_result("git status", result)
        assert error is None

    def test_returns_gac_policy_error_for_blocked_results(self):
        """Test that blocked results return a GACPolicyError."""
        result = {
            "success": False,
            "output": "",
            "error": "Security blocked",
            "blocked": True,
            "reason": "Push not permitted",
            "policy_source": "policy_engine",
        }

        error = handle_blocked_result("git push", result)

        assert isinstance(error, GACPolicyError)
        assert error.command == "git push"
        assert error.reason == "Push not permitted"

    def test_passes_through_reason_and_source(self):
        """Test that reason and source are passed through correctly."""
        result = {
            "success": False,
            "blocked": True,
            "reason": "Custom reason",
            "policy_source": "user_policy",
        }

        error = handle_blocked_result("git reset", result)

        assert error.reason == "Custom reason"
        assert "User policy" in (error.policy_source or "")

    def test_uses_default_reason_when_missing(self):
        """Test that missing reason defaults to 'Unknown policy denial'."""
        result = {
            "success": False,
            "blocked": True,
        }

        error = handle_blocked_result("git status", result)

        assert error.reason == "Unknown policy denial"


# =============================================================================
# Tests for _clean_policy_source()
# =============================================================================


class TestCleanPolicySource:
    """Tests for _clean_policy_source() function."""

    def test_maps_policy_engine(self):
        """Test that 'policy_engine' maps to friendly name."""
        result = _clean_policy_source("policy_engine")
        assert "Project policy rules" in (result or "")
        assert ".code_puppy/policy.json" in (result or "")

    def test_maps_user_policy(self):
        """Test that 'user_policy' maps to friendly name."""
        result = _clean_policy_source("user_policy")
        assert "User policy" in (result or "")
        assert "~/.code_puppy/policy.json" in (result or "")

    def test_maps_shell_safety(self):
        """Test that 'shell_safety' maps to friendly name."""
        result = _clean_policy_source("shell_safety")
        assert "Shell safety analysis" in (result or "")
        assert "automatic" in (result or "")

    def test_maps_run_shell_command(self):
        """Test that 'run_shell_command' maps to friendly name."""
        result = _clean_policy_source("run_shell_command")
        assert result == "Shell command callback"

    def test_passes_through_unknown_sources(self):
        """Test that unknown sources are returned unchanged."""
        result = _clean_policy_source("my_custom_source")
        assert result == "my_custom_source"

    def test_returns_none_for_none_input(self):
        """Test that None input returns None."""
        result = _clean_policy_source(None)
        assert result is None

    def test_returns_none_for_empty_string(self):
        """Test that empty string returns None."""
        result = _clean_policy_source("")
        assert result is None


# =============================================================================
# Tests for DENIAL_SUGGESTIONS constant
# =============================================================================


class TestDenialSuggestions:
    """Tests for the DENIAL_SUGGESTIONS mapping."""

    def test_all_expected_patterns_exist(self):
        """Test that all expected denial patterns are in the map."""
        expected_patterns = [
            "git push",
            "git reset",
            "git checkout",
            "git rebase",
            "destructive",
            "not_in_allowlist",
        ]

        for pattern in expected_patterns:
            assert pattern in DENIAL_SUGGESTIONS, f"Missing pattern: {pattern}"

    def test_all_suggestions_are_non_empty_strings(self):
        """Test that all suggestions are non-empty strings."""
        for pattern, suggestion in DENIAL_SUGGESTIONS.items():
            assert isinstance(suggestion, str), f"{pattern}: not a string"
            assert len(suggestion) > 0, f"{pattern}: empty string"
            assert suggestion.strip() == suggestion, (
                f"{pattern}: has leading/trailing whitespace"
            )

    def test_suggestions_are_actionable(self):
        """Test that suggestions tell the user what to do."""
        for pattern, suggestion in DENIAL_SUGGESTIONS.items():
            # Should be actionable - contains instruction words
            actionable_indicators = [
                "manually",
                "manually.",
                "safety.",
                "Check",
                "Review",
                "Commit locally",
                "Branch operations",
                "Reset operations",
                "Rebase operations",
            ]
            assert any(
                indicator in suggestion for indicator in actionable_indicators
            ), f"{pattern}: suggestion doesn't appear actionable: {suggestion}"

    def test_git_push_suggestion_specific(self):
        """Test the specific content of the git push suggestion."""
        suggestion = DENIAL_SUGGESTIONS["git push"]
        assert "GAC v1" in suggestion
        assert "does not support push" in suggestion
        assert "manually" in suggestion

    def test_destructive_suggestion_mentions_policy_json(self):
        """Test that destructive suggestion references policy.json."""
        suggestion = DENIAL_SUGGESTIONS["destructive"]
        assert ".code_puppy/policy.json" in suggestion
