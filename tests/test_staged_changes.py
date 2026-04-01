"""Tests for staged changes sandbox."""

import os
import tempfile
from pathlib import Path

import pytest

from code_puppy.staged_changes import (
    get_staged_count,
    ChangeType,
    StagedChange,
    StagedChangesSandbox,
    get_sandbox,
    reset_sandbox,
    is_staging_enabled,
    stage_create,
    stage_replace,
    stage_delete_snippet,
    clear_staged,
)


class TestStagedChange:
    """Test StagedChange dataclass."""
    
    def test_create_staged_change(self):
        """Test creating a staged change."""
        change = StagedChange(
            change_id="test-123",
            change_type=ChangeType.CREATE,
            file_path="/tmp/test.py",
            content="print('hello')",
            description="Create test file",
        )
        assert change.change_id == "test-123"
        assert change.change_type == ChangeType.CREATE
        assert change.file_path == "/tmp/test.py"
        assert change.content == "print('hello')"
        assert change.description == "Create test file"
        assert not change.applied
        assert not change.rejected
    
    def test_serialization(self):
        """Test serialization to/from dict."""
        change = StagedChange(
            change_id="test-456",
            change_type=ChangeType.REPLACE,
            file_path="/tmp/test.py",
            old_str="old",
            new_str="new",
        )
        
        data = change.to_dict()
        assert data["change_id"] == "test-456"
        assert data["change_type"] == "REPLACE"
        
        restored = StagedChange.from_dict(data)
        assert restored.change_id == "test-456"
        assert restored.change_type == ChangeType.REPLACE


class TestStagedChangesSandbox:
    """Test StagedChangesSandbox."""
    
    def test_enable_disable(self):
        """Test enabling and disabling staging."""
        sandbox = StagedChangesSandbox()
        assert not sandbox.enabled
        
        sandbox.enable()
        assert sandbox.enabled
        
        sandbox.disable()
        assert not sandbox.enabled
        
        result = sandbox.toggle()
        assert result == True
        assert sandbox.enabled
        
        result = sandbox.toggle()
        assert result == False
        assert not sandbox.enabled
    
    def test_add_changes(self):
        """Test adding different types of changes."""
        sandbox = StagedChangesSandbox()
        
        # Add create
        create = sandbox.add_create("/tmp/test1.py", "content", "Create file")
        assert create.change_type == ChangeType.CREATE
        
        # Add replace
        replace = sandbox.add_replace("/tmp/test2.py", "old", "new", "Replace text")
        assert replace.change_type == ChangeType.REPLACE
        
        # Add delete snippet
        delete = sandbox.add_delete_snippet("/tmp/test3.py", "snippet", "Delete snippet")
        assert delete.change_type == ChangeType.DELETE_SNIPPET
        
        assert sandbox.count() == 3
    
    def test_clear_changes(self):
        """Test clearing all changes."""
        sandbox = StagedChangesSandbox()
        sandbox.add_create("/tmp/test.py", "content")
        assert sandbox.count() == 1
        
        sandbox.clear()
        assert sandbox.count() == 0
        assert sandbox.is_empty()
    
    def test_remove_change(self):
        """Test removing a specific change."""
        sandbox = StagedChangesSandbox()
        change = sandbox.add_create("/tmp/test.py", "content")
        
        assert sandbox.remove_change(change.change_id)
        assert sandbox.count() == 0
        
        # Removing non-existent should return False
        assert not sandbox.remove_change("non-existent")
    
    def test_get_changes_for_file(self):
        """Test getting changes for a specific file."""
        sandbox = StagedChangesSandbox()
        sandbox.add_create("/tmp/file1.py", "content")
        sandbox.add_replace("/tmp/file1.py", "old", "new")
        sandbox.add_create("/tmp/file2.py", "content")
        
        file1_changes = sandbox.get_changes_for_file("/tmp/file1.py")
        assert len(file1_changes) == 2
        
        file2_changes = sandbox.get_changes_for_file("/tmp/file2.py")
        assert len(file2_changes) == 1


