"""Tests for API security features including auth rate limiting."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from code_puppy.api.security import (
    require_api_access,
    reset_auth_rate_limits,
    _check_auth_rate_limit,
    _record_auth_failure,
    _get_client_ip,
    AUTH_RATE_LIMIT_MAX_FAILURES,
)


class TestAuthRateLimiting:
    """Tests for authentication rate limiting."""

    def setup_method(self):
        """Reset rate limits before each test."""
        reset_auth_rate_limits()

    def teardown_method(self):
        """Clean up after each test."""
        reset_auth_rate_limits()

    def _make_request(self, client_ip: str = "192.168.1.100") -> MagicMock:
        """Create a mock request with given client IP."""
        request = MagicMock()
        request.client.host = client_ip
        request.headers = {}
        return request

    def test_first_failure_allowed(self):
        """First auth failure should not trigger rate limit."""
        request = self._make_request()

        # Should not raise
        _check_auth_rate_limit(request)

    def test_rate_limit_after_max_failures(self):
        """Should return 429 after max failures."""
        request = self._make_request()

        # Record max failures
        for _ in range(AUTH_RATE_LIMIT_MAX_FAILURES):
            _record_auth_failure(request)

        # Next check should raise 429
        with pytest.raises(HTTPException) as exc_info:
            _check_auth_rate_limit(request)

        assert exc_info.value.status_code == 429
        assert "Too many authentication failures" in exc_info.value.detail
        assert "Retry-After" in exc_info.value.headers

    def test_different_ips_tracked_separately(self):
        """Different IPs should have separate rate limits."""
        request1 = self._make_request("10.0.0.1")
        request2 = self._make_request("10.0.0.2")

        # Max out IP 1
        for _ in range(AUTH_RATE_LIMIT_MAX_FAILURES):
            _record_auth_failure(request1)

        # IP 1 should be blocked
        with pytest.raises(HTTPException) as exc_info:
            _check_auth_rate_limit(request1)
        assert exc_info.value.status_code == 429

        # IP 2 should still be allowed
        _check_auth_rate_limit(request2)  # Should not raise

    def test_reset_clears_limits(self):
        """reset_auth_rate_limits should clear all tracked failures."""
        request = self._make_request()

        # Record failures
        for _ in range(AUTH_RATE_LIMIT_MAX_FAILURES):
            _record_auth_failure(request)

        # Verify blocked
        with pytest.raises(HTTPException):
            _check_auth_rate_limit(request)

        # Reset
        reset_auth_rate_limits()

        # Should be allowed again
        _check_auth_rate_limit(request)  # Should not raise

    def test_get_client_ip_direct(self):
        """Should extract IP from request.client.host."""
        request = self._make_request("1.2.3.4")
        assert _get_client_ip(request) == "1.2.3.4"

    def test_get_client_ip_forwarded(self):
        """Should prefer X-Forwarded-For header."""
        request = self._make_request("127.0.0.1")
        request.headers = {"X-Forwarded-For": "203.0.113.50, 70.41.3.18"}

        assert _get_client_ip(request) == "203.0.113.50"

    def test_retry_after_header(self):
        """429 response should include valid Retry-After header."""
        request = self._make_request()

        for _ in range(AUTH_RATE_LIMIT_MAX_FAILURES):
            _record_auth_failure(request)

        with pytest.raises(HTTPException) as exc_info:
            _check_auth_rate_limit(request)

        retry_after = int(exc_info.value.headers["Retry-After"])
        assert 1 <= retry_after <= 60  # Should be within the window


class TestRequireApiAccessWithRateLimiting:
    """Integration tests for require_api_access with rate limiting."""

    def setup_method(self):
        reset_auth_rate_limits()

    def teardown_method(self):
        reset_auth_rate_limits()

    def _make_request(self, client_ip: str = "192.168.1.100") -> MagicMock:
        request = MagicMock()
        request.client.host = client_ip
        request.headers = {}
        return request

    @patch.dict(
        "os.environ",
        {"CODE_PUPPY_API_TOKEN": "secret-token", "CODE_PUPPY_REQUIRE_TOKEN": "1"},
    )
    def test_invalid_token_records_failure(self):
        """Invalid token should record auth failure."""
        request = self._make_request()
        creds = MagicMock()
        creds.credentials = "wrong-token"

        # Should fail and record
        with pytest.raises(HTTPException) as exc_info:
            require_api_access(request, creds)
        assert exc_info.value.status_code == 401

        # Do it max times
        for _ in range(AUTH_RATE_LIMIT_MAX_FAILURES - 1):
            with pytest.raises(HTTPException):
                require_api_access(request, creds)

        # Next should be rate limited
        with pytest.raises(HTTPException) as exc_info:
            require_api_access(request, creds)
        assert exc_info.value.status_code == 429

    @patch.dict(
        "os.environ",
        {"CODE_PUPPY_API_TOKEN": "secret-token", "CODE_PUPPY_REQUIRE_TOKEN": "1"},
    )
    def test_missing_creds_records_failure(self):
        """Missing credentials should record auth failure."""
        request = self._make_request()

        # Should fail and record
        with pytest.raises(HTTPException) as exc_info:
            require_api_access(request, None)
        assert exc_info.value.status_code == 401
