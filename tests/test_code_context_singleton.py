"""Concurrency regression tests for _global_explorer singleton.

Ensures that get_explorer_instance() returns exactly one CodeExplorer
instance even when called from many threads simultaneously.

 Regression guard for code_puppy-68x.9.
"""

import threading
import time
from unittest.mock import patch

import pytest

from code_puppy.code_context import (
    CodeExplorer,
    get_explorer_instance,
    get_code_context,
    get_file_outline,
    explore_directory,
)
import code_puppy.code_context as cc_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_global_explorer():
    """Reset the module-level singleton between tests."""
    with cc_module._explorer_lock:
        cc_module._global_explorer = None
    yield
    with cc_module._explorer_lock:
        cc_module._global_explorer = None


# ---------------------------------------------------------------------------
# Singleton identity tests
# ---------------------------------------------------------------------------


class TestExplorerSingletonIdentity:
    """Verify that get_explorer_instance always returns the same object."""

    def test_same_instance_sequential(self):
        """Sequential calls must return the identical object."""
        a = get_explorer_instance()
        b = get_explorer_instance()
        assert a is b

    def test_same_instance_concurrent(self):
        """Many threads racing to get the instance must all get the same one."""
        results: list[CodeExplorer | None] = [None] * 50
        barrier = threading.Barrier(50)

        def worker(idx: int) -> None:
            barrier.wait()  # all threads start together
            results[idx] = get_explorer_instance()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Every entry must be the *same* CodeExplorer instance
        first = results[0]
        assert first is not None, "get_explorer_instance() returned None"
        for i, r in enumerate(results):
            assert r is first, f"Thread {i} got a different instance!"

    def test_exactly_one_instance_created_concurrent(self):
        """Verify the constructor is called exactly once under contention."""

        call_count = 0
        original_init = CodeExplorer.__init__

        def counting_init(self, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            # tiny sleep to widen the race window
            time.sleep(0.001)
            original_init(self, *args, **kwargs)

        with patch.object(CodeExplorer, "__init__", counting_init):
            results: list[CodeExplorer | None] = [None] * 20
            barrier = threading.Barrier(20)

            def worker(idx: int) -> None:
                barrier.wait()
                results[idx] = get_explorer_instance()

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert call_count == 1, (
            f"CodeExplorer.__init__ called {call_count} times, expected 1"
        )


# ---------------------------------------------------------------------------
# Module-level convenience function tests (they must go through singleton)
# ---------------------------------------------------------------------------


class TestModuleFunctionsUseSingleton:
    """Ensure module-level helpers delegate to the singleton."""

    def test_get_code_context_uses_singleton(self, tmp_path):
        """get_code_context(with_symbols=True) must use get_explorer_instance."""
        py_file = tmp_path / "sample.py"
        py_file.write_text("def foo(): pass\n")

        instance = get_explorer_instance()

        with patch.object(
            instance, "explore_file", wraps=instance.explore_file
        ) as spy:
            get_code_context(str(py_file), include_content=False, with_symbols=True)
            spy.assert_called_once()

    def test_get_file_outline_uses_singleton(self, tmp_path):
        """get_file_outline must delegate to singleton."""
        py_file = tmp_path / "sample.py"
        py_file.write_text("def bar(): pass\n")

        instance = get_explorer_instance()

        with patch.object(
            instance, "get_outline", wraps=instance.get_outline
        ) as spy:
            get_file_outline(str(py_file))
            spy.assert_called_once()

    def test_explore_directory_uses_singleton(self, tmp_path):
        """explore_directory must delegate to singleton."""
        (tmp_path / "a.py").write_text("x = 1\n")

        instance = get_explorer_instance()

        with patch.object(
            instance, "explore_directory", wraps=instance.explore_directory
        ) as spy:
            explore_directory(str(tmp_path))
            spy.assert_called_once()


# ---------------------------------------------------------------------------
# Lazy initialization test
# ---------------------------------------------------------------------------


class TestLazyInitialization:
    """The singleton must not be created until first access."""

    def test_not_created_at_import(self):
        """After reset, _global_explorer must be None until accessed."""
        assert cc_module._global_explorer is None

    def test_created_on_first_access(self):
        """First call creates the instance."""
        assert cc_module._global_explorer is None
        inst = get_explorer_instance()
        assert inst is not None
        assert cc_module._global_explorer is inst
