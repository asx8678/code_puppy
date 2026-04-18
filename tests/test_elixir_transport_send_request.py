"""Tests for the ElixirTransport._send_request method with non-JSON line skipping.

Tests the bd-128 functionality that handles:
- Non-JSON preamble lines before valid response
- Mismatched JSON-RPC response IDs
- Budget exhaustion (line count and time budget)
"""

import json
import threading
import time
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.elixir_transport import ElixirTransport, ElixirTransportError


class MockProcess:
    """Mock subprocess.Popen for testing."""

    def __init__(self, stdout_lines=None, poll_result=None):
        self.stdout_lines = stdout_lines or []
        self._poll_result = poll_result
        self.stdin = MagicMock()
        self.stdout = StringIO("\n".join(self.stdout_lines) + "\n")
        self._closed = False

    def poll(self):
        return self._poll_result


def _create_transport(request_id=0):
    """Create a minimally initialized transport for testing."""
    transport = ElixirTransport.__new__(ElixirTransport)
    transport._request_id = request_id
    transport._closed = False
    transport._lock = threading.Lock()
    return transport


class TestSendRequestNonJsonSkipping:
    """Tests for non-JSON line skipping in _send_request."""

    def test_non_json_preamble_lines_skipped(self):
        """Test that non-JSON lines before valid response are skipped."""
        transport = _create_transport(request_id=0)

        # Create mock process with some non-JSON lines before valid response
        valid_response = {"jsonrpc": "2.0", "id": 1, "result": {"pong": True}}
        stdout_lines = [
            "Some warning message",  # Non-JSON
            "Another log line",  # Non-JSON
            json.dumps(valid_response),  # Valid JSON response
        ]
        transport._process = MockProcess(stdout_lines=stdout_lines)

        result = transport._send_request("ping", {})

        assert result == {"pong": True}

    def test_multiple_non_json_lines_skipped(self):
        """Test that multiple non-JSON lines are all skipped."""
        transport = _create_transport(request_id=0)

        valid_response = {"jsonrpc": "2.0", "id": 1, "result": {"data": "test"}}
        stdout_lines = ["warning", "info", "log", "debug", json.dumps(valid_response)]
        transport._process = MockProcess(stdout_lines=stdout_lines)

        result = transport._send_request("test_method", {})

        assert result == {"data": "test"}

    def test_empty_lines_skipped(self):
        """Test that empty lines are skipped."""
        transport = _create_transport(request_id=0)

        valid_response = {"jsonrpc": "2.0", "id": 1, "result": {"data": "test"}}
        stdout_lines = ["", "   ", json.dumps(valid_response)]
        transport._process = MockProcess(stdout_lines=stdout_lines)

        result = transport._send_request("test_method", {})

        assert result == {"data": "test"}


class TestSendRequestMismatchedIds:
    """Tests for mismatched JSON-RPC response ID handling."""

    def test_mismatched_id_is_discarded(self):
        """Test that response with mismatched ID is discarded and we keep reading."""
        transport = _create_transport(request_id=1)

        # First response has wrong ID, second has correct
        wrong_id_response = {"jsonrpc": "2.0", "id": 99, "result": {"old": "data"}}
        correct_response = {"jsonrpc": "2.0", "id": 2, "result": {"correct": "data"}}
        stdout_lines = [json.dumps(wrong_id_response), json.dumps(correct_response)]
        transport._process = MockProcess(stdout_lines=stdout_lines)

        result = transport._send_request("test_method", {})

        assert result == {"correct": "data"}

    def test_multiple_mismatched_ids_discarded(self):
        """Test that multiple mismatched IDs are all discarded."""
        transport = _create_transport(request_id=0)

        responses = [
            {"jsonrpc": "2.0", "id": 999, "result": {"stale": 1}},
            {"jsonrpc": "2.0", "id": 998, "result": {"stale": 2}},
            {"jsonrpc": "2.0", "id": 997, "result": {"stale": 3}},
            {"jsonrpc": "2.0", "id": 1, "result": {"correct": True}},
        ]
        stdout_lines = [json.dumps(r) for r in responses]
        transport._process = MockProcess(stdout_lines=stdout_lines)

        result = transport._send_request("test_method", {})

        assert result == {"correct": True}


