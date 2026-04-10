"""Tests for checkpoint utility (ADOPT from Agentless skip_existing pattern)."""

import json
import threading

import pytest

from code_puppy.utils.checkpoint import CheckpointStore


class TestCheckpointStore:
    """Test JSONL-based checkpoint store."""

    def test_empty_store(self, tmp_path):
        """New store with no file → empty."""
        store = CheckpointStore(tmp_path / "ckpt.jsonl")
        assert store.count == 0
        assert not store.is_done("task-1")

    def test_save_and_check(self, tmp_path):
        """Save an item → is_done returns True."""
        store = CheckpointStore(tmp_path / "ckpt.jsonl")
        store.save("task-1", {"status": "ok"})
        assert store.is_done("task-1")
        assert not store.is_done("task-2")
        assert store.count == 1

    def test_save_with_result(self, tmp_path):
        """Saved result is retrievable."""
        store = CheckpointStore(tmp_path / "ckpt.jsonl")
        store.save("task-1", {"output": 42})
        assert store.get_result("task-1") == {"output": 42}

    def test_persistence_across_instances(self, tmp_path):
        """Close and reopen → items persisted."""
        path = tmp_path / "ckpt.jsonl"

        # First instance: save items
        store1 = CheckpointStore(path)
        store1.save("task-1", "result-1")
        store1.save("task-2", "result-2")

        # Second instance: should see saved items
        store2 = CheckpointStore(path)
        assert store2.is_done("task-1")
        assert store2.is_done("task-2")
        assert store2.get_result("task-1") == "result-1"
        assert store2.count == 2

    def test_resume_skips_existing(self, tmp_path):
        """Simulate resume-after-crash pattern."""
        path = tmp_path / "ckpt.jsonl"
        work_items = ["a", "b", "c", "d", "e"]

        # First run: process a, b, c then "crash"
        store = CheckpointStore(path)
        for item in work_items[:3]:
            store.save(item, f"done-{item}")

        # Second run: resume from where we left off
        store = CheckpointStore(path)
        processed = []
        for item in work_items:
            if store.is_done(item):
                continue
            processed.append(item)
            store.save(item, f"done-{item}")

        assert processed == ["d", "e"]
        assert store.count == 5

    def test_malformed_lines_skipped(self, tmp_path):
        """Malformed JSONL lines are silently skipped."""
        path = tmp_path / "ckpt.jsonl"
        path.write_text(
            '{"_checkpoint_id": "good", "result": 1}\n'
            'not valid json\n'
            '{"missing_id_field": true}\n'
            '{"_checkpoint_id": "also-good", "result": 2}\n'
        )

        store = CheckpointStore(path)
        assert store.is_done("good")
        assert store.is_done("also-good")
        assert store.count == 2

    def test_thread_safety(self, tmp_path):
        """Concurrent saves from multiple threads are safe."""
        store = CheckpointStore(tmp_path / "ckpt.jsonl")
        errors = []

        def save_batch(start, count):
            try:
                for i in range(start, start + count):
                    store.save(f"item-{i}", {"value": i})
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=save_batch, args=(i * 100, 50))
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert store.count == 200

    def test_done_ids_returns_frozenset(self, tmp_path):
        """done_ids returns immutable frozenset."""
        store = CheckpointStore(tmp_path / "ckpt.jsonl")
        store.save("a")
        store.save("b")
        ids = store.done_ids
        assert isinstance(ids, frozenset)
        assert ids == frozenset({"a", "b"})

    def test_iter_results(self, tmp_path):
        """iter_results yields sorted (id, result) pairs."""
        store = CheckpointStore(tmp_path / "ckpt.jsonl")
        store.save("c", 3)
        store.save("a", 1)
        store.save("b", 2)

        pairs = list(store.iter_results())
        assert pairs == [("a", 1), ("b", 2), ("c", 3)]

    def test_clear(self, tmp_path):
        """clear() removes all checkpoints."""
        path = tmp_path / "ckpt.jsonl"
        store = CheckpointStore(path)
        store.save("task-1", "result")
        assert store.count == 1

        store.clear()
        assert store.count == 0
        assert not store.is_done("task-1")
        assert path.read_text() == ""

    def test_nonexistent_result_returns_none(self, tmp_path):
        """get_result for unknown ID returns None."""
        store = CheckpointStore(tmp_path / "ckpt.jsonl")
        assert store.get_result("nonexistent") is None

    def test_numeric_ids_converted_to_string(self, tmp_path):
        """Numeric IDs are converted to strings."""
        store = CheckpointStore(tmp_path / "ckpt.jsonl")
        store.save(42, "result")
        assert store.is_done("42")
        assert store.is_done(42)

    def test_creates_parent_dirs(self, tmp_path):
        """Parent directories are created if they don't exist."""
        path = tmp_path / "deep" / "nested" / "ckpt.jsonl"
        store = CheckpointStore(path)
        store.save("task-1", "ok")
        assert path.exists()
        assert store.is_done("task-1")

    def test_save_none_result(self, tmp_path):
        """Save with None result works correctly."""
        store = CheckpointStore(tmp_path / "ckpt.jsonl")
        store.save("task-1")
        assert store.is_done("task-1")
        assert store.get_result("task-1") is None
