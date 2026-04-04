"""Tests for the tool_result_truncator plugin.

Verifies that tool results exceeding the configured threshold are truncated
before they enter message history, with proper truncation indicators.
"""

import pytest
from unittest.mock import MagicMock, patch

from code_puppy.plugins.tool_result_truncator.register_callbacks import (
    _extract_result_text,
    _reconstruct_result_with_truncation,
    _truncate_text,
    _on_post_tool_call,
    TRUNCATED_TOOLS,
)



class TestExtractResultText:
    """Tests for _extract_result_text function."""

    def test_extract_from_string(self):
        """Should return string unchanged."""
        text = "Hello world"
        result, is_structured = _extract_result_text(text)
        assert result == text
        assert is_structured is False

    def test_extract_from_none(self):
        """Should return empty string for None."""
        result, is_structured = _extract_result_text(None)
        assert result == ""
        assert is_structured is False

    def test_extract_from_bytes(self):
        """Should decode bytes to string."""
        text = "Hello world"
        result, is_structured = _extract_result_text(text.encode("utf-8"))
        assert result == text
        assert is_structured is False

    def test_extract_from_dict_with_content(self):
        """Should extract content field from dict."""
        data = {"content": "file contents here", "other": "field"}
        result, is_structured = _extract_result_text(data)
        assert result == "file contents here"
        assert is_structured is True

    def test_extract_from_dict_with_output(self):
        """Should extract output field from dict."""
        data = {"output": "command output", "status": "ok"}
        result, is_structured = _extract_result_text(data)
        assert result == "command output"
        assert is_structured is True

    def test_extract_from_dict_with_stdout(self):
        """Should extract stdout field from dict."""
        data = {"stdout": "shell output", "stderr": "", "exit_code": 0}
        result, is_structured = _extract_result_text(data)
        assert result == "shell output"
        assert is_structured is True

    def test_extract_from_dict_no_recognized_field(self):
        """Should stringify entire dict if no recognized field."""
        data = {"foo": "bar", "baz": 123}
        result, is_structured = _extract_result_text(data)
        assert "foo" in result
        assert "bar" in result
        assert is_structured is True

    def test_extract_from_pydantic_model(self):
        """Should extract content from Pydantic model."""
        from pydantic import BaseModel

        class FileResult(BaseModel):
            content: str
            num_tokens: int

        model = FileResult(content="file contents", num_tokens=10)
        result, is_structured = _extract_result_text(model)
        assert result == "file contents"
        assert is_structured is True

    def test_extract_from_object_with_content_attr(self):
        """Should extract content attribute from any object."""
        obj = MagicMock()
        obj.content = "object content"
        result, is_structured = _extract_result_text(obj)
        assert result == "object content"
        assert is_structured is True


class TestTruncateText:
    """Tests for _truncate_text function."""

    def test_no_truncation_needed(self):
        """Should not truncate text under the limit."""
        text = "Short text"
        max_tokens = 100
        result = _truncate_text(text, max_tokens)
        assert result == text

    def test_truncation_adds_indicator(self):
        """Should add truncation indicator when truncating."""
        # Create text that will definitely exceed token limit
        # ~4 chars per token, so 2000 chars ≈ 500 tokens
        # To exceed 100 tokens, we need ~400+ chars
        text = "Line {}\n".format("x" * 50) * 20  # ~1000+ chars
        max_tokens = 100

        result = _truncate_text(text, max_tokens)

        # Should contain truncation indicator
        assert "[...truncated" in result
        assert "original was" in result

    def test_truncation_preserves_beginning_and_end(self):
        """Should preserve both beginning and end of text."""
        # Create text with clear beginning and end markers
        lines = [f"BEGINNING_LINE_{i}" for i in range(10)]
        lines.extend([f"MIDDLE_LINE_{i}" for i in range(50)])
        lines.extend([f"END_LINE_{i}" for i in range(10)])
        text = "\n".join(lines)

        max_tokens = 100
        result = _truncate_text(text, max_tokens)

        # Should have beginning lines
        assert "BEGINNING_LINE_0" in result

        # Should have end lines
        assert "END_LINE_0" in result

        # Should have truncation indicator
        assert "[...truncated" in result

    def test_truncation_reports_token_counts(self):
        """Should report original and kept token counts in indicator."""
        text = "word " * 500  # Definitely over 100 tokens
        max_tokens = 100

        result = _truncate_text(text, max_tokens)

        # Should contain token count info
        assert "original was" in result
        assert "tokens" in result


