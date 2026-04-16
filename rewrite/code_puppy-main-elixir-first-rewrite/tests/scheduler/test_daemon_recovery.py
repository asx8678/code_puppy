"""Tests for scheduler daemon crash recovery functionality.

Tests the self-healing reconciliation that marks orphaned 'running' tasks
as 'failed' on daemon startup. Ported from Orion pattern.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from code_puppy.scheduler.config import ScheduledTask, load_tasks, save_tasks
from code_puppy.scheduler.daemon import _reconcile_incomplete_tasks


class TestReconcileIncompleteTasks:
    """Tests for the _reconcile_incomplete_tasks() crash recovery function."""

    @pytest.fixture
    def temp_schedules_file(self, tmp_path):
        """Create a temporary schedules file and patch SCHEDULES_FILE."""
        schedules_file = tmp_path / "scheduled_tasks.json"
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        with patch("code_puppy.scheduler.config.SCHEDULES_FILE", str(schedules_file)):
            with patch("code_puppy.scheduler.config.SCHEDULER_LOG_DIR", str(logs_dir)):
                yield schedules_file

    def test_running_task_marked_as_failed(self, temp_schedules_file, capsys):
        """Happy path: task in 'running' state gets marked as 'failed'."""
        # Arrange: Create a task stuck in 'running' state (orphaned by crash)
        orphaned_task = ScheduledTask(
            id="orphan-001",
            name="Orphaned Task",
            prompt="Test prompt",
            last_status="running",
            last_run=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        )
        save_tasks([orphaned_task])

        # Act: Run reconciliation
        reconciled = _reconcile_incomplete_tasks()

        # Assert: Task was reconciled
        assert reconciled == ["orphan-001"]

        # Verify task state was persisted correctly
        tasks = load_tasks()
        assert len(tasks) == 1
        assert tasks[0].last_status == "failed"
        assert tasks[0].last_exit_code == -1
        assert tasks[0].name == "Orphaned Task"  # Other fields preserved

        # Verify console output
        captured = capsys.readouterr()
        assert "Reconciled 1 orphaned task(s)" in captured.out
        assert "orphan-001" in captured.out

    def test_multiple_orphaned_tasks_reconciled(self, temp_schedules_file, capsys):
        """Multiple orphans: 2+ running tasks all get reconciled."""
        # Arrange: Multiple orphaned tasks
        tasks = [
            ScheduledTask(
                id="orphan-001",
                name="Task 1",
                prompt="Prompt 1",
                last_status="running",
            ),
            ScheduledTask(
                id="orphan-002",
                name="Task 2",
                prompt="Prompt 2",
                last_status="running",
            ),
            ScheduledTask(
                id="normal-003",
                name="Task 3",
                prompt="Prompt 3",
                last_status="success",
            ),
        ]
        save_tasks(tasks)

        # Act
        reconciled = _reconcile_incomplete_tasks()

        # Assert
        assert sorted(reconciled) == ["orphan-001", "orphan-002"]

        captured = capsys.readouterr()
        assert "Reconciled 2 orphaned task(s)" in captured.out

        # Verify states
        from code_puppy.scheduler.config import load_tasks

        loaded = load_tasks()
        by_id = {t.id: t for t in loaded}
        assert by_id["orphan-001"].last_status == "failed"
        assert by_id["orphan-002"].last_status == "failed"
        assert by_id["normal-003"].last_status == "success"  # Unchanged

    def test_clean_state_no_orphans(self, temp_schedules_file, capsys):
        """Clean state: no running tasks → function is no-op, returns empty list."""
        # Arrange: Tasks in non-running states
        tasks = [
            ScheduledTask(
                id="success-001",
                name="Completed",
                prompt="Done",
                last_status="success",
            ),
            ScheduledTask(
                id="failed-002",
                name="Failed",
                prompt="Error",
                last_status="failed",
                last_exit_code=1,
            ),
            ScheduledTask(
                id="new-003",
                name="Never Run",
                prompt="Fresh",
                last_status=None,
            ),
        ]
        save_tasks(tasks)

        # Act
        reconciled = _reconcile_incomplete_tasks()

        # Assert
        assert reconciled == []

        captured = capsys.readouterr()
        assert "Reconciled" not in captured.out  # No output when nothing to do

        # Verify all tasks unchanged
        by_id = {t.id: t for t in load_tasks()}
        assert by_id["success-001"].last_status == "success"
        assert by_id["failed-002"].last_status == "failed"
        assert by_id["new-003"].last_status is None

    def test_idempotency_second_call_reconciles_nothing(
        self, temp_schedules_file, capsys
    ):
        """Idempotency: call reconciliation twice → second call reconciles nothing."""
        # Arrange: One orphaned task
        orphaned = ScheduledTask(
            id="orphan-001",
            name="Orphan",
            prompt="Test",
            last_status="running",
        )
        save_tasks([orphaned])

        # Act: First reconciliation
        first = _reconcile_incomplete_tasks()
        assert first == ["orphan-001"]

        # Act: Second reconciliation (simulating restart without crash)
        second = _reconcile_incomplete_tasks()

        # Assert: Second call finds nothing to reconcile
        assert second == []

        # Task is still failed from first run
        assert load_tasks()[0].last_status == "failed"

    def test_completed_tasks_untouched(self, temp_schedules_file):
        """Completed tasks (success/failed) are NOT modified."""
        # Arrange: Mix of statuses
        tasks = [
            ScheduledTask(
                id="success-001",
                name="Success",
                prompt="Done",
                last_status="success",
                last_run=datetime.now(timezone.utc).isoformat(),
            ),
            ScheduledTask(
                id="failed-002",
                name="Failed",
                prompt="Error",
                last_status="failed",
                last_exit_code=42,
                last_run=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            ),
            ScheduledTask(
                id="running-003",
                name="Running",
                prompt="Orphan",
                last_status="running",
            ),
        ]
        # Preserve original timestamps for verification
        original_success_time = tasks[0].last_run
        original_failed_time = tasks[1].last_run
        original_failed_code = tasks[1].last_exit_code

        save_tasks(tasks)

        # Act
        _reconcile_incomplete_tasks()

        # Assert
        by_id = {t.id: t for t in load_tasks()}

        # Completed tasks untouched
        assert by_id["success-001"].last_status == "success"
        assert by_id["success-001"].last_run == original_success_time

        assert by_id["failed-002"].last_status == "failed"
        assert by_id["failed-002"].last_exit_code == original_failed_code
        assert by_id["failed-002"].last_run == original_failed_time

        # Only running task was updated
        assert by_id["running-003"].last_status == "failed"
        assert by_id["running-003"].last_exit_code == -1

    def test_timestamp_updated_to_now(self, temp_schedules_file):
        """Verify last_run timestamp is bumped to now (UTC) on reconciliation."""
        before = datetime.now(timezone.utc)

        old_time = (before - timedelta(hours=2)).isoformat()
        orphaned = ScheduledTask(
            id="orphan-001",
            name="Old Task",
            prompt="Test",
            last_status="running",
            last_run=old_time,
        )
        save_tasks([orphaned])

        # Act
        _reconcile_incomplete_tasks()

        # Assert
        after = datetime.now(timezone.utc)

        # Parse the new timestamp
        new_time = datetime.fromisoformat(load_tasks()[0].last_run)
        assert before <= new_time <= after

    def test_empty_task_list(self, temp_schedules_file):
        """No tasks at all → returns empty list gracefully."""
        reconciled = _reconcile_incomplete_tasks()
        assert reconciled == []

    def test_load_failure_graceful(self, temp_schedules_file):
        """If load_tasks() fails, return empty list but don't crash."""
        with patch(
            "code_puppy.scheduler.daemon.load_tasks",
            side_effect=IOError("Disk error"),
        ):
            reconciled = _reconcile_incomplete_tasks()
            assert reconciled == []

    def test_save_failure_logs_but_continues(self, temp_schedules_file, capsys):
        """If save_tasks() fails, log warning but still return reconciled IDs."""
        orphaned = ScheduledTask(
            id="orphan-001",
            name="Orphan",
            prompt="Test",
            last_status="running",
        )
        save_tasks([orphaned])

        with patch(
            "code_puppy.scheduler.daemon.save_tasks",
            side_effect=IOError("Write error"),
        ):
            reconciled = _reconcile_incomplete_tasks()
            # Still reports what it found
            assert reconciled == ["orphan-001"]

        captured = capsys.readouterr()
        assert "Warning: Failed to persist reconciled tasks" in captured.out
        assert "Write error" in captured.out

    def test_error_message_not_stored_in_task(self, temp_schedules_file):
        """Verify we don't add an error message field - task schema doesn't have it."""
        # Note: code_puppy's ScheduledTask doesn't have an 'error' field like Orion's Run
        # We just mark status as failed and set exit_code to -1
        orphaned = ScheduledTask(
            id="orphan-001",
            name="Orphan",
            prompt="Test",
            last_status="running",
        )
        save_tasks([orphaned])

        _reconcile_incomplete_tasks()

        task = load_tasks()[0]
        # Schema has no 'error' field - we verify by checking the dataclass fields
        assert hasattr(task, "last_status")
        assert hasattr(task, "last_exit_code")
        assert task.last_status == "failed"
        assert task.last_exit_code == -1
        # No error attribute on the dataclass (this would fail if we tried to set one)
        assert "error" not in task.__dataclass_fields__
