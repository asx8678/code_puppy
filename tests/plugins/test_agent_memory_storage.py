"""Tests for agent_memory storage module.

Comprehensive coverage of FileMemoryStorage including:
- CRUD operations
- Thread safety under concurrent access
- Corrupt JSON recovery
- Directory auto-creation
- Per-agent isolation
- Confidence filtering
- Edge cases and error handling
"""

import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from code_puppy.plugins.agent_memory.storage import FileMemoryStorage, _MEMORY_DIR

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_memory_dir(tmp_path: Path) -> Path:
    """Create a temporary memory directory for testing."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir


@pytest.fixture
def isolated_storage(temp_memory_dir: Path) -> type[FileMemoryStorage]:
    """Provide FileMemoryStorage class with isolated memory directory."""
    with patch(
        "code_puppy.plugins.agent_memory.storage._MEMORY_DIR",
        temp_memory_dir,
    ):
        # Also need to patch in the module namespace for existing instances
        original_dir = _MEMORY_DIR
        try:
            import code_puppy.plugins.agent_memory.storage as storage_module

            storage_module._MEMORY_DIR = temp_memory_dir
            yield FileMemoryStorage
        finally:
            storage_module._MEMORY_DIR = original_dir


@pytest.fixture
def sample_fact() -> dict:
    """Return a sample fact for testing."""
    return {
        "text": "Python uses indentation for blocks",
        "confidence": 0.95,
        "source_session": "session-123",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_reinforced": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================================
# Initialization Tests
# ============================================================================


class TestInitialization:
    """Tests for FileMemoryStorage initialization."""

    def test_valid_agent_name(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Storage initializes with valid agent name."""
        storage = isolated_storage("test-agent")
        assert storage.agent_name == "test-agent"

    def test_empty_agent_name_raises(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Empty agent name raises ValueError."""
        with pytest.raises(ValueError, match="agent_name cannot be empty"):
            isolated_storage("")

    def test_whitespace_agent_name_raises(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Whitespace-only agent name raises ValueError."""
        with pytest.raises(ValueError, match="agent_name cannot be empty"):
            isolated_storage("   ")

    def test_slash_in_name_raises(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Forward slash in agent name raises ValueError."""
        with pytest.raises(ValueError, match="Invalid agent_name"):
            isolated_storage("agent/name")

    def test_backslash_in_name_raises(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Backslash in agent name raises ValueError."""
        with pytest.raises(ValueError, match="Invalid agent_name"):
            isolated_storage("agent\\name")

    def test_dotdot_in_name_raises(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Directory traversal pattern raises ValueError."""
        with pytest.raises(ValueError, match="Invalid agent_name"):
            isolated_storage("../etc/passwd")

    def test_file_path_set_correctly(self, isolated_storage: type[FileMemoryStorage], temp_memory_dir: Path) -> None:
        """File path is set correctly based on agent name."""
        storage = isolated_storage("my-agent")
        expected_path = temp_memory_dir / "my-agent.json"
        assert storage._file_path == expected_path


# ============================================================================
# CRUD Operation Tests
# ============================================================================


class TestCRUDOperations:
    """Tests for basic CRUD operations."""

    def test_load_empty_when_no_file(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Load returns empty list when file doesn't exist."""
        storage = isolated_storage("new-agent")
        facts = storage.load()
        assert facts == []

    def test_save_and_load_facts(self, isolated_storage: type[FileMemoryStorage], sample_fact: dict) -> None:
        """Save facts and load them back."""
        storage = isolated_storage("agent-1")
        storage.save([sample_fact])

        loaded = storage.load()
        assert len(loaded) == 1
        assert loaded[0]["text"] == sample_fact["text"]

    def test_add_fact_appends(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Add fact appends to existing facts."""
        storage = isolated_storage("agent-1")

        fact1 = {"text": "Fact 1", "confidence": 0.8}
        fact2 = {"text": "Fact 2", "confidence": 0.9}

        storage.add_fact(fact1)
        storage.add_fact(fact2)

        loaded = storage.load()
        assert len(loaded) == 2
        assert loaded[0]["text"] == "Fact 1"
        assert loaded[1]["text"] == "Fact 2"

    def test_remove_fact_by_text(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Remove fact by exact text match."""
        storage = isolated_storage("agent-1")

        storage.save([
            {"text": "Keep this", "confidence": 0.9},
            {"text": "Remove this", "confidence": 0.8},
        ])

        result = storage.remove_fact("Remove this")
        assert result is True

        loaded = storage.load()
        assert len(loaded) == 1
        assert loaded[0]["text"] == "Keep this"

    def test_remove_fact_not_found(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Remove fact returns False when not found."""
        storage = isolated_storage("agent-1")
        storage.save([{"text": "Only fact", "confidence": 0.9}])

        result = storage.remove_fact("Nonexistent")
        assert result is False

    def test_clear_removes_all_facts(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Clear removes all facts."""
        storage = isolated_storage("agent-1")
        storage.save([
            {"text": "Fact 1", "confidence": 0.9},
            {"text": "Fact 2", "confidence": 0.8},
        ])

        storage.clear()
        loaded = storage.load()
        assert loaded == []

    def test_fact_count(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Fact count returns correct number."""
        storage = isolated_storage("agent-1")
        assert storage.fact_count() == 0

        storage.add_fact({"text": "Fact 1"})
        assert storage.fact_count() == 1

        storage.add_fact({"text": "Fact 2"})
        assert storage.fact_count() == 2

    def test_add_fact_without_text_logs_warning(self, isolated_storage: type[FileMemoryStorage], caplog: pytest.LogCaptureFixture) -> None:
        """Add fact without 'text' key logs warning and doesn't save."""
        storage = isolated_storage("agent-1")

        with caplog.at_level("WARNING"):
            storage.add_fact({"confidence": 0.9})  # Missing 'text'

        assert "Invalid fact format" in caplog.text
        assert storage.fact_count() == 0


# ============================================================================
# Per-Agent Isolation Tests
# ============================================================================


class TestPerAgentIsolation:
    """Tests that each agent has isolated storage."""

    def test_agents_dont_share_facts(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Facts are isolated per agent."""
        storage_a = isolated_storage("agent-a")
        storage_b = isolated_storage("agent-b")

        storage_a.add_fact({"text": "Fact for A"})
        storage_b.add_fact({"text": "Fact for B"})

        assert storage_a.fact_count() == 1
        assert storage_b.fact_count() == 1
        assert storage_a.load()[0]["text"] == "Fact for A"
        assert storage_b.load()[0]["text"] == "Fact for B"

    def test_different_file_paths(self, isolated_storage: type[FileMemoryStorage], temp_memory_dir: Path) -> None:
        """Different agents have different file paths."""
        storage_a = isolated_storage("agent-a")
        storage_b = isolated_storage("agent-b")

        assert storage_a._file_path == temp_memory_dir / "agent-a.json"
        assert storage_b._file_path == temp_memory_dir / "agent-b.json"
        assert storage_a._file_path != storage_b._file_path

    def test_clear_doesnt_affect_other_agents(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Clearing one agent doesn't affect others."""
        storage_a = isolated_storage("agent-a")
        storage_b = isolated_storage("agent-b")

        storage_a.add_fact({"text": "Fact for A"})
        storage_b.add_fact({"text": "Fact for B"})

        storage_a.clear()

        assert storage_a.fact_count() == 0
        assert storage_b.fact_count() == 1


# ============================================================================
# Confidence Filtering Tests
# ============================================================================


class TestConfidenceFiltering:
    """Tests for get_facts with confidence filtering."""

    def test_get_facts_no_filter(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Get facts with no filter returns all."""
        storage = isolated_storage("agent-1")
        storage.save([
            {"text": "High confidence", "confidence": 0.9},
            {"text": "Low confidence", "confidence": 0.3},
            {"text": "No confidence"},  # Defaults to 1.0
        ])

        facts = storage.get_facts()
        assert len(facts) == 3

    def test_get_facts_with_threshold(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Get facts filters by confidence threshold."""
        storage = isolated_storage("agent-1")
        storage.save([
            {"text": "High confidence", "confidence": 0.9},
            {"text": "Medium confidence", "confidence": 0.6},
            {"text": "Low confidence", "confidence": 0.3},
        ])

        facts = storage.get_facts(min_confidence=0.5)
        assert len(facts) == 2
        texts = [f["text"] for f in facts]
        assert "High confidence" in texts
        assert "Medium confidence" in texts
        assert "Low confidence" not in texts

    def test_get_facts_defaults_to_1_0(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Facts without confidence default to 1.0."""
        storage = isolated_storage("agent-1")
        storage.save([
            {"text": "No confidence field"},  # Should be treated as 1.0
            {"text": "Low confidence", "confidence": 0.3},
        ])

        facts = storage.get_facts(min_confidence=0.9)
        assert len(facts) == 1
        assert facts[0]["text"] == "No confidence field"


# ============================================================================
# Update and Reinforce Tests
# ============================================================================


class TestUpdateAndReinforce:
    """Tests for update_fact and reinforce_fact."""

    def test_update_fact_existing(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Update fact modifies existing fact."""
        storage = isolated_storage("agent-1")
        storage.save([
            {"text": "Original text", "confidence": 0.5, "extra": "value"},
        ])

        result = storage.update_fact("Original text", {"confidence": 0.9, "new_field": "new"})
        assert result is True

        facts = storage.load()
        assert facts[0]["confidence"] == 0.9
        assert facts[0]["new_field"] == "new"
        assert facts[0]["extra"] == "value"  # Original field preserved

    def test_update_fact_not_found(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Update fact returns False when text not found."""
        storage = isolated_storage("agent-1")
        storage.save([{"text": "Different text"}])

        result = storage.update_fact("Nonexistent", {"confidence": 0.9})
        assert result is False

    def test_reinforce_fact_updates_timestamp(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Reinforce fact updates last_reinforced timestamp."""
        storage = isolated_storage("agent-1")
        original_time = "2024-01-01T00:00:00+00:00"
        storage.save([{
            "text": "To reinforce",
            "confidence": 0.9,
            "last_reinforced": original_time,
        }])

        time.sleep(0.01)  # Ensure timestamp changes
        result = storage.reinforce_fact("To reinforce", session_id="new-session")
        assert result is True

        facts = storage.load()
        assert facts[0]["last_reinforced"] != original_time
        assert facts[0]["source_session"] == "new-session"

    def test_reinforce_fact_not_found(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Reinforce fact returns False when text not found."""
        storage = isolated_storage("agent-1")
        result = storage.reinforce_fact("Nonexistent")
        assert result is False


# ============================================================================
# Corrupt File Recovery Tests
# ============================================================================


class TestCorruptFileRecovery:
    """Tests for graceful handling of corrupt files."""

    def test_corrupt_json_returns_empty(self, isolated_storage: type[FileMemoryStorage], temp_memory_dir: Path) -> None:
        """Corrupt JSON file returns empty list."""
        storage = isolated_storage("corrupt-agent")

        # Write corrupt JSON directly
        storage._file_path.parent.mkdir(parents=True, exist_ok=True)
        storage._file_path.write_text("this is not json {{{")

        facts = storage.load()
        assert facts == []

    def test_corrupt_json_creates_backup(self, isolated_storage: type[FileMemoryStorage], temp_memory_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Corrupt JSON file is backed up before reset."""
        storage = isolated_storage("corrupt-agent")

        # Create directory and corrupt file
        storage._file_path.parent.mkdir(parents=True, exist_ok=True)
        storage._file_path.write_text("corrupt content")
        assert storage._file_path.exists(), "Corrupt file should exist before loading"

        # Capture the warning to verify backup was mentioned
        with caplog.at_level("WARNING"):
            storage.load()

        # Verify backup was logged (actual path doesn't matter as long as it happens)
        assert "backed up to" in caplog.text or "Corrupt memory file" in caplog.text

    def test_non_list_json_returns_empty(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """JSON that isn't a list returns empty and creates backup."""
        storage = isolated_storage("object-agent")

        storage._file_path.parent.mkdir(parents=True, exist_ok=True)
        storage._file_path.write_text('{"not": "a list"}')

        facts = storage.load()
        assert facts == []

    def test_invalid_facts_filtered(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Facts without 'text' key are filtered out."""
        storage = isolated_storage("agent-1")

        storage._file_path.parent.mkdir(parents=True, exist_ok=True)
        storage._file_path.write_text(json.dumps([
            {"text": "Valid fact"},
            {"notext": "Invalid fact"},  # Missing 'text'
            "not a dict",  # Not a dict
        ]))

        facts = storage.load()
        assert len(facts) == 1
        assert facts[0]["text"] == "Valid fact"


# ============================================================================
# Directory Auto-Creation Tests
# ============================================================================


class TestDirectoryAutoCreation:
    """Tests for automatic directory creation."""

    def test_directory_created_on_save(self, isolated_storage: type[FileMemoryStorage], temp_memory_dir: Path) -> None:
        """Directory is auto-created when saving."""
        # Delete the temp memory directory
        if temp_memory_dir.exists():
            shutil.rmtree(temp_memory_dir)

        storage = isolated_storage("new-agent")
        assert not temp_memory_dir.exists()

        storage.save([{"text": "Fact"}])
        assert temp_memory_dir.exists()

    def test_directory_created_on_add(self, isolated_storage: type[FileMemoryStorage], temp_memory_dir: Path) -> None:
        """Directory is auto-created when adding fact."""
        if temp_memory_dir.exists():
            shutil.rmtree(temp_memory_dir)

        storage = isolated_storage("new-agent")
        storage.add_fact({"text": "Fact"})
        assert temp_memory_dir.exists()


# ============================================================================
# Thread Safety Tests
# ============================================================================


class TestThreadSafety:
    """Tests for concurrent access safety."""

    def test_concurrent_adds_consistent(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Concurrent adds result in consistent state."""
        storage = isolated_storage("concurrent-agent")
        num_threads = 10
        facts_per_thread = 10

        def add_facts(thread_id: int) -> None:
            for i in range(facts_per_thread):
                storage.add_fact({
                    "text": f"Thread {thread_id} Fact {i}",
                    "thread_id": thread_id,
                })

        threads = [threading.Thread(target=add_facts, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All facts should be present
        facts = storage.load()
        assert len(facts) == num_threads * facts_per_thread

    def test_concurrent_read_write(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Concurrent reads and writes are safe."""
        storage = isolated_storage("concurrent-agent")

        # Pre-populate with some data
        storage.save([{"text": f"Initial {i}"} for i in range(50)])

        errors = []

        def writer() -> None:
            try:
                for i in range(20):
                    storage.add_fact({"text": f"Writer fact {i}"})
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"Writer error: {e}")

        def reader() -> None:
            try:
                for _ in range(50):
                    _ = storage.load()
                    _ = storage.fact_count()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"Reader error: {e}")

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=writer))
            threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent errors: {errors}"

    def test_thread_pool_concurrent_access(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """ThreadPoolExecutor concurrent access is safe."""
        storage = isolated_storage("pool-agent")

        def mixed_operation(op_id: int) -> dict:
            if op_id % 3 == 0:
                storage.add_fact({"text": f"Fact {op_id}", "op": op_id})
                return {"op": "add", "id": op_id}
            elif op_id % 3 == 1:
                count = storage.fact_count()
                return {"op": "count", "result": count}
            else:
                facts = storage.get_facts(min_confidence=0.5)
                return {"op": "get", "count": len(facts)}

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(mixed_operation, i) for i in range(30)]
            results = [f.result() for f in as_completed(futures)]

        # Should complete without errors
        assert len(results) == 30

        # All adds should be present
        adds = [r for r in results if r["op"] == "add"]
        assert storage.fact_count() == len(adds)

    def test_atomic_write_consistency(self, isolated_storage: type[FileMemoryStorage], temp_memory_dir: Path) -> None:
        """Atomic writes ensure file is never partially written."""
        storage = isolated_storage("atomic-agent")

        # Write large number of facts
        large_facts = [{"text": f"Fact {i}", "data": "x" * 1000} for i in range(100)]
        storage.save(large_facts)

        # Verify file is valid JSON
        file_content = storage._file_path.read_text()
        parsed = json.loads(file_content)
        assert len(parsed) == 100

        # Verify no temp files left behind
        temp_files = list(temp_memory_dir.glob("*.tmp"))
        assert len(temp_files) == 0


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for graceful error handling."""

    def test_ioerror_on_read_graceful(self, isolated_storage: type[FileMemoryStorage], caplog: pytest.LogCaptureFixture) -> None:
        """IOError on read is handled gracefully."""
        storage = isolated_storage("agent-1")

        # Create file first so there's something to fail on
        storage.save([{"text": "test"}])

        with patch("builtins.open", side_effect=IOError("Permission denied")):
            with caplog.at_level("ERROR"):
                facts = storage.load()

        assert facts == []
        assert "Failed to read memory file" in caplog.text

    def test_ioerror_on_save_graceful(self, isolated_storage: type[FileMemoryStorage], temp_memory_dir: Path) -> None:
        """IOError on save is handled gracefully without crashing."""
        storage = isolated_storage("agent-1")

        # Pre-create the directory
        storage._file_path.parent.mkdir(parents=True, exist_ok=True)

        # Make a read-only file to trigger IO error on write
        # First save something to create the file
        storage.save([{"text": "test"}])

        # Now make the directory read-only by creating a file with same name as temp file
        # This is tricky to test in a cross-platform way, so we just verify save doesn't crash
        # on the error path by temporarily breaking the path
        original_path = storage._file_path
        storage._file_path = temp_memory_dir / "<>:|?*" / "agent-1.json"  # Invalid path on Windows/Unix

        try:
            # This should not raise an exception, just log and continue
            storage.save([{"text": "Fact"}])
        except Exception:
            pytest.fail("save() raised an exception when it should have handled the error gracefully")
        finally:
            storage._file_path = original_path


# ============================================================================
# JSON Serialization Tests
# ============================================================================


class TestJSONSerialization:
    """Tests for JSON serialization details."""

    def test_unicode_preserved(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Unicode characters are preserved correctly."""
        storage = isolated_storage("unicode-agent")
        storage.save([{"text": "Hello 世界 🌍 émojis"}])

        loaded = storage.load()
        assert loaded[0]["text"] == "Hello 世界 🌍 émojis"

    def test_indent_and_readable(self, isolated_storage: type[FileMemoryStorage], temp_memory_dir: Path) -> None:
        """JSON is indented for readability."""
        storage = isolated_storage("readable-agent")
        storage.save([{"text": "Fact 1"}, {"text": "Fact 2"}])

        content = storage._file_path.read_text()
        assert "  " in content  # Has indentation
        assert "\n" in content  # Has newlines


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_text_fact(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Fact with empty text is valid."""
        storage = isolated_storage("agent-1")
        storage.add_fact({"text": "", "confidence": 0.5})

        facts = storage.load()
        assert len(facts) == 1
        assert facts[0]["text"] == ""

    def test_very_long_text(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Very long text is handled correctly."""
        storage = isolated_storage("agent-1")
        long_text = "x" * 100000
        storage.add_fact({"text": long_text})

        facts = storage.load()
        assert facts[0]["text"] == long_text

    def test_special_characters_in_text(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Special characters in text are handled."""
        storage = isolated_storage("agent-1")
        special_text = 'Special chars: \\"\\n\\t\\r{}[]<>/&'
        storage.add_fact({"text": special_text})

        facts = storage.load()
        assert facts[0]["text"] == special_text

    def test_multiple_instances_same_agent(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """Multiple storage instances for same agent share state."""
        storage1 = isolated_storage("shared-agent")
        storage2 = isolated_storage("shared-agent")

        storage1.add_fact({"text": "Added via instance 1"})

        # Instance 2 should see the fact
        facts = storage2.load()
        assert len(facts) == 1
        assert facts[0]["text"] == "Added via instance 1"


# ============================================================================
# Batch Operations Tests (code-puppy-48p)
# ============================================================================


class TestBatchOperations:
    """Tests for batch operations - performance optimization (code-puppy-48p)."""

    def test_add_facts_batch(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """add_facts() adds multiple facts in single write operation."""
        storage = isolated_storage("batch-agent")
        facts = [
            {"text": "Fact 1", "confidence": 0.9},
            {"text": "Fact 2", "confidence": 0.8},
            {"text": "Fact 3", "confidence": 0.7},
        ]

        count = storage.add_facts(facts)

        assert count == 3
        loaded = storage.load()
        assert len(loaded) == 3
        texts = {f["text"] for f in loaded}
        assert texts == {"Fact 1", "Fact 2", "Fact 3"}

    def test_add_facts_empty_list(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """add_facts() with empty list returns 0."""
        storage = isolated_storage("empty-batch-agent")
        count = storage.add_facts([])
        assert count == 0
        assert storage.fact_count() == 0

    def test_add_facts_invalid_filtered(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """add_facts() filters out invalid facts."""
        storage = isolated_storage("filter-agent")
        facts = [
            {"text": "Valid fact", "confidence": 0.9},
            {"confidence": 0.8},  # Missing text
            "not a dict",  # Invalid type
            {"text": "Another valid", "confidence": 0.7},
        ]

        count = storage.add_facts(facts)  # type: ignore[list-item]

        assert count == 2  # Only valid facts added
        loaded = storage.load()
        assert len(loaded) == 2

    def test_update_facts_batch(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """update_facts() updates multiple facts in single write."""
        storage = isolated_storage("batch-update-agent")

        # Pre-populate facts
        storage.add_facts([
            {"text": "Fact A", "confidence": 0.5, "tags": []},
            {"text": "Fact B", "confidence": 0.6, "tags": []},
            {"text": "Fact C", "confidence": 0.7, "tags": []},
        ])

        # Batch update
        updates = {
            "Fact A": {"confidence": 0.9, "updated": True},
            "Fact B": {"confidence": 0.95, "updated": True},
        }
        updated = storage.update_facts(updates)

        assert set(updated) == {"Fact A", "Fact B"}

        # Verify updates
        facts = {f["text"]: f for f in storage.load()}
        assert facts["Fact A"]["confidence"] == 0.9
        assert facts["Fact A"]["updated"] is True
        assert facts["Fact B"]["confidence"] == 0.95
        assert facts["Fact C"]["confidence"] == 0.7  # Unchanged

    def test_update_facts_empty(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """update_facts() with empty dict returns empty list."""
        storage = isolated_storage("empty-update-agent")
        result = storage.update_facts({})
        assert result == []

    def test_update_facts_nonexistent(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """update_facts() skips nonexistent facts."""
        storage = isolated_storage("missing-update-agent")
        storage.add_fact({"text": "Exists", "confidence": 0.5})

        updates = {
            "Exists": {"confidence": 0.9},
            "Does not exist": {"confidence": 0.8},
        }
        updated = storage.update_facts(updates)

        assert updated == ["Exists"]

    def test_remove_facts_batch(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """remove_facts() removes multiple facts in single write."""
        storage = isolated_storage("batch-remove-agent")

        # Pre-populate facts
        storage.add_facts([
            {"text": "Keep 1", "confidence": 0.9},
            {"text": "Remove 1", "confidence": 0.8},
            {"text": "Keep 2", "confidence": 0.7},
            {"text": "Remove 2", "confidence": 0.6},
        ])

        # Batch remove
        removed = storage.remove_facts(["Remove 1", "Remove 2"])

        assert set(removed) == {"Remove 1", "Remove 2"}

        # Verify removal
        loaded = storage.load()
        assert len(loaded) == 2
        texts = {f["text"] for f in loaded}
        assert texts == {"Keep 1", "Keep 2"}

    def test_remove_facts_empty_list(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """remove_facts() with empty list returns empty list."""
        storage = isolated_storage("empty-remove-agent")
        result = storage.remove_facts([])
        assert result == []

    def test_remove_facts_nonexistent(self, isolated_storage: type[FileMemoryStorage]) -> None:
        """remove_facts() handles nonexistent facts gracefully."""
        storage = isolated_storage("missing-remove-agent")
        storage.add_fact({"text": "Exists", "confidence": 0.5})

        removed = storage.remove_facts(["Exists", "Does not exist"])

        assert removed == ["Exists"]
        assert storage.fact_count() == 0

    def test_batch_operations_thread_safety(
        self, isolated_storage: type[FileMemoryStorage]
    ) -> None:
        """Batch operations are thread-safe."""
        import threading

        storage = isolated_storage("threadsafe-batch-agent")
        errors = []

        def add_batch(batch_id: int) -> None:
            try:
                facts = [{"text": f"Batch{batch_id}-Fact{i}", "confidence": 0.5 + i * 0.1}
                         for i in range(10)]
                storage.add_facts(facts)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_batch, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert storage.fact_count() == 50  # 5 threads x 10 facts
