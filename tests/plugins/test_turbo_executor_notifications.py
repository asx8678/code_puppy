"""Unit tests for the Turbo Executor Notifications module.

Tests the visual feedback system that hooks into pre_tool_call and post_tool_call
callbacks to provide progress notifications for turbo_execute batch operations.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from code_puppy.plugins.turbo_executor.notifications import (
    _format_brief_args,
    _format_brief_stats,
    _on_post_tool_call,
    _on_pre_tool_call,
    emit_operation_complete,
    emit_operation_error,
    emit_operation_start,
)


class TestOnPreToolCall:
    """Test _on_pre_tool_call callback handler."""

    def test_ignores_non_turbo_tools_list_files(self):
        """Test that _on_pre_tool_call ignores non-turbo tools like list_files."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            _on_pre_tool_call("list_files", {"directory": "."})
            mock_emit.assert_not_called()

    def test_ignores_non_turbo_tools_other_tools(self):
        """Test that _on_pre_tool_call ignores other non-turbo tools."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            _on_pre_tool_call("some_other_tool", {"arg": "value"})
            mock_emit.assert_not_called()

            _on_pre_tool_call("read_file", {"file_path": "test.py"})
            mock_emit.assert_not_called()

            _on_pre_tool_call("grep", {"search_string": "test"})
            mock_emit.assert_not_called()

    def test_emits_banner_for_turbo_execute_list_files(self):
        """Test that _on_pre_tool_call emits correct banner for turbo_execute with list_files."""
        plan_data = {
            "id": "test-plan-1",
            "operations": [
                {"type": "list_files", "args": {"directory": "src"}, "priority": 1}
            ],
        }

        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            _on_pre_tool_call("turbo_execute", {"plan_json": json.dumps(plan_data)})

            # Should be called twice: once for banner, once for summary
            assert mock_emit.call_count == 2

            # First call should have the startup banner
            first_call = mock_emit.call_args_list[0]
            assert "🚀 Turbo Plan 'test-plan-1' starting" in first_call[0][0]
            assert "1 operations" in first_call[0][0]

            # Second call should have the summary with emoji
            second_call = mock_emit.call_args_list[1]
            assert "📂 1 list_files" in second_call[0][0]

    def test_emits_banner_for_turbo_execute_multiple_operations(self):
        """Test that _on_pre_tool_call emits correct banner with multiple operation types."""
        plan_data = {
            "id": "multi-op-plan",
            "operations": [
                {"type": "list_files", "args": {"directory": "src"}, "priority": 1},
                {"type": "grep", "args": {"search_string": "def "}, "priority": 2},
                {"type": "read_files", "args": {"file_paths": ["a.py", "b.py"]}, "priority": 3},
            ],
        }

        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            _on_pre_tool_call("turbo_execute", {"plan_json": json.dumps(plan_data)})

            assert mock_emit.call_count == 2

            first_call = mock_emit.call_args_list[0]
            assert "🚀 Turbo Plan 'multi-op-plan' starting" in first_call[0][0]
            assert "3 operations" in first_call[0][0]

            second_call = mock_emit.call_args_list[1]
            summary = second_call[0][0]
            assert "📂 1 list_files" in summary
            assert "🔍 1 grep" in summary
            assert "📄 1 read_files" in summary

    def test_handles_empty_operations_gracefully(self):
        """Test that _on_pre_tool_call handles empty operations list."""
        plan_data = {
            "id": "empty-plan",
            "operations": [],
        }

        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            _on_pre_tool_call("turbo_execute", {"plan_json": json.dumps(plan_data)})

            assert mock_emit.call_count == 2
            second_call = mock_emit.call_args_list[1]
            assert "no operations" in second_call[0][0]


class TestOnPostToolCall:
    """Test _on_post_tool_call callback handler."""

    def test_ignores_non_turbo_tools(self):
        """Test that _on_post_tool_call ignores non-turbo tools."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_success") as mock_success, \
             patch("code_puppy.plugins.turbo_executor.notifications.emit_warning") as mock_warning:
            _on_post_tool_call("list_files", {}, {"status": "success"}, 100.0)
            mock_success.assert_not_called()
            mock_warning.assert_not_called()

    def test_emits_success_message(self):
        """Test that _on_post_tool_call emits success message for turbo_execute."""
        result = {
            "status": "completed",
            "success_count": 3,
            "error_count": 0,
            "total_duration_ms": 250.5,
            "operation_results": [
                {"operation_id": "op1", "type": "list_files", "status": "success"},
                {"operation_id": "op2", "type": "grep", "status": "success"},
                {"operation_id": "op3", "type": "read_files", "status": "success"},
            ],
        }

        with patch("code_puppy.plugins.turbo_executor.notifications.emit_success") as mock_success:
            _on_post_tool_call("turbo_execute", {}, result, 250.5)

            mock_success.assert_called_once()
            call_args = mock_success.call_args[0][0]
            assert "✅ Turbo Plan completed" in call_args
            assert "3 success" in call_args
            assert "0 errors" in call_args
            assert "251ms" in call_args or "250.5ms" in call_args or "250ms" in call_args

    def test_emits_error_warnings_for_failed_operations(self):
        """Test that _on_post_tool_call emits warnings for failed operations."""
        result = {
            "status": "partial",
            "success_count": 1,
            "error_count": 2,
            "total_duration_ms": 150.0,
            "operation_results": [
                {"operation_id": "op1", "type": "list_files", "status": "success"},
                {"operation_id": "op2", "type": "grep", "status": "error", "error": "Permission denied"},
                {"operation_id": "op3", "type": "read_files", "status": "error", "error": "File not found"},
            ],
        }

        with patch("code_puppy.plugins.turbo_executor.notifications.emit_success") as mock_success, \
             patch("code_puppy.plugins.turbo_executor.notifications.emit_warning") as mock_warning:
            _on_post_tool_call("turbo_execute", {}, result, 150.0)

            mock_success.assert_called_once()

            # Should emit warning for each failed operation
            assert mock_warning.call_count == 2

            first_warning = mock_warning.call_args_list[0][0][0]
            assert "❌" in first_warning
            assert "grep (op2)" in first_warning
            assert "Permission denied" in first_warning

            second_warning = mock_warning.call_args_list[1][0][0]
            assert "❌" in second_warning
            assert "read_files (op3)" in second_warning
            assert "File not found" in second_warning

    def test_handles_failed_status_with_no_individual_errors(self):
        """Test handling of failed status without specific operation errors."""
        result = {
            "status": "failed",
            "success_count": 0,
            "error_count": 0,
            "total_duration_ms": 50.0,
            "operation_results": [],
        }

        with patch("code_puppy.plugins.turbo_executor.notifications.emit_success") as mock_success, \
             patch("code_puppy.plugins.turbo_executor.notifications.emit_warning") as mock_warning:
            _on_post_tool_call("turbo_execute", {}, result, 50.0)

            mock_success.assert_called_once()

            # Should emit generic failure warning
            mock_warning.assert_called_once()
            warning_msg = mock_warning.call_args[0][0]
            assert "failed with no specific operation errors" in warning_msg

    def test_handles_non_dict_result_gracefully(self):
        """Test handling when result is not a dict."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_success") as mock_success:
            _on_post_tool_call("turbo_execute", {}, "unexpected result format", 100.0)

            mock_success.assert_called_once()
            call_args = mock_success.call_args[0][0]
            assert "✅ Turbo Plan completed" in call_args
            assert "100ms" in call_args or "100.0ms" in call_args


class TestEmitOperationStart:
    """Test emit_operation_start formatting."""

    def test_formatting_list_files(self):
        """Test emit_operation_start formatting for list_files."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            emit_operation_start(1, 3, "list_files", {"directory": "src", "recursive": True})

            mock_emit.assert_called_once()
            output = mock_emit.call_args[0][0]
            assert "⚡ [1/3]" in output
            assert "📂 list_files" in output
            assert "dir=src" in output

    def test_formatting_grep(self):
        """Test emit_operation_start formatting for grep."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            emit_operation_start(2, 5, "grep", {"search_string": "def hello", "directory": "."})

            mock_emit.assert_called_once()
            output = mock_emit.call_args[0][0]
            assert "⚡ [2/5]" in output
            assert "🔍 grep" in output
            assert "search='def hello'" in output

    def test_formatting_grep_truncates_long_search(self):
        """Test that grep search strings are truncated if too long."""
        long_search = "a" * 50
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            emit_operation_start(1, 1, "grep", {"search_string": long_search})

            output = mock_emit.call_args[0][0]
            assert "search='" in output
            assert "..." in output
            # Should be truncated to ~30 chars
            assert len(output) < len(long_search) + 50

    def test_formatting_read_files(self):
        """Test emit_operation_start formatting for read_files."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            emit_operation_start(3, 3, "read_files", {"file_paths": ["a.py", "b.py", "c.py"]})

            mock_emit.assert_called_once()
            output = mock_emit.call_args[0][0]
            assert "⚡ [3/3]" in output
            assert "📄 read_files" in output
            assert "3 files" in output

    def test_formatting_unknown_operation(self):
        """Test emit_operation_start formatting for unknown operation type."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            emit_operation_start(1, 1, "unknown_op", {"some_arg": "value"})

            mock_emit.assert_called_once()
            output = mock_emit.call_args[0][0]
            assert "⚡ [1/1]" in output
            assert "⚡ unknown_op" in output


class TestEmitOperationComplete:
    """Test emit_operation_complete formatting."""

    def test_formatting_list_files(self):
        """Test emit_operation_complete formatting for list_files."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            data = {
                "content": "file1.py\nfile2.py\ndir1/",
                "successful_reads": 0,
            }
            emit_operation_complete(1, 3, "list_files", {"directory": "src"}, 125.5, data)

            mock_emit.assert_called_once()
            output = mock_emit.call_args[0][0]
            assert "⚡ [1/3] ✅ list_files done" in output
            assert "126ms" in output or "125.5ms" in output or "125ms" in output
            assert "3 items" in output

    def test_formatting_grep(self):
        """Test emit_operation_complete formatting for grep."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            data = {
                "matches": [{}, {}, {}],
                "total_matches": 3,
            }
            emit_operation_complete(2, 4, "grep", {"search_string": "test"}, 75.0, data)

            mock_emit.assert_called_once()
            output = mock_emit.call_args[0][0]
            assert "⚡ [2/4] ✅ grep done" in output
            assert "75ms" in output or "75.0ms" in output
            assert "3 matches" in output

    def test_formatting_read_files(self):
        """Test emit_operation_complete formatting for read_files."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            data = {
                "files": [{"success": True}, {"success": True}, {"success": False}],
                "total_files": 3,
                "successful_reads": 2,
            }
            emit_operation_complete(3, 3, "read_files", {"file_paths": ["a.py", "b.py", "c.py"]}, 200.0, data)

            mock_emit.assert_called_once()
            output = mock_emit.call_args[0][0]
            assert "⚡ [3/3] ✅ read_files done" in output
            assert "200ms" in output or "200.0ms" in output
            assert "2/3 reads" in output or "2/3" in output


