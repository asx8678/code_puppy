"""Tests for text_ops module (bd-118).

These tests verify the Python -> Elixir RPC integration for text processing.
They mock the transport layer to avoid requiring the Elixir service.
"""

from unittest.mock import MagicMock, patch

import pytest

# Import the module under test
from code_puppy import text_ops


class TestTextReplace:
    """Tests for text_replace RPC wrapper."""

    def test_calls_transport_with_correct_params(self):
        """Verify correct RPC method and parameters are sent."""
        mock_transport = MagicMock()
        mock_transport._send_request.return_value = {
            "modified": "Hello Python",
            "diff": "-Hello World\n+Hello Python",
            "success": True,
            "error": None,
            "jw_score": 1.0,
        }

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            result = text_ops.text_replace(
                content="Hello World",
                replacements=[{"old_str": "World", "new_str": "Python"}],
            )

        mock_transport._send_request.assert_called_once_with(
            "text_replace",
            {
                "content": "Hello World",
                "replacements": [{"old_str": "World", "new_str": "Python"}],
            },
        )

        assert result["modified"] == "Hello Python"
        assert result["success"] is True

    def test_handles_multiple_replacements(self):
        """Verify multiple replacements are passed correctly."""
        mock_transport = MagicMock()
        mock_transport._send_request.return_value = {
            "modified": "Foo Bar Baz",
            "diff": "",
            "success": True,
            "error": None,
            "jw_score": 1.0,
        }

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            text_ops.text_replace(
                content="A B C",
                replacements=[
                    {"old_str": "A", "new_str": "Foo"},
                    {"old_str": "B", "new_str": "Bar"},
                    {"old_str": "C", "new_str": "Baz"},
                ],
            )

        call_args = mock_transport._send_request.call_args
        assert call_args[0][0] == "text_replace"
        assert call_args[0][1]["replacements"] == [
            {"old_str": "A", "new_str": "Foo"},
            {"old_str": "B", "new_str": "Bar"},
            {"old_str": "C", "new_str": "Baz"},
        ]

    def test_handles_failed_replacement(self):
        """Verify failed replacement responses are returned correctly."""
        mock_transport = MagicMock()
        mock_transport._send_request.return_value = {
            "modified": "Hello World",
            "diff": "",
            "success": False,
            "error": "No match found for 'NonExistent'",
            "jw_score": 0.5,
        }

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            result = text_ops.text_replace(
                content="Hello World",
                replacements=[{"old_str": "NonExistent", "new_str": "Python"}],
            )

        assert result["success"] is False
        assert "NonExistent" in result["error"]
        assert result["jw_score"] == 0.5


class TestTextFuzzyMatch:
    """Tests for text_fuzzy_match RPC wrapper."""

    def test_calls_transport_with_correct_params(self):
        """Verify correct RPC method and parameters are sent."""
        mock_transport = MagicMock()
        mock_transport._send_request.return_value = {
            "matched_text": "def foo():",
            "start": 1,
            "end": 1,
            "score": 1.0,
        }

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            result = text_ops.text_fuzzy_match(
                haystack_lines=["def foo():", "    pass"],
                needle="def foo():",
            )

        mock_transport._send_request.assert_called_once_with(
            "text_fuzzy_match",
            {
                "haystack_lines": ["def foo():", "    pass"],
                "needle": "def foo():",
            },
        )

        assert result["matched_text"] == "def foo():"
        assert result["start"] == 1

    def test_handles_no_match(self):
        """Verify no-match responses are returned correctly."""
        mock_transport = MagicMock()
        mock_transport._send_request.return_value = {
            "matched_text": None,
            "start": 0,
            "end": None,
            "score": 0.0,
        }

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            result = text_ops.text_fuzzy_match(
                haystack_lines=["line 1", "line 2"],
                needle="nonexistent content",
            )

        assert result["matched_text"] is None
        assert result["score"] == 0.0

    def test_multi_line_match(self):
        """Verify multi-line needle matching works correctly."""
        mock_transport = MagicMock()
        mock_transport._send_request.return_value = {
            "matched_text": "if True:\n    pass",
            "start": 3,
            "end": 4,
            "score": 0.95,
        }

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            result = text_ops.text_fuzzy_match(
                haystack_lines=["# Comment", "", "if True:", "    pass"],
                needle="if True:\n    pass",
            )

        assert result["start"] == 3
        assert result["end"] == 4


