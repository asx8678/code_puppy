"""Tests for code_puppy.compaction.file_ops_tracker."""

import pytest
from code_puppy.compaction.file_ops_tracker import (
    FileOpsTracker,
    extract_file_ops_from_messages,
    format_file_ops_xml,
)


class TestFileOpsTracker:
    def test_empty_tracker(self):
        t = FileOpsTracker()
        assert not t.has_ops
        assert t.read_files == []
        assert t.modified_files == []

    def test_add_operations(self):
        t = FileOpsTracker()
        t.add_read("src/main.py")
        t.add_write("src/config.py")
        t.add_edit("src/utils.py")
        assert t.has_ops
        assert t.read_files == ["src/main.py"]
        assert t.modified_files == ["src/config.py", "src/utils.py"]

    def test_deduplication(self):
        t = FileOpsTracker()
        t.add_read("src/main.py")
        t.add_read("src/main.py")
        assert t.read_files == ["src/main.py"]

    def test_modified_combines_written_and_edited(self):
        t = FileOpsTracker()
        t.add_write("a.py")
        t.add_edit("b.py")
        t.add_write("b.py")  # duplicate across categories
        assert t.modified_files == ["a.py", "b.py"]

    def test_merge(self):
        t1 = FileOpsTracker()
        t1.add_read("a.py")
        t1.add_write("b.py")

        t2 = FileOpsTracker()
        t2.add_read("c.py")
        t2.add_edit("d.py")

        t1.merge(t2)
        assert t1.read_files == ["a.py", "c.py"]
        assert t1.modified_files == ["b.py", "d.py"]

    def test_clear(self):
        t = FileOpsTracker()
        t.add_read("a.py")
        t.add_write("b.py")
        t.clear()
        assert not t.has_ops

    def test_sorted_output(self):
        t = FileOpsTracker()
        t.add_read("z.py")
        t.add_read("a.py")
        t.add_read("m.py")
        assert t.read_files == ["a.py", "m.py", "z.py"]


class TestExtractFileOpsFromMessages:
    """Tests for extracting file ops from pydantic-ai messages."""

    def _make_tool_call_message(self, tool_name: str, args: dict):
        """Create a minimal ModelResponse with a ToolCallPart."""
        try:
            from pydantic_ai.messages import ModelResponse, ToolCallPart
        except ImportError:
            pytest.skip("pydantic-ai not installed")
        
        part = ToolCallPart(tool_name=tool_name, args=args, tool_call_id="test-id")
        return ModelResponse(parts=[part])

    def test_read_file_extraction(self):
        msg = self._make_tool_call_message("read_file", {"file_path": "src/main.py"})
        tracker = extract_file_ops_from_messages([msg])
        assert tracker.read_files == ["src/main.py"]

    def test_write_file_extraction(self):
        msg = self._make_tool_call_message("write_to_file", {"path": "src/out.py", "content": "..."})
        tracker = extract_file_ops_from_messages([msg])
        assert tracker.modified_files == ["src/out.py"]

    def test_edit_file_extraction(self):
        msg = self._make_tool_call_message("edit_file", {"file_path": "src/fix.py", "replacements": []})
        tracker = extract_file_ops_from_messages([msg])
        assert tracker.modified_files == ["src/fix.py"]

    def test_replace_in_file_extraction(self):
        msg = self._make_tool_call_message("replace_in_file", {"path": "src/a.py"})
        tracker = extract_file_ops_from_messages([msg])
        assert tracker.modified_files == ["src/a.py"]

    def test_multiple_messages(self):
        msgs = [
            self._make_tool_call_message("read_file", {"file_path": "a.py"}),
            self._make_tool_call_message("write_to_file", {"path": "b.py", "content": ""}),
            self._make_tool_call_message("edit_file", {"file_path": "c.py"}),
        ]
        tracker = extract_file_ops_from_messages(msgs)
        assert tracker.read_files == ["a.py"]
        assert tracker.modified_files == ["b.py", "c.py"]

    def test_accumulate_into_existing_tracker(self):
        existing = FileOpsTracker()
        existing.add_read("old.py")
        
        msg = self._make_tool_call_message("read_file", {"file_path": "new.py"})
        tracker = extract_file_ops_from_messages([msg], tracker=existing)
        assert tracker is existing
        assert tracker.read_files == ["new.py", "old.py"]

    def test_unknown_tool_ignored(self):
        msg = self._make_tool_call_message("unknown_tool", {"file_path": "x.py"})
        tracker = extract_file_ops_from_messages([msg])
        assert not tracker.has_ops

    def test_missing_path_ignored(self):
        msg = self._make_tool_call_message("read_file", {"content": "no path here"})
        tracker = extract_file_ops_from_messages([msg])
        assert not tracker.has_ops

    def test_non_response_messages_skipped(self):
        """ModelRequest messages should be skipped."""
        try:
            from pydantic_ai.messages import ModelRequest, UserPromptPart
        except ImportError:
            pytest.skip("pydantic-ai not installed")
        
        msg = ModelRequest(parts=[UserPromptPart(content="hello")])
        tracker = extract_file_ops_from_messages([msg])
        assert not tracker.has_ops

    def test_empty_messages(self):
        tracker = extract_file_ops_from_messages([])
        assert not tracker.has_ops


class TestFormatFileOpsXml:
    def test_empty_tracker(self):
        t = FileOpsTracker()
        assert format_file_ops_xml(t) == ""

    def test_read_only(self):
        t = FileOpsTracker()
        t.add_read("src/main.py")
        t.add_read("src/utils.py")
        result = format_file_ops_xml(t)
        assert "<read-files>" in result
        assert "- src/main.py" in result
        assert "- src/utils.py" in result
        assert "<modified-files>" not in result

    def test_modified_only(self):
        t = FileOpsTracker()
        t.add_write("out.py")
        result = format_file_ops_xml(t)
        assert "<modified-files>" in result
        assert "- out.py" in result
        assert "<read-files>" not in result

    def test_both_sections(self):
        t = FileOpsTracker()
        t.add_read("a.py")
        t.add_write("b.py")
        result = format_file_ops_xml(t)
        assert "<read-files>" in result
        assert "<modified-files>" in result
        assert "- a.py" in result
        assert "- b.py" in result

    def test_sorted_output(self):
        t = FileOpsTracker()
        t.add_read("z.py")
        t.add_read("a.py")
        result = format_file_ops_xml(t)
        # a.py should come before z.py
        a_pos = result.index("a.py")
        z_pos = result.index("z.py")
        assert a_pos < z_pos