class TestSendRequestBudgetExhaustion:
    """Tests for budget exhaustion scenarios."""

    def test_line_budget_exhaustion_raises_error(self):
        """Test that 50 bad lines causes budget exhaustion error."""
        transport = _create_transport(request_id=0)

        # 51 non-JSON lines (exceeds max_non_json_reads of 50)
        stdout_lines = [f"bad line {i}" for i in range(51)]
        transport._process = MockProcess(stdout_lines=stdout_lines)

        with pytest.raises(ElixirTransportError) as exc_info:
            transport._send_request("test_method", {})

        assert "id=1" in str(exc_info.value)
        assert "50 attempts" in str(exc_info.value)

    def test_mixed_bad_lines_and_mismatched_ids_exhaust_budget(self):
        """Test that mix of non-JSON and mismatched IDs counts toward budget."""
        transport = _create_transport(request_id=0)

        # 25 non-JSON + 25 mismatched IDs = 50, then 51st is also bad
        stdout_lines = []
        for i in range(25):
            stdout_lines.append(f"non-json {i}")
        for i in range(26):
            stdout_lines.append(
                json.dumps({"jsonrpc": "2.0", "id": 900 + i, "result": {}})
            )
        transport._process = MockProcess(stdout_lines=stdout_lines)

        with pytest.raises(ElixirTransportError) as exc_info:
            transport._send_request("test_method", {})

        assert "50 attempts" in str(exc_info.value)


class TestSendRequestTimeBudget:
    """Tests for time budget (5 second timeout) in _send_request."""

    def test_time_budget_timeout_raises_error(self):
        """Test that time budget of 5 seconds raises timeout error."""
        transport = _create_transport(request_id=0)

        # Create a mock process that will have a slow stdout.readline
        transport._process = MagicMock()
        transport._process.poll.return_value = None

        # Mock stdin to accept writes
        transport._process.stdin = MagicMock()

        # Mock stdout.readline to simulate slow responses (beyond 5 second budget)
        # Each call advances time by 0.2s, so after 26 calls we've exceeded 5s
        call_count = 0

        def slow_readline():
            nonlocal call_count
            call_count += 1
            # Simulate time passing with each readline call
            # First few calls are fast, but eventually we exceed 5s
            if call_count > 26:
                return json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
            time.sleep(0.21)  # Each call takes 0.21s
            return "non-json line"

        transport._process.stdout.readline = slow_readline

        with pytest.raises(ElixirTransportError) as exc_info:
            transport._send_request("test_method", {})

        assert "Timed out" in str(exc_info.value)
        assert "5.0s" in str(exc_info.value)
        assert "id=1" in str(exc_info.value)

    def test_time_budget_resets_per_request(self):
        """Test that time budget is per-request, not global."""
        transport = _create_transport(request_id=0)

        # First request succeeds quickly
        transport._process = MagicMock()
        transport._process.poll.return_value = None
        transport._process.stdin = MagicMock()
        transport._process.stdout.readline.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"data": 1}}
        )

        result1 = transport._send_request("test_method", {})
        assert result1 == {"data": 1}

        # Second request also succeeds (time budget is reset for each request)
        transport._process.stdout.readline.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 2, "result": {"data": 2}}
        )
        result2 = transport._send_request("test_method", {})
        assert result2 == {"data": 2}


class TestSendRequestErrorResponses:
    """Tests for error response handling."""

    def test_error_response_raises_exception(self):
        """Test that JSON-RPC error response raises ElixirTransportError."""
        transport = _create_transport(request_id=0)

        error_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32000, "message": "Something went wrong"},
        }
        transport._process = MockProcess(stdout_lines=[json.dumps(error_response)])

        with pytest.raises(ElixirTransportError) as exc_info:
            transport._send_request("test_method", {})

        assert "Something went wrong" in str(exc_info.value)
        assert "-32000" in str(exc_info.value)

    def test_empty_response_raises_error(self):
        """Test that empty response (EOF) raises error."""
        transport = _create_transport(request_id=0)
        transport._process = MockProcess(stdout_lines=[""])  # Empty line simulates EOF

        with pytest.raises(ElixirTransportError) as exc_info:
            transport._send_request("test_method", {})

        assert "Empty response" in str(exc_info.value)


class TestSendRequestProcessDead:
    """Tests for when the process has died."""

    def test_process_died_before_request_raises_error(self):
        """Test that if process died before request, we get an error."""
        transport = _create_transport(request_id=0)
        transport._process = MockProcess(poll_result=1)  # Process exited with code 1

        with pytest.raises(ElixirTransportError) as exc_info:
            transport._send_request("test_method", {})

        assert (
            "process died" in str(exc_info.value).lower()
            or "not started" in str(exc_info.value).lower()
        )

    def test_broken_pipe_on_write_raises_error(self):
        """Test that BrokenPipeError on write raises ElixirTransportError."""
        transport = _create_transport(request_id=0)
        transport._process = MagicMock()
        transport._process.poll.return_value = None
        transport._process.stdin.write.side_effect = BrokenPipeError("Pipe broken")

        with pytest.raises(ElixirTransportError) as exc_info:
            transport._send_request("test_method", {})

        assert "Failed to send request" in str(exc_info.value)
