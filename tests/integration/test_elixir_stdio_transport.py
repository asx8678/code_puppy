"""
Integration tests for the Elixir stdio transport.

These tests verify that the Python client can communicate with
the Elixir stdio service correctly.

Run with:
    pytest tests/integration/test_elixir_stdio_transport.py -v

Or to skip integration tests:
    pytest tests/integration/test_elixir_stdio_transport.py -v --ignore-glob='*integration*'
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration

# Skip if Elixir is not available
elixir_available = shutil.which("elixir") is not None


@pytest.fixture(scope="module")
def elixir_project_path():
    """Path to the code_puppy_control Elixir project."""
    # Look for the elixir directory relative to tests
    current_file = Path(__file__).resolve()
    project_root = current_file.parent.parent.parent

    possible_paths = [
        project_root / "elixir" / "code_puppy_control",
        project_root.parent / "elixir" / "code_puppy_control",
    ]

    for path in possible_paths:
        if (path / "mix.exs").exists():
            return str(path.resolve())

    pytest.skip("Could not find code_puppy_control Elixir project")


@pytest.fixture
def stdio_service(elixir_project_path):
    """
    Start the Elixir stdio service as a subprocess.

    Yields a subprocess.Popen that communicates via stdin/stdout.
    """
    if not elixir_available:
        pytest.skip("Elixir not available")

    cmd = ["mix", "code_puppy.stdio_service"]

    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=elixir_project_path,
        )

        # Wait for service to be ready
        start_time = time.time()
        ready = False

        while time.time() - start_time < 10:
            try:
                # Send ping
                request = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()

                # Read response
                response_line = process.stdout.readline()
                if response_line:
                    response = json.loads(response_line)
                    if response.get("result", {}).get("pong"):
                        ready = True
                        break
            except Exception:
                pass

            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr else ""
                pytest.fail(f"Service exited early with code {process.returncode}: {stderr[:500]}")

            time.sleep(0.1)

        if not ready:
            process.terminate()
            pytest.fail("Timeout waiting for service to be ready")

        yield process

    finally:
        if 'process' in locals() and process.poll() is None:
            try:
                process.stdin.close()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


@pytest.fixture
def test_dir():
    """Create a temporary directory with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        (Path(tmpdir) / "file1.txt").write_text("Line 1\nLine 2\nLine 3\n")
        (Path(tmpdir) / "file2.py").write_text("def hello():\n    return 'world'\n")

        # Create subdirectory
        subdir = Path(tmpdir) / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("Nested content\n")

        yield tmpdir


