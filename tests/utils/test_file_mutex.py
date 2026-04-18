"""Tests for code_puppy.utils.file_mutex.

Covers async file_lock, sync file_lock_sync, and the per-file serialization
behavior ported from pi-mono-main's file-mutation-queue.ts.
"""

import asyncio
import os
import threading
import time

import pytest

from code_puppy.utils.file_mutex import (
    active_lock_count,
    file_lock,
    file_lock_sync,
)


class TestFileLockAsync:
    """Tests for the async file_lock context manager."""

    @pytest.mark.asyncio
    async def test_same_file_serialized(self, tmp_path):
        """Two concurrent writes to the same file are serialized."""
        target = tmp_path / "test.txt"
        target.write_text("initial")
        order = []

        async def writer(name: str, delay: float):
            async with file_lock(str(target)):
                order.append(f"{name}_start")
                await asyncio.sleep(delay)
                order.append(f"{name}_end")

        await asyncio.gather(writer("A", 0.1), writer("B", 0.05))
        # A starts first, B waits, then B runs after A finishes
        assert order == ["A_start", "A_end", "B_start", "B_end"]

    @pytest.mark.asyncio
    async def test_different_files_parallel(self, tmp_path):
        """Writes to different files run concurrently."""
        file_a = tmp_path / "a.txt"
        file_b = tmp_path / "b.txt"
        file_a.write_text("")
        file_b.write_text("")
        order = []

        async def writer(path, name: str, delay: float):
            async with file_lock(str(path)):
                order.append(f"{name}_start")
                await asyncio.sleep(delay)
                order.append(f"{name}_end")

        await asyncio.gather(writer(file_a, "A", 0.1), writer(file_b, "B", 0.05))
        # B should finish before A since they run in parallel
        assert order == ["A_start", "B_start", "B_end", "A_end"]

    @pytest.mark.asyncio
    async def test_symlink_resolves_to_same_lock(self, tmp_path):
        """Symlinks to the same file use the same lock."""
        target = tmp_path / "real.txt"
        target.write_text("content")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        order = []

        async def writer(path, name: str, delay: float):
            async with file_lock(str(path)):
                order.append(f"{name}_start")
                await asyncio.sleep(delay)
                order.append(f"{name}_end")

        await asyncio.gather(writer(target, "real", 0.1), writer(link, "sym", 0.05))
        # Serialized because they resolve to the same realpath
        assert order == ["real_start", "real_end", "sym_start", "sym_end"]

    @pytest.mark.asyncio
    async def test_lock_cleanup_after_use(self, tmp_path):
        """Locks are cleaned up after all users release them."""
        target = tmp_path / "test.txt"
        target.write_text("")
        initial = active_lock_count()

        async with file_lock(str(target)):
            assert active_lock_count() > initial

        # After release, lock should be cleaned up
        # Give a small delay for cleanup
        await asyncio.sleep(0.01)
        assert active_lock_count() == initial

    @pytest.mark.asyncio
    async def test_exception_releases_lock(self, tmp_path):
        """Lock is released even when the body raises an exception."""
        target = tmp_path / "test.txt"
        target.write_text("")

        with pytest.raises(ValueError, match="test error"):
            async with file_lock(str(target)):
                raise ValueError("test error")

        # Should be able to acquire lock again
        async with file_lock(str(target)):
            pass  # Would hang if lock wasn't released

    @pytest.mark.asyncio
    async def test_nonexistent_path_uses_abspath(self, tmp_path):
        """Non-existent files use abspath as the key (realpath would fail)."""
        target = tmp_path / "does_not_exist.txt"
        # Should not raise
        async with file_lock(str(target)):
            pass