class TestEmitOperationError:
    """Test emit_operation_error formatting."""

    def test_formatting_error_message(self):
        """Test emit_operation_error formatting."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            emit_operation_error(2, 5, "read_files", "File not found: /path/to/file.py")

            mock_emit.assert_called_once()
            output = mock_emit.call_args[0][0]
            assert "⚡ [2/5] ❌ read_files failed:" in output
            assert "File not found: /path/to/file.py" in output

    def test_formatting_different_operation_types(self):
        """Test emit_operation_error with different operation types."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            emit_operation_error(1, 3, "list_files", "Permission denied")
            output1 = mock_emit.call_args[0][0]
            assert "❌ list_files failed:" in output1
            assert "Permission denied" in output1

            mock_emit.reset_mock()
            emit_operation_error(3, 3, "grep", "Invalid regex pattern")
            output2 = mock_emit.call_args[0][0]
            assert "❌ grep failed:" in output2
            assert "Invalid regex pattern" in output2


class TestMalformedPlanJson:
    """Test graceful handling of malformed plan_json."""

    def test_handles_invalid_json_gracefully(self):
        """Test that invalid JSON in plan_json doesn't raise exception."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            # Should not raise
            _on_pre_tool_call("turbo_execute", {"plan_json": "not valid json"})

            # Should still emit something (fallback message)
            mock_emit.assert_called()
            first_call = mock_emit.call_args_list[0][0][0]
            assert "🚀 Turbo Plan starting" in first_call

    def test_handles_missing_plan_json_key(self):
        """Test handling when plan_json key is missing."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            # Should not raise
            _on_pre_tool_call("turbo_execute", {})

            # Should still emit something
            mock_emit.assert_called()

    def test_handles_partial_malformed_data(self):
        """Test handling of partial/malformed plan data."""
        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_emit:
            # Missing operations array
            _on_pre_tool_call("turbo_execute", {"plan_json": json.dumps({"id": "test"})})

            mock_emit.assert_called()
            first_call = mock_emit.call_args_list[0][0][0]
            assert "🚀 Turbo Plan 'test' starting" in first_call