class TestBasicProtocol:
    """Tests for basic JSON-RPC protocol compliance."""

    def test_ping(self, stdio_service):
        """Test that ping returns pong."""
        request = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert response["result"]["pong"] is True
        assert "timestamp" in response["result"]

    def test_health_check(self, stdio_service):
        """Test health check returns service information."""
        request = {"jsonrpc": "2.0", "id": 2, "method": "health_check", "params": {}}
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 2
        assert response["result"]["status"] == "healthy"
        assert "version" in response["result"]
        assert "elixir_version" in response["result"]
        assert "otp_version" in response["result"]

    def test_method_not_found(self, stdio_service):
        """Test that unknown methods return proper error."""
        request = {"jsonrpc": "2.0", "id": 3, "method": "unknown_method", "params": {}}
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 3
        assert "error" in response
        assert response["error"]["code"] == -32601
        assert "Method not found" in response["error"]["message"]

    def test_invalid_json(self, stdio_service):
        """Test that invalid JSON returns parse error."""
        stdio_service.stdin.write("not valid json\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert response["jsonrpc"] == "2.0"
        assert "error" in response
        assert response["error"]["code"] == -32700
        assert "Parse error" in response["error"]["message"]


class TestFileOperations:
    """Tests for file operation methods."""

    def test_file_list(self, stdio_service, test_dir):
        """Test listing files in a directory."""
        request = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "file_list",
            "params": {"directory": test_dir, "recursive": False}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 10
        assert "result" in response
        assert "files" in response["result"]

        files = response["result"]["files"]
        paths = [f["path"] for f in files]

        assert "file1.txt" in paths
        assert "file2.py" in paths
        assert "subdir" in paths

    def test_file_list_recursive(self, stdio_service, test_dir):
        """Test recursive file listing."""
        request = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "file_list",
            "params": {"directory": test_dir, "recursive": True}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        files = response["result"]["files"]
        paths = [f["path"] for f in files]

        assert "file1.txt" in paths
        assert "subdir/nested.txt" in paths

    def test_file_read(self, stdio_service, test_dir):
        """Test reading a file."""
        file_path = os.path.join(test_dir, "file1.txt")

        request = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "file_read",
            "params": {"path": file_path}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 12

        result = response["result"]
        assert result["path"] == file_path
        assert "Line 1" in result["content"]
        assert result["num_lines"] == 3
        assert result["truncated"] is False
        assert result["error"] is None

    def test_file_read_with_line_range(self, stdio_service, test_dir):
        """Test reading specific line range."""
        file_path = os.path.join(test_dir, "file1.txt")

        request = {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "file_read",
            "params": {"path": file_path, "start_line": 2, "num_lines": 1}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        result = response["result"]
        assert result["content"] == "Line 2"
        assert result["truncated"] is True

    def test_file_read_nonexistent(self, stdio_service, test_dir):
        """Test reading a non-existent file returns error."""
        file_path = os.path.join(test_dir, "nonexistent.txt")

        request = {
            "jsonrpc": "2.0",
            "id": 14,
            "method": "file_read",
            "params": {"path": file_path}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert "error" in response
        assert response["error"]["code"] == -32000

    def test_file_read_missing_path_param(self, stdio_service):
        """Test that missing path parameter returns proper error."""
        request = {
            "jsonrpc": "2.0",
            "id": 15,
            "method": "file_read",
            "params": {}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert "error" in response
        assert response["error"]["code"] == -32602
        assert "Missing required param" in response["error"]["message"]


class TestBatchOperations:
    """Tests for batch file operations."""

    def test_file_read_batch(self, stdio_service, test_dir):
        """Test reading multiple files in batch."""
        paths = [
            os.path.join(test_dir, "file1.txt"),
            os.path.join(test_dir, "file2.py"),
        ]

        request = {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "file_read_batch",
            "params": {"paths": paths}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 20

        files = response["result"]["files"]
        assert len(files) == 2

        # Both should be readable
        assert all(f["error"] is None for f in files)

    def test_file_read_batch_partial_failure(self, stdio_service, test_dir):
        """Test batch read handles partial failures gracefully."""
        paths = [
            os.path.join(test_dir, "file1.txt"),
            os.path.join(test_dir, "nonexistent.txt"),
        ]

        request = {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "file_read_batch",
            "params": {"paths": paths}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        files = response["result"]["files"]

        # Both entries should exist
        assert len(files) == 2

        # At least one should have an error (the nonexistent file)
        errors = [f for f in files if f["error"] is not None]
        assert len(errors) >= 1

    def test_file_read_batch_empty_paths(self, stdio_service):
        """Test batch read with empty paths returns error."""
        request = {
            "jsonrpc": "2.0",
            "id": 22,
            "method": "file_read_batch",
            "params": {"paths": []}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert "error" in response
        assert response["error"]["code"] == -32602


class TestGrep:
    """Tests for grep search functionality."""

    def test_grep_find_pattern(self, stdio_service, test_dir):
        """Test finding a pattern in files."""
        request = {
            "jsonrpc": "2.0",
            "id": 30,
            "method": "grep_search",
            "params": {"pattern": "def ", "directory": test_dir}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 30

        matches = response["result"]["matches"]
        assert len(matches) >= 1

        # Check structure
        match = matches[0]
        assert "file" in match
        assert "line_number" in match
        assert "line_content" in match
        assert "def " in match["line_content"]

    def test_grep_case_sensitive(self, stdio_service, test_dir):
        """Test that grep is case sensitive by default."""
        request = {
            "jsonrpc": "2.0",
            "id": 31,
            "method": "grep_search",
            "params": {"pattern": "DEF ", "directory": test_dir}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        matches = response["result"]["matches"]
        # Should be empty (case sensitive)
        assert len(matches) == 0

    def test_grep_case_insensitive(self, stdio_service, test_dir):
        """Test case insensitive grep."""
        request = {
            "jsonrpc": "2.0",
            "id": 32,
            "method": "grep_search",
            "params": {"pattern": "DEF ", "directory": test_dir, "case_sensitive": False}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        matches = response["result"]["matches"]
        # Should find the match now
        assert len(matches) >= 1

    def test_grep_invalid_pattern(self, stdio_service, test_dir):
        """Test that invalid regex patterns return proper error."""
        request = {
            "jsonrpc": "2.0",
            "id": 33,
            "method": "grep_search",
            "params": {"pattern": "[invalid", "directory": test_dir}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert "error" in response
        assert response["error"]["code"] == -32000


class TestSecurity:
    """Tests for security validations."""

    def test_file_read_blocked_sensitive_path(self, stdio_service):
        """Test that sensitive paths are blocked."""
        home = os.path.expanduser("~")
        sensitive_path = os.path.join(home, ".ssh", "id_rsa")

        request = {
            "jsonrpc": "2.0",
            "id": 40,
            "method": "file_read",
            "params": {"path": sensitive_path}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert "error" in response
        assert "sensitive path blocked" in response["error"]["message"]

    def test_list_files_blocked_sensitive_directory(self, stdio_service):
        """Test that sensitive directories are blocked."""
        request = {
            "jsonrpc": "2.0",
            "id": 41,
            "method": "file_list",
            "params": {"directory": "/etc"}
        }
        stdio_service.stdin.write(json.dumps(request) + "\n")
        stdio_service.stdin.flush()

        response_line = stdio_service.stdout.readline()
        response = json.loads(response_line)

        assert "error" in response
        assert "sensitive path blocked" in response["error"]["message"]


class TestPythonClientAdapter:
    """Tests for the Python client adapter."""

    def test_transport_context_manager(self, elixir_project_path):
        """Test that the transport works as a context manager."""
        try:
            from code_puppy.elixir_transport import ElixirTransport
        except ImportError:
            pytest.skip("elixir_transport module not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.txt").write_text("Hello, World!")

            with ElixirTransport(project_path=elixir_project_path) as transport:
                # Test list_files
                files = transport.list_files(tmpdir)
                paths = [f["path"] for f in files]
                assert "test.txt" in paths

                # Test read_file
                result = transport.read_file(os.path.join(tmpdir, "test.txt"))
                assert result["content"] == "Hello, World!"

    def test_transport_ping(self, elixir_project_path):
        """Test transport ping method."""
        try:
            from code_puppy.elixir_transport import ElixirTransport
        except ImportError:
            pytest.skip("elixir_transport module not available")

        transport = ElixirTransport(project_path=elixir_project_path)
        transport.start()
        try:
            result = transport.ping()
            assert result["pong"] is True
        finally:
            transport.stop()

    def test_transport_health_check(self, elixir_project_path):
        """Test transport health check."""
        try:
            from code_puppy.elixir_transport import ElixirTransport
        except ImportError:
            pytest.skip("elixir_transport module not available")

        transport = ElixirTransport(project_path=elixir_project_path)
        transport.start()
        try:
            result = transport.health_check()
            assert result["status"] == "healthy"
            assert "version" in result
        finally:
            transport.stop()