class TestDiffGeneration:
    """Test diff generation."""
    
    def test_diff_for_create(self):
        """Test generating diff for file creation."""
        sandbox = StagedChangesSandbox()
        change = sandbox.add_create("/tmp/new_file.py", "print('hello')\n")
        
        diff = sandbox.generate_diff(change)
        assert "+++ b/new_file.py" in diff
        assert "print('hello')" in diff
    
    def test_diff_for_replace(self, tmp_path):
        """Test generating diff for text replacement."""
        # Create a temporary file
        test_file = tmp_path / "test.py"
        test_file.write_text("old text here\nmore content\n")
        
        sandbox = StagedChangesSandbox()
        change = sandbox.add_replace(str(test_file), "old text", "new text")
        
        diff = sandbox.generate_diff(change)
        assert "--- a/test.py" in diff
        assert "+++ b/test.py" in diff
        assert "-old text" in diff
        assert "+new text" in diff
    
    def test_diff_for_delete_snippet(self, tmp_path):
        """Test generating diff for snippet deletion."""
        test_file = tmp_path / "test.py"
        test_file.write_text("keep this\nremove this\nkeep this too\n")
        
        sandbox = StagedChangesSandbox()
        change = sandbox.add_delete_snippet(str(test_file), "remove this")
        
        diff = sandbox.generate_diff(change)
        assert "--- a/test.py" in diff
        assert "+++ b/test.py" in diff
        assert "-remove this" in diff
    
    def test_combined_diff(self, tmp_path):
        """Test generating combined diff."""
        test_file = tmp_path / "test.py"
        test_file.write_text("old text\n")
        
        sandbox = StagedChangesSandbox()
        sandbox.add_replace(str(test_file), "old", "new")
        sandbox.add_create("/tmp/new.py", "new file")
        
        combined = sandbox.generate_combined_diff()
        assert "old" in combined or "new" in combined


class TestSummary:
    """Test summary generation."""
    
    def test_get_summary(self):
        """Test getting summary of changes."""
        sandbox = StagedChangesSandbox()
        sandbox.enable()
        
        sandbox.add_create("/tmp/file1.py", "content")
        sandbox.add_replace("/tmp/file2.py", "old", "new")
        sandbox.add_replace("/tmp/file3.py", "a", "b")
        
        summary = sandbox.get_summary()
        assert summary["total"] == 3
        assert summary["by_type"]["CREATE"] == 1
        assert summary["by_type"]["REPLACE"] == 2
        assert summary["by_file"] == 3
        assert summary["enabled"] == True
        assert "session_id" in summary


class TestPersistence:
    """Test saving and loading from disk."""
    
    def test_save_and_load(self, tmp_path):
        """Test persisting staged changes."""
        import code_puppy.staged_changes as sc
        
        # Create sandbox with custom stage dir
        sandbox = StagedChangesSandbox()
        original_stage_dir = sc.STAGE_DIR
        
        try:
            # Use temp directory
            sc.STAGE_DIR = tmp_path
            sandbox._ensure_stage_dir()
            
            sandbox.add_create("/tmp/test.py", "content")
            sandbox.enable()
            
            # Save
            save_path = sandbox.save_to_disk()
            assert save_path.exists()
            
            # Create new sandbox and load
            new_sandbox = StagedChangesSandbox()
            new_sandbox._session_id = sandbox._session_id
            
            assert new_sandbox.load_from_disk()
            assert new_sandbox.count() == 1
            assert new_sandbox.enabled
        finally:
            sc.STAGE_DIR = original_stage_dir


class TestGlobalFunctions:
    """Test global convenience functions."""
    
    def test_global_sandbox(self):
        """Test global sandbox functions."""
        reset_sandbox()
        
        assert is_staging_enabled() == False
        
        # Enable via sandbox
        get_sandbox().enable()
        assert is_staging_enabled() == True
        
        # Stage changes
        change = stage_create("/tmp/test.py", "content", "Test create")
        assert change.change_type == ChangeType.CREATE
        
        assert get_staged_count() == 1
        
        clear_staged()
        assert get_staged_count() == 0
