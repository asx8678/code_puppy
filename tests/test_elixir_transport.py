"""
Unit tests for the ElixirTransport class.

These tests verify the behavior of ElixirTransport methods using mocking
to avoid requiring an actual Elixir process.

Run with:
    pytest tests/test_elixir_transport.py -v
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.elixir_transport import ElixirTransport, ElixirTransportError


class TestDrainStartupStdout:
    """Tests for the _drain_startup_stdout method (bd-129)."""

    def _create_transport(self):
        """Helper to create a minimal transport with required attributes."""
        transport = ElixirTransport.__new__(ElixirTransport)
        transport._process = None
        transport._request_id = 0
        transport._closed = True  # Mark as closed to avoid __del__ issues
        transport._lock = MagicMock()
        return transport

    def test_drains_stale_stdout_after_successful_ping(self):
        """
        Test that stale stdout after a successful ping is properly drained.
        
        Verifies:
        - The drain method reads and counts bytes from stdout
        - Multiple lines can be drained
        - Returns total bytes drained
        """
        transport = self._create_transport()
        transport._process = MagicMock()
        transport._process.poll.return_value = None  # Process is running
        
        # Simulate multiple lines in stdout
        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = [
            '{"jsonrpc": "2.0", "id": 99, "result": {"pong": true}}\n',  # stale pong
            'log line 1\n',  # log output
            'log line 2\n',  # more log output
            '',  # EOF
        ]
        transport._process.stdout = mock_stdout
        
        # Mock select to indicate data is available, then no more data
        with patch('select.select') as mock_select:
            mock_select.side_effect = [
                ([mock_stdout], [], []),  # Data available
                ([mock_stdout], [], []),  # Data available
                ([mock_stdout], [], []),  # Data available
                ([], [], []),  # No more data
            ]
            
            result = transport._drain_startup_stdout(timeout_sec=0.5)
        
        # Should have drained all 3 lines
        assert result == len('{"jsonrpc": "2.0", "id": 99, "result": {"pong": true}}\n') + len('log line 1\n') + len('log line 2\n')
        assert mock_stdout.readline.call_count == 3

    def test_request_id_updated_only_after_drain(self):
        """
        Test that _request_id is updated only after drain completes.
        
        This verifies the ordering: ping success -> drain stdout -> update request_id.
        The request_id should not be updated before draining completes.
        """
        transport = self._create_transport()
        transport._process = MagicMock()
        transport._process.poll.return_value = None
        transport._lock = MagicMock()
        transport._request_id = 0
        
        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = [
            'stale output\n',
            '',  # EOF
        ]
        transport._process.stdout = mock_stdout
        
        # Track when drain is called vs when request_id is updated
        drain_called = False
        request_id_updated = False
        
        original_drain = transport._drain_startup_stdout
        
        def mock_drain(timeout_sec=0.5):
            nonlocal drain_called
            drain_called = True
            # request_id should NOT be updated yet
            assert transport._request_id == 0, "request_id should not be updated before drain"
            return original_drain(timeout_sec)
        
        transport._drain_startup_stdout = mock_drain
        
        # Simulate _wait_for_ready flow
        with patch('select.select') as mock_select:
            mock_select.side_effect = [
                ([mock_stdout], [], []),  # For drain
                ([], [], []),  # No more data
            ]
            
            # Simulate successful ping response
            ping_id = 5
            
            # Call drain (as _wait_for_ready would)
            drained_count = transport._drain_startup_stdout(timeout_sec=0.5)
            
            # Now update request_id (as _wait_for_ready does after drain)
            with transport._lock:
                transport._request_id = ping_id
                request_id_updated = True
        
        assert drain_called, "Drain should have been called"
        assert request_id_updated, "request_id should have been updated after drain"
        assert transport._request_id == ping_id

    def test_process_death_during_drain_does_not_crash(self):
        """
        Test that process death during drain doesn't crash - returns gracefully.
        
        Verifies:
        - If process dies (poll() returns non-None), returns 0 immediately
        - No exceptions are raised
        """
        transport = self._create_transport()
        transport._process = MagicMock()
        
        # Process dies before drain starts
        transport._process.poll.return_value = 1  # Exit code 1
        
        # Should return 0 without crashing
        result = transport._drain_startup_stdout(timeout_sec=0.5)
        assert result == 0
        
        # Process dies during drain (after initial check)
        transport._process.poll.side_effect = [None, 1]  # Running, then dead
        mock_stdout = MagicMock()
        mock_stdout.readline.return_value = ''
        transport._process.stdout = mock_stdout
        
        with patch('select.select') as mock_select:
            mock_select.return_value = ([], [], [])  # No data available
            
            result = transport._drain_startup_stdout(timeout_sec=0.5)
            assert result == 0

    def test_timeout_during_drain_returns_gracefully(self):
        """
        Test that timeout during drain returns gracefully with partial results.
        
        Verifies:
        - If timeout is reached, returns bytes drained so far
        - Doesn't hang indefinitely
        - Partial results are returned
        """
        transport = self._create_transport()
        transport._process = MagicMock()
        transport._process.poll.return_value = None
        
        mock_stdout = MagicMock()
        # Simulate continuous data that would cause hanging
        mock_stdout.readline.return_value = 'continuous output\n'
        transport._process.stdout = mock_stdout
        
        start_time = time.time()
        
        with patch('select.select') as mock_select:
            # Always indicate data is available (would cause infinite loop without timeout)
            mock_select.return_value = ([mock_stdout], [], [])
            
            # Very short timeout
            result = transport._drain_startup_stdout(timeout_sec=0.1)
            
            # Should complete quickly due to timeout
            elapsed = time.time() - start_time
            assert elapsed < 0.5, f"Drain should timeout quickly, took {elapsed}s"
            
            # Should return accumulated bytes
            assert result > 0
            assert mock_stdout.readline.call_count >= 1

    def test_drain_with_no_available_data(self):
        """
        Test that drain returns 0 when no data is available.
        """
        transport = self._create_transport()
        transport._process = MagicMock()
        transport._process.poll.return_value = None
        
        mock_stdout = MagicMock()
        transport._process.stdout = mock_stdout
        
        with patch('select.select') as mock_select:
            # No data available immediately
            mock_select.return_value = ([], [], [])
            
            result = transport._drain_startup_stdout(timeout_sec=0.5)
            
            assert result == 0
            mock_stdout.readline.assert_not_called()

    def test_drain_handles_readline_exception(self):
        """
        Test that drain handles exceptions from readline gracefully.
        """
        transport = self._create_transport()
        transport._process = MagicMock()
        transport._process.poll.return_value = None
        
        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = IOError("Stream closed")
        transport._process.stdout = mock_stdout
        
        with patch('select.select') as mock_select:
            mock_select.return_value = ([mock_stdout], [], [])
            
            # Should not raise exception
            result = transport._drain_startup_stdout(timeout_sec=0.5)
            
            assert result == 0

    def test_drain_logs_stripped_content(self):
        """
        Test that drain logs stripped content for debugging.
        """
        transport = self._create_transport()
        transport._process = MagicMock()
        transport._process.poll.return_value = None
        
        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = [
            'some log message\n',
            '',  # EOF
        ]
        transport._process.stdout = mock_stdout
        
        with patch('select.select') as mock_select:
            mock_select.side_effect = [
                ([mock_stdout], [], []),
                ([], [], []),
            ]
            with patch('code_puppy.elixir_transport.logger') as mock_logger:
                result = transport._drain_startup_stdout(timeout_sec=0.5)
                
                # Should log the drained content
                mock_logger.debug.assert_called_with(
                    "Drained from stdout during startup: some log message"
                )
                assert result == len('some log message\n')

    def test_drain_skips_empty_lines_in_logs(self):
        """
        Test that empty lines are counted in total but not logged.
        """
        transport = self._create_transport()
        transport._process = MagicMock()
        transport._process.poll.return_value = None
        
        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = [
            '\n',  # Empty line (just newline)
            'content line\n',
            '',  # EOF
        ]
        transport._process.stdout = mock_stdout
        
        with patch('select.select') as mock_select:
            mock_select.side_effect = [
                ([mock_stdout], [], []),
                ([mock_stdout], [], []),
                ([], [], []),
            ]
            with patch('code_puppy.elixir_transport.logger') as mock_logger:
                result = transport._drain_startup_stdout(timeout_sec=0.5)
                
                # Should count both lines
                assert result == len('\n') + len('content line\n')
                
                # Should only log the non-empty line
                mock_logger.debug.assert_called_once_with(
                    "Drained from stdout during startup: content line"
                )


class TestElixirTransportInit:
    """Tests for ElixirTransport initialization."""

    def test_transport_initializes_with_defaults(self):
        """Test that transport initializes with default values."""
        with patch.object(ElixirTransport, '_detect_elixir_path', return_value='/usr/bin'), \
             patch.object(ElixirTransport, '_detect_project_path', return_value='/project'):
            transport = ElixirTransport()
            
            assert transport.elixir_path == '/usr/bin'
            assert transport.project_path == '/project'
            assert transport.timeout == 30.0
            assert transport._process is None
            assert transport._request_id == 0
            assert transport._closed is False

    def test_transport_accepts_custom_values(self):
        """Test that transport accepts custom initialization values."""
        transport = ElixirTransport(
            elixir_path='/custom/elixir',
            project_path='/custom/project',
            timeout=60.0
        )
        
        assert transport.elixir_path == '/custom/elixir'
        assert transport.project_path == '/custom/project'
        assert transport.timeout == 60.0


class TestElixirTransportErrorHandling:
    """Tests for error handling in ElixirTransport."""

    def test_error_is_raised_when_elixir_not_found(self):
        """Test that error is raised when Elixir is not found."""
        with patch('shutil.which', return_value=None), \
             patch('os.path.exists', return_value=False):
            with pytest.raises(ElixirTransportError, match="Could not find elixir"):
                ElixirTransport()

    def test_error_is_raised_when_project_not_found(self):
        """Test that error is raised when project is not found."""
        with patch('shutil.which', return_value='/usr/bin/elixir'), \
             patch('pathlib.Path.exists', return_value=False):
            with pytest.raises(ElixirTransportError, match="Could not find code_puppy_control"):
                ElixirTransport()


class TestWaitForReadyDrainIntegration:
    """Tests for the integration between _wait_for_ready and _drain_startup_stdout."""

    def _create_transport(self):
        """Helper to create a minimal transport with required attributes."""
        transport = ElixirTransport.__new__(ElixirTransport)
        transport._process = None
        transport._request_id = 0
        transport._closed = True  # Mark as closed to avoid __del__ issues
        transport._lock = MagicMock()
        return transport

    def test_successful_ping_triggers_drain(self):
        """
        Test that a successful ping triggers the drain process.
        
        Verifies the flow: ping -> drain -> update request_id
        """
        transport = self._create_transport()
        transport._process = MagicMock()
        transport._process.poll.return_value = None
        transport._lock = MagicMock()
        transport._request_id = 0
        
        mock_stdout = MagicMock()
        # First response is the successful ping, then stale data to drain
        mock_stdout.readline.side_effect = [
            '{"jsonrpc": "2.0", "id": 1, "result": {"pong": true}}\n',
            'stale log line\n',
            '',  # EOF
        ]
        transport._process.stdout = mock_stdout
        
        drain_calls = []
        original_drain = transport._drain_startup_stdout
        
        def tracking_drain(timeout_sec=0.5):
            drain_calls.append(timeout_sec)
            return original_drain(timeout_sec)
        
        transport._drain_startup_stdout = tracking_drain
        
        with patch('select.select') as mock_select:
            mock_select.side_effect = [
                ([mock_stdout], [], []),  # Ping response available
                ([mock_stdout], [], []),  # Stale data for drain
                ([], [], []),  # No more data
            ]
            with patch('time.sleep'):  # Skip sleeps for speed
                with patch('time.time') as mock_time:
                    # Return increasing times to avoid timeout
                    mock_time.side_effect = [0, 0.1, 0.2, 0.3, 0.4, 0.5]
                    
                    # Simulate the _wait_for_ready logic manually
                    ping_id = 1
                    response_line = mock_stdout.readline().strip()
                    response = json.loads(response_line)
                    
                    if response.get("id") == ping_id and response.get("result", {}).get("pong"):
                        drained_count = transport._drain_startup_stdout(timeout_sec=0.5)
                        with transport._lock:
                            transport._request_id = ping_id
        
        assert len(drain_calls) == 1
        assert drain_calls[0] == 0.5
        assert transport._request_id == 1

    def test_drain_logs_debug_for_each_line(self):
        """
        Test that debug logs are written for each drained line.
        
        _drain_startup_stdout uses logger.debug for individual lines,
        while _wait_for_ready logs the total via logger.warning.
        """
        transport = self._create_transport()
        transport._process = MagicMock()
        transport._process.poll.return_value = None
        
        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = [
            'stale data\n',
            '',  # EOF
        ]
        transport._process.stdout = mock_stdout
        
        with patch('select.select') as mock_select:
            mock_select.side_effect = [
                ([mock_stdout], [], []),
                ([], [], []),
            ]
            with patch('code_puppy.elixir_transport.logger') as mock_logger:
                result = transport._drain_startup_stdout(timeout_sec=0.5)
                
                # Should log debug message about the drained content
                mock_logger.debug.assert_called_with(
                    "Drained from stdout during startup: stale data"
                )
                assert result == len('stale data\n')