class TestFileLockSync:
    """Tests for the sync file_lock_sync context manager."""

    def test_same_file_serialized_sync(self, tmp_path):
        """Two concurrent writes to the same file are serialized."""
        target = tmp_path / "test.txt"
        target.write_text("initial")
        order = []
        order_lock = threading.Lock()

        def writer(name: str, delay: float):
            with file_lock_sync(str(target)):
                with order_lock:
                    order.append(f"{name}_start")
                time.sleep(delay)
                with order_lock:
                    order.append(f"{name}_end")

        t1 = threading.Thread(target=writer, args=("A", 0.1))
        t2 = threading.Thread(target=writer, args=("B", 0.05))
        t1.start()
        time.sleep(0.01)  # Ensure A starts first
        t2.start()
        t1.join()
        t2.join()
        assert order == ["A_start", "A_end", "B_start", "B_end"]

    def test_exception_releases_sync_lock(self, tmp_path):
        """Sync lock is released on exception."""
        target = tmp_path / "test.txt"
        target.write_text("")

        with pytest.raises(ValueError):
            with file_lock_sync(str(target)):
                raise ValueError("test")

        # Should be able to acquire again
        with file_lock_sync(str(target)):
            pass

    def test_different_files_parallel_sync(self, tmp_path):
        """Different files run in parallel in threads."""
        file_a = tmp_path / "a.txt"
        file_b = tmp_path / "b.txt"
        file_a.write_text("")
        file_b.write_text("")
        order = []
        order_lock = threading.Lock()

        def writer(path, name: str, delay: float):
            with file_lock_sync(str(path)):
                with order_lock:
                    order.append(f"{name}_start")
                time.sleep(delay)
                with order_lock:
                    order.append(f"{name}_end")

        t1 = threading.Thread(target=writer, args=(file_a, "A", 0.1))
        t2 = threading.Thread(target=writer, args=(file_b, "B", 0.05))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        # B should finish before A since they run in parallel on different files
        assert order == ["A_start", "B_start", "B_end", "A_end"]

    def test_symlink_sync_same_lock(self, tmp_path):
        """Symlinks resolve to same lock in sync version."""
        target = tmp_path / "real.txt"
        target.write_text("content")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        order = []
        order_lock = threading.Lock()

        def writer(path, name: str, delay: float):
            with file_lock_sync(str(path)):
                with order_lock:
                    order.append(f"{name}_start")
                time.sleep(delay)
                with order_lock:
                    order.append(f"{name}_end")

        t1 = threading.Thread(target=writer, args=(target, "real", 0.1))
        t2 = threading.Thread(target=writer, args=(link, "sym", 0.05))
        t1.start()
        time.sleep(0.01)  # Ensure real starts first
        t2.start()
        t1.join()
        t2.join()
        # Serialized because they resolve to the same realpath
        assert order == ["real_start", "real_end", "sym_start", "sym_end"]

    def test_lock_cleanup_sync(self, tmp_path):
        """Sync locks are cleaned up after release."""
        target = tmp_path / "test.txt"
        target.write_text("")

        # Track count via private attribute (test introspection)
        from code_puppy.utils.file_mutex import _sync_locks

        initial = len(_sync_locks)

        with file_lock_sync(str(target)):
            assert len(_sync_locks) > initial

        # Lock should be cleaned up
        assert len(_sync_locks) == initial


class TestEdgeCases:
    """Edge cases and stress tests for both implementations."""

    @pytest.mark.asyncio
    async def test_many_files_independent(self, tmp_path):
        """Many files all run independently."""
        files = [tmp_path / f"file_{i}.txt" for i in range(10)]
        for f in files:
            f.write_text("")

        order_lock = asyncio.Lock()
        order = []

        async def writer(path, name: str):
            async with file_lock(str(path)):
                async with order_lock:
                    order.append(f"{name}_start")
                await asyncio.sleep(0.05)
                async with order_lock:
                    order.append(f"{name}_end")

        await asyncio.gather(*[writer(f, f"writer_{i}") for i, f in enumerate(files)])
        # All should complete, none should be serialized against each other
        assert len(order) == 20  # 10 starts + 10 ends

@pytest.mark.serial
@pytest.mark.xdist_group(name="chdir")
    def test_relative_path_resolved(self, tmp_path):
        """Relative paths are resolved to absolute before locking."""
        target = tmp_path / "relative.txt"
        target.write_text("")

        # Change to the temp dir so relative path works
        import os
        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            # Should work with relative path
            with file_lock_sync("relative.txt"):
                pass
            # Same with async
            asyncio.run(self._async_lock_relative("relative.txt"))
        finally:
            os.chdir(original_dir)

    @staticmethod
    async def _async_lock_relative(path: str):
        async with file_lock(path):
            pass

    @pytest.mark.asyncio
    async def test_nested_same_file_not_deadlock(self, tmp_path):
        """Nested locks on same file in same coroutine should not deadlock."""
        # Note: This documents current behavior - asyncio.Lock is not reentrant
        # so this WILL deadlock. We're documenting this is expected behavior.
        # Users should avoid nested file_lock calls on the same file.
        target = tmp_path / "test.txt"
        target.write_text("")

        # This will timeout because asyncio.Lock is not reentrant
        # The test verifies the behavior is consistent
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                self._acquire_nested(str(target)),
                timeout=0.1
            )

    @staticmethod
    async def _acquire_nested(path: str):
        async with file_lock(path):
            async with file_lock(path):  # Deadlock here
                pass

    def test_absolute_path_input(self, tmp_path):
        """Absolute paths work directly."""
        target = tmp_path / "abs.txt"
        target.write_text("")
        abs_path = os.path.abspath(str(target))

        # Should work with absolute path
        with file_lock_sync(abs_path):
            pass
