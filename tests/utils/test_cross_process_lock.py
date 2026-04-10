"""Tests for cross-process file locking in file_mutex.py."""

import asyncio
import os
import tempfile

import pytest

from code_puppy.utils.file_mutex import (
    cross_process_file_lock,
    cross_process_file_lock_sync,
)


@pytest.fixture
def lock_target():
    """Create a temporary file to use as lock target."""
    with tempfile.NamedTemporaryFile(delete=False) as f:
        yield f.name
    # Clean up file and any leftover lock dirs
    try:
        os.unlink(f.name)
    except OSError:
        pass
    lock_dir = f"{f.name}.lock"
    if os.path.isdir(lock_dir):
        import shutil
        shutil.rmtree(lock_dir, ignore_errors=True)


class TestCrossProcessFileLockSync:
    def test_basic_acquire_release(self, lock_target):
        with cross_process_file_lock_sync(lock_target):
            # Lock is held — lock dir should exist
            assert os.path.isdir(f"{lock_target}.lock")
        # Lock released — lock dir should be gone
        assert not os.path.isdir(f"{lock_target}.lock")

    def test_lock_info_contains_pid(self, lock_target):
        import json

        with cross_process_file_lock_sync(lock_target):
            info_path = os.path.join(f"{lock_target}.lock", "info")
            assert os.path.exists(info_path)
            with open(info_path) as f:
                info = json.load(f)
            assert info["pid"] == os.getpid()
            assert "timestamp" in info

    def test_released_on_exception(self, lock_target):
        try:
            with cross_process_file_lock_sync(lock_target):
                raise ValueError("boom")
        except ValueError:
            pass
        assert not os.path.isdir(f"{lock_target}.lock")

    def test_stale_lock_reclaimed(self, lock_target):
        """A lock from a dead process should be reclaimed."""
        import json
        import time

        # Create a fake stale lock
        lock_dir = f"{lock_target}.lock"
        os.makedirs(lock_dir)
        info = {"pid": 999999999, "timestamp": time.time() - 100}  # Dead PID, old timestamp
        with open(os.path.join(lock_dir, "info"), "w") as f:
            json.dump(info, f)

        # Should reclaim the stale lock
        with cross_process_file_lock_sync(lock_target, stale_ms=1000):
            assert os.path.isdir(lock_dir)

    def test_concurrent_exclusion(self, lock_target):
        """Two threads should not hold the lock simultaneously."""
        import threading

        held_at_same_time = []
        lock_state = {"held": False}
        lock = threading.Lock()

        def _worker():
            with cross_process_file_lock_sync(lock_target, retry_delay=0.01):
                with lock:
                    if lock_state["held"]:
                        held_at_same_time.append(True)
                    lock_state["held"] = True
                import time
                time.sleep(0.05)
                with lock:
                    lock_state["held"] = False

        threads = [threading.Thread(target=_worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not held_at_same_time


class TestCrossProcessFileLockAsync:
    def test_basic_acquire_release(self, lock_target):
        async def _run():
            async with cross_process_file_lock(lock_target):
                assert os.path.isdir(f"{lock_target}.lock")
            assert not os.path.isdir(f"{lock_target}.lock")

        asyncio.run(_run())

    def test_released_on_exception(self, lock_target):
        async def _run():
            try:
                async with cross_process_file_lock(lock_target):
                    raise ValueError("boom")
            except ValueError:
                pass
            assert not os.path.isdir(f"{lock_target}.lock")

        asyncio.run(_run())

    def test_timeout_raises(self, lock_target):
        """Should raise TimeoutError if lock can't be acquired."""
        # Pre-create a non-stale lock
        import json
        import time

        lock_dir = f"{lock_target}.lock"
        os.makedirs(lock_dir)
        info = {"pid": os.getpid(), "timestamp": time.time()}
        with open(os.path.join(lock_dir, "info"), "w") as f:
            json.dump(info, f)

        async def _run():
            with pytest.raises(TimeoutError):
                async with cross_process_file_lock(
                    lock_target, retries=3, retry_delay=0.01, stale_ms=60000
                ):
                    pass

        try:
            asyncio.run(_run())
        finally:
            import shutil
            shutil.rmtree(lock_dir, ignore_errors=True)
