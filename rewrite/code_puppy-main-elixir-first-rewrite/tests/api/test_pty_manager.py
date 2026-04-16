"""Tests for PTYSession.is_alive() and singleton thread-safety in pty_manager.py."""

import threading
from unittest.mock import MagicMock, patch

import code_puppy.api.pty_manager as pty_mod
from code_puppy.api.pty_manager import PTYManager, PTYSession, get_pty_manager


class TestPTYSessionIsAlive:
    """Tests for the PTYSession.is_alive() method."""

    @patch("code_puppy.api.pty_manager.IS_WINDOWS", False)
    @patch("os.waitpid", return_value=(0, 0))
    def test_is_alive_returns_true_when_process_running(
        self, mock_waitpid: MagicMock
    ) -> None:
        """is_alive() returns True when os.waitpid reports process still running."""
        session = PTYSession(session_id="test-1", pid=12345)
        assert session.is_alive() is True
        mock_waitpid.assert_called_once_with(12345, 1)  # os.WNOHANG == 1

    @patch("code_puppy.api.pty_manager.IS_WINDOWS", False)
    @patch("os.waitpid", return_value=(12345, 9))
    def test_is_alive_returns_false_when_process_exited(
        self, mock_waitpid: MagicMock
    ) -> None:
        """is_alive() returns False when os.waitpid reports process exited."""
        session = PTYSession(session_id="test-2", pid=12345)
        assert session.is_alive() is False
        mock_waitpid.assert_called_once_with(12345, 1)

    @patch("code_puppy.api.pty_manager.IS_WINDOWS", False)
    @patch("os.waitpid", side_effect=ChildProcessError("No child processes"))
    def test_is_alive_returns_false_on_child_process_error(
        self, mock_waitpid: MagicMock
    ) -> None:
        """is_alive() returns False when the child process was already reaped."""
        session = PTYSession(session_id="test-3", pid=12345)
        assert session.is_alive() is False
        mock_waitpid.assert_called_once_with(12345, 1)

    @patch("code_puppy.api.pty_manager.IS_WINDOWS", False)
    def test_is_alive_returns_false_when_pid_is_none(self) -> None:
        """is_alive() returns False when the session has no pid."""
        session = PTYSession(session_id="test-4", pid=None)
        assert session.is_alive() is False

    @patch("code_puppy.api.pty_manager.IS_WINDOWS", True)
    def test_is_alive_windows_with_winpty(self) -> None:
        """is_alive() delegates to winpty_process.isalive() on Windows."""
        mock_winpty = MagicMock()
        mock_winpty.isalive.return_value = True

        session = PTYSession(session_id="test-5", winpty_process=mock_winpty)
        assert session.is_alive() is True
        mock_winpty.isalive.assert_called_once()

        # Also test when winpty reports not alive
        mock_winpty.isalive.return_value = False
        assert session.is_alive() is False

    @patch("code_puppy.api.pty_manager.IS_WINDOWS", True)
    def test_is_alive_windows_without_winpty_process(self) -> None:
        """is_alive() returns False on Windows when winpty_process is None."""
        session = PTYSession(session_id="test-6", winpty_process=None)
        assert session.is_alive() is False


class TestGetPTYManagerThreadSafety:
    """Regression test: get_pty_manager() must return the same singleton
    even when called concurrently from multiple threads.
    """

    def test_get_pty_manager_thread_safety(self) -> None:
        """All threads racing through get_pty_manager() get the same instance."""
        # Reset singleton so we start from a clean state
        pty_mod._pty_manager = None

        num_threads = 20
        barrier = threading.Barrier(num_threads)
        results: list[PTYManager] = [None] * num_threads  # type: ignore[assignment]
        init_count = 0
        init_lock = threading.Lock()

        original_init = PTYManager.__init__

        def _counting_init(self: PTYManager) -> None:
            nonlocal init_count
            with init_lock:
                init_count += 1
            original_init(self)

        with patch.object(PTYManager, "__init__", _counting_init):
            def worker(idx: int) -> None:
                barrier.wait(timeout=5)
                results[idx] = get_pty_manager()

            threads = [
                threading.Thread(target=worker, args=(i,)) for i in range(num_threads)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

        # Every thread must have received the exact same object
        assert all(r is results[0] for r in results), (
            "Not all threads got the same PTYManager instance"
        )

        # PTYManager.__init__ should have been called exactly once
        assert init_count == 1, (
            f"Expected exactly 1 PTYManager init, got {init_count}"
        )

        # Clean up so other tests aren't affected
        pty_mod._pty_manager = None