class TestFormatBriefArgs:
    """Test _format_brief_args helper function."""

    def test_list_files_formatting(self):
        """Test _format_brief_args for list_files."""
        result = _format_brief_args("list_files", {"directory": "src/components"})
        assert result == "dir=src/components"

        # Default directory
        result_default = _format_brief_args("list_files", {})
        assert result_default == "dir=."

    def test_grep_formatting(self):
        """Test _format_brief_args for grep."""
        result = _format_brief_args("grep", {"search_string": "def hello"})
        assert result == "search='def hello'"

    def test_grep_truncates_long_strings(self):
        """Test that grep search strings over 30 chars are truncated."""
        long_search = "a" * 50
        result = _format_brief_args("grep", {"search_string": long_search})
        assert "..." in result
        assert len(result) < len(long_search) + 20

    def test_read_files_formatting(self):
        """Test _format_brief_args for read_files."""
        result = _format_brief_args("read_files", {"file_paths": ["a.py", "b.py", "c.py"]})
        assert result == "3 files"

        result_single = _format_brief_args("read_files", {"file_paths": ["single.py"]})
        assert result_single == "1 files"

        result_empty = _format_brief_args("read_files", {"file_paths": []})
        assert result_empty == "0 files"

    def test_unknown_operation_type(self):
        """Test _format_brief_args for unknown operation type."""
        result = _format_brief_args("unknown_op", {"arg": "value"})
        assert result == ""