class TestTextUnifiedDiff:
    """Tests for text_unified_diff RPC wrapper."""

    def test_calls_transport_with_correct_params(self):
        """Verify correct RPC method and parameters are sent."""
        mock_transport = MagicMock()
        mock_transport._send_request.return_value = {
            "diff": "--- a.txt\n+++ b.txt\n@@ -1 +1 @@\n-hello\n+world\n",
        }

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            result = text_ops.text_unified_diff(
                old_string="hello",
                new_string="world",
                context_lines=3,
                from_file="a.txt",
                to_file="b.txt",
            )

        mock_transport._send_request.assert_called_once_with(
            "text_unified_diff",
            {
                "old": "hello",
                "new": "world",
                "context_lines": 3,
                "from_file": "a.txt",
                "to_file": "b.txt",
            },
        )

        assert "--- a.txt" in result
        assert "+world" in result

    def test_uses_default_params(self):
        """Verify default parameters are used when not specified."""
        mock_transport = MagicMock()
        mock_transport._send_request.return_value = {"diff": ""}

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            text_ops.text_unified_diff(
                old_string="a",
                new_string="b",
            )

        call_args = mock_transport._send_request.call_args
        assert call_args[0][1]["context_lines"] == 3
        assert call_args[0][1]["from_file"] == ""
        assert call_args[0][1]["to_file"] == ""

    def test_returns_diff_string_only(self):
        """Verify the function returns just the diff string, not the full response."""
        expected_diff = "--- \n+++ \n@@ -1 +1 @@\n-old\n+new\n"
        mock_transport = MagicMock()
        mock_transport._send_request.return_value = {"diff": expected_diff}

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            result = text_ops.text_unified_diff(
                old_string="old",
                new_string="new",
            )

        assert result == expected_diff
        assert isinstance(result, str)


class TestConvenienceAliases:
    """Tests for the convenience function aliases."""

    def test_replace_alias(self):
        """Verify replace() is an alias for text_replace()."""
        mock_transport = MagicMock()
        mock_transport._send_request.return_value = {
            "modified": "test",
            "diff": "",
            "success": True,
            "error": None,
            "jw_score": 1.0,
        }

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            result = text_ops.replace(
                content="original",
                replacements=[{"old_str": "original", "new_str": "test"}],
            )

        mock_transport._send_request.assert_called_once()
        assert result["modified"] == "test"

    def test_fuzzy_match_alias(self):
        """Verify fuzzy_match() is an alias for text_fuzzy_match()."""
        mock_transport = MagicMock()
        mock_transport._send_request.return_value = {
            "matched_text": "match",
            "start": 1,
            "end": 1,
            "score": 1.0,
        }

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            result = text_ops.fuzzy_match(
                haystack_lines=["match"],
                needle="match",
            )

        mock_transport._send_request.assert_called_once()
        assert result["matched_text"] == "match"

    def test_unified_diff_alias(self):
        """Verify unified_diff() is an alias for text_unified_diff()."""
        mock_transport = MagicMock()
        mock_transport._send_request.return_value = {"diff": "--- \n+++ \n@@ -1 +1 @@\n-a\n+b\n"}

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            result = text_ops.unified_diff(
                old_string="a",
                new_string="b",
            )

        mock_transport._send_request.assert_called_once()
        assert "-a" in result


class TestTransportIntegration:
    """Tests for transport integration edge cases."""

    def test_transport_error_propagation(self):
        """Verify transport errors are propagated correctly."""
        mock_transport = MagicMock()
        mock_transport._send_request.side_effect = Exception("Transport error")

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            with pytest.raises(Exception, match="Transport error"):
                text_ops.text_replace("content", [])

    def test_get_transport_import(self):
        """Verify _get_transport properly imports from elixir_transport_helpers."""
        # This test verifies the lazy import mechanism works
        mock_transport = MagicMock()

        with patch(
            "code_puppy.elixir_transport_helpers.get_transport",
            return_value=mock_transport,
        ):
            mock_transport._send_request.return_value = {
                "modified": "test",
                "diff": "",
                "success": True,
                "error": None,
                "jw_score": 1.0,
            }
            # Call the private function directly to test the import path
            transport = text_ops._get_transport()
            assert transport is mock_transport


class TestTypeAnnotations:
    """Tests to verify type annotations are present and functional."""

    def test_function_signatures_accept_typed_params(self):
        """Verify functions accept typed parameters without runtime errors."""
        mock_transport = MagicMock()
        mock_transport._send_request.return_value = {
            "modified": "",
            "diff": "",
            "success": True,
            "error": None,
            "jw_score": 0.0,
        }

        with patch(
            "code_puppy.text_ops._get_transport",
            return_value=mock_transport,
        ):
            # These should not raise type errors at runtime
            text_ops.text_replace("content", [])
            text_ops.text_fuzzy_match([], "needle")
            text_ops.text_unified_diff("old", "new", 5, "a", "b")