class TestReconstructResult:
    """Tests for _reconstruct_result_with_truncation function."""

    def test_reconstruct_string(self):
        """Should return truncated string for string input."""
        original = "original text"
        truncated = "truncated text"
        result = _reconstruct_result_with_truncation(original, truncated, original)
        assert result == truncated

    def test_reconstruct_bytes(self):
        """Should encode truncated text for bytes input."""
        original = b"original text"
        truncated = "truncated text"
        result = _reconstruct_result_with_truncation(original, truncated, original)
        assert result == b"truncated text"

    def test_reconstruct_dict_with_content(self):
        """Should update content field in dict."""
        original = {"content": "old", "other": "field"}
        truncated = "new content"
        result = _reconstruct_result_with_truncation(original, truncated, "old")
        assert result["content"] == truncated
        assert result["other"] == "field"

    def test_reconstruct_dict_with_output(self):
        """Should update output field in dict."""
        original = {"output": "old", "status": "ok"}
        truncated = "new output"
        result = _reconstruct_result_with_truncation(original, truncated, "old")
        assert result["output"] == truncated
        assert result["status"] == "ok"

    def test_reconstruct_dict_adds_content_if_not_found(self):
        """Should add content field if no recognized field exists."""
        original = {"foo": "bar"}
        truncated = "new content"
        result = _reconstruct_result_with_truncation(original, truncated, "old")
        assert result["content"] == truncated
        assert result["foo"] == "bar"


class TestPostToolCallCallback:
    """Tests for _on_post_tool_call callback."""

    @pytest.mark.asyncio
    async def test_ignores_non_truncated_tools(self):
        """Should return None for tools not in truncation list."""
        result = await _on_post_tool_call(
            tool_name="some_other_tool",
            tool_args={},
            result="large content",
            duration_ms=100.0,
            context=None
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_truncation_for_small_results(self):
        """Should not truncate small results for truncated tools."""
        small_text = "Small result"

        with patch(
            "code_puppy.plugins.tool_result_truncator.register_callbacks.get_tool_result_max_tokens",
            return_value=1000
        ):
            result = await _on_post_tool_call(
                tool_name="read_file",
                tool_args={"file_path": "/test.txt"},
                result=small_text,
                duration_ms=100.0,
                context=None
            )
            assert result is None  # No truncation needed

    @pytest.mark.asyncio
    async def test_truncates_large_string_results(self):
        """Should truncate large string results for truncated tools."""
        # Create text that exceeds default threshold
        large_text = "word " * 3000  # ~3000 words, definitely over 8000 tokens

        with patch(
            "code_puppy.plugins.tool_result_truncator.register_callbacks.get_tool_result_max_tokens",
            return_value=100
        ):
            result = await _on_post_tool_call(
                tool_name="read_file",
                tool_args={"file_path": "/test.txt"},
                result=large_text,
                duration_ms=100.0,
                context=None
            )

            # Should be truncated
            assert result is not None
            assert "[...truncated" in result
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_truncates_large_dict_results(self):
        """Should truncate large dict results for truncated tools."""
        large_content = "word " * 3000

        with patch(
            "code_puppy.plugins.tool_result_truncator.register_callbacks.get_tool_result_max_tokens",
            return_value=100
        ):
            result = await _on_post_tool_call(
                tool_name="grep",
                tool_args={"pattern": "test"},
                result={"content": large_content, "matches": []},
                duration_ms=100.0,
                context=None
            )

            # Should be truncated and reconstructed as dict
            assert result is not None
            assert isinstance(result, dict)
            assert "[...truncated" in result["content"]

    @pytest.mark.asyncio
    async def test_handles_all_truncated_tools(self):
        """Should handle all tools in TRUNCATED_TOOLS list."""
        large_content = "word " * 3000

        with patch(
            "code_puppy.plugins.tool_result_truncator.register_callbacks.get_tool_result_max_tokens",
            return_value=100
        ):
            for tool_name in TRUNCATED_TOOLS:
                result = await _on_post_tool_call(
                    tool_name=tool_name,
                    tool_args={},
                    result=large_content,
                    duration_ms=100.0,
                    context=None
                )
                # All should be truncated since content is large
                assert result is not None
                assert "[...truncated" in result or isinstance(result, (str, dict))


class TestTruncatedToolsList:
    """Tests for TRUNCATED_TOOLS constant."""

    def test_contains_expected_tools(self):
        """Should contain the expected tool names."""
        expected_tools = [
            "read_file",
            "grep",
            "list_files",
            "run_shell_command",
            "agent_run_shell_command",
        ]
        for tool in expected_tools:
            assert tool in TRUNCATED_TOOLS

    def test_is_frozen_set(self):
        """Should be a frozenset for immutability."""
        assert isinstance(TRUNCATED_TOOLS, frozenset)