class TestFormatBriefStats:
    """Test _format_brief_stats helper function."""

    def test_list_files_stats(self):
        """Test _format_brief_stats for list_files."""
        data = {"content": "file1.py\nfile2.py\ndir1/\n\n"}
        result = _format_brief_stats("list_files", data)
        assert result == "3 items"

        # Empty content
        result_empty = _format_brief_stats("list_files", {"content": ""})
        assert result_empty == "0 items"

        # Non-string content (edge case)
        result_non_string = _format_brief_stats("list_files", {"content": None})
        assert result_non_string == ""

    def test_grep_stats(self):
        """Test _format_brief_stats for grep."""
        data = {"total_matches": 42}
        result = _format_brief_stats("grep", data)
        assert result == "42 matches"

        data_zero = {"total_matches": 0}
        result_zero = _format_brief_stats("grep", data_zero)
        assert result_zero == "0 matches"

    def test_read_files_stats(self):
        """Test _format_brief_stats for read_files."""
        data = {"successful_reads": 5, "total_files": 8}
        result = _format_brief_stats("read_files", data)
        assert result == "5/8 reads"

        data_all_success = {"successful_reads": 3, "total_files": 3}
        result_all = _format_brief_stats("read_files", data_all_success)
        assert result_all == "3/3 reads"

    def test_unknown_operation_type_stats(self):
        """Test _format_brief_stats for unknown operation type."""
        result = _format_brief_stats("unknown_op", {"some": "data"})
        assert result == ""


class TestIntegration:
    """Integration tests for the notifications module."""

    def test_full_lifecycle_simulation(self):
        """Test simulating a full turbo_execute lifecycle with notifications."""
        plan_data = {
            "id": "integration-test",
            "operations": [
                {"type": "list_files", "args": {"directory": "src"}, "priority": 1},
                {"type": "grep", "args": {"search_string": "class "}, "priority": 2},
            ],
        }

        result_data = {
            "status": "completed",
            "success_count": 2,
            "error_count": 0,
            "total_duration_ms": 300.0,
            "operation_results": [
                {"operation_id": "op1", "type": "list_files", "status": "success"},
                {"operation_id": "op2", "type": "grep", "status": "success"},
            ],
        }

        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_info, \
             patch("code_puppy.plugins.turbo_executor.notifications.emit_success") as mock_success:
            # Pre-tool call
            _on_pre_tool_call("turbo_execute", {"plan_json": json.dumps(plan_data)})

            # Post-tool call
            _on_post_tool_call("turbo_execute", {}, result_data, 300.0)

            # Verify pre-tool call outputs
            assert mock_info.call_count >= 2
            first_info = mock_info.call_args_list[0][0][0]
            assert "🚀 Turbo Plan 'integration-test' starting" in first_info

            # Verify post-tool call outputs
            mock_success.assert_called_once()
            success_msg = mock_success.call_args[0][0]
            assert "2 success" in success_msg
            assert "0 errors" in success_msg

    def test_error_lifecycle_simulation(self):
        """Test simulating a failed turbo_execute lifecycle."""
        plan_data = {
            "id": "error-test",
            "operations": [
                {"type": "list_files", "args": {"directory": "/nonexistent"}, "priority": 1},
            ],
        }

        result_data = {
            "status": "failed",
            "success_count": 0,
            "error_count": 1,
            "total_duration_ms": 50.0,
            "operation_results": [
                {"operation_id": "op1", "type": "list_files", "status": "error", "error": "Directory not found"},
            ],
        }

        with patch("code_puppy.plugins.turbo_executor.notifications.emit_info") as mock_info, \
             patch("code_puppy.plugins.turbo_executor.notifications.emit_success") as mock_success, \
             patch("code_puppy.plugins.turbo_executor.notifications.emit_warning") as mock_warning:
            # Pre-tool call
            _on_pre_tool_call("turbo_execute", {"plan_json": json.dumps(plan_data)})

            # Post-tool call
            _on_post_tool_call("turbo_execute", {}, result_data, 50.0)

            # Verify success was called (plan completed, even with errors)
            mock_success.assert_called_once()

            # Verify warning was called for the error
            mock_warning.assert_called_once()
            warning_msg = mock_warning.call_args[0][0]
            assert "❌ list_files (op1): Directory not found" in warning_msg
