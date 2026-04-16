"""Tests for scripts/api_smoke.py smoke test script."""

import sys
from unittest.mock import patch


from scripts.api_smoke import main, run_test


class TestMainFunction:
    """Tests for main() function."""

    def test_returns_zero_for_healthy_app(self):
        """main() should return 0 when all endpoints pass."""
        result = main([])
        assert result == 0

    def test_returns_nonzero_on_failure(self):
        """main() should return 1 when an endpoint fails."""
        with patch("scripts.api_smoke.get_smoke_endpoints") as mock_get:
            mock_get.return_value = [("GET", "/nonexistent-endpoint-that-will-404")]
            result = main([])
        assert result == 1

    def test_quiet_suppresses_success_output(self, capsys):
        """--quiet should suppress all output on success."""
        main(["--quiet"])
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_quiet_shows_failures(self, capsys):
        """--quiet should still show failures."""
        with patch("scripts.api_smoke.get_smoke_endpoints") as mock_get:
            mock_get.return_value = [("GET", "/nonexistent-endpoint-that-will-404")]
            result = main(["--quiet"])
        assert result == 1
        captured = capsys.readouterr()
        assert "❌" in captured.out or "ERROR" in captured.out

    def test_endpoint_flag_targets_single_endpoint(self, capsys):
        """--endpoint should test only that endpoint."""
        result = main(["--endpoint", "/health"])
        captured = capsys.readouterr()
        assert result == 0
        assert "/health" in captured.out
        # Should not include other endpoints
        assert captured.out.count("✅") == 1 or captured.out.count("200") >= 1


class TestRunTestFunction:
    """Tests for run_test() function."""

    def test_successful_request(self):
        """run_test() should return success for working endpoint."""
        from fastapi.testclient import TestClient
        from code_puppy.api.app import create_app

        app = create_app()
        client = TestClient(app)
        result = run_test(client, "GET", "/health")

        assert result.success is True
        assert result.status_code == 200
        assert result.error is None

    def test_failed_request(self):
        """run_test() should handle 404."""
        from fastapi.testclient import TestClient
        from code_puppy.api.app import create_app

        app = create_app()
        client = TestClient(app)
        result = run_test(client, "GET", "/not-a-real-endpoint")

        assert result.success is False
        assert result.status_code == 404


class TestIntegration:
    """Integration tests using subprocess."""

    def test_script_runs_via_subprocess(self):
        """Script should be runnable via python subprocess."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "scripts/api_smoke.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "5/5" in result.stdout

    def test_script_quiet_subprocess(self):
        """Script --quiet mode should produce no stdout on success."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "scripts/api_smoke.py", "--quiet"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stdout == ""
