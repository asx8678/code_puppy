"""Tests for _run_with_streaming_retry transient error handling.

Verifies that transient HTTP errors (RemoteProtocolError, ReadTimeout)
are properly caught and retried with exponential backoff, while
non-retryable errors propagate immediately.

Covers: https://github.com/mpfaffenberger/code_puppy/issues/199
"""

import asyncio
from unittest.mock import AsyncMock, patch

import httpcore
import httpx
import pytest

from pydantic_ai.exceptions import ModelHTTPError


# ---- Helpers to build the retry function in isolation ----
# We extract the retry logic so tests don't need to instantiate the full agent.

MAX_STREAMING_RETRIES = 3
STREAMING_RETRY_DELAYS = [1, 2, 4]
RETRYABLE_EXCEPTIONS = (
    httpx.RemoteProtocolError,
    httpx.ReadTimeout,
    httpcore.RemoteProtocolError,
)


def _is_transient_model_error(error: ModelHTTPError) -> bool:
    """Mirror of the transient error detection helper for isolated testing."""
    if error.status_code == 400:
        body_str = str(error.body or "").lower()
        return "connection prematurely closed" in body_str
    return False


async def _run_with_streaming_retry(run_coro_factory):
    """Mirror of the retry logic in agent_tools.py for isolated testing."""
    last_error = None
    for attempt in range(MAX_STREAMING_RETRIES):
        try:
            return await run_coro_factory()
        except RETRYABLE_EXCEPTIONS as e:
            last_error = e
            if attempt < MAX_STREAMING_RETRIES - 1:
                delay = STREAMING_RETRY_DELAYS[attempt]
                await asyncio.sleep(delay)
        except ModelHTTPError as e:
            if _is_transient_model_error(e):
                last_error = e
                if attempt < MAX_STREAMING_RETRIES - 1:
                    delay = STREAMING_RETRY_DELAYS[attempt]
                    await asyncio.sleep(delay)
            else:
                raise
    raise last_error


# ---- Tests ----


class TestStreamingRetry:
    """Tests for transient HTTP error retry logic."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """No retries needed when the call succeeds immediately."""
        factory = AsyncMock(return_value="ok")

        result = await _run_with_streaming_retry(factory)

        assert result == "ok"
        assert factory.await_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_httpx_remote_protocol_error(self):
        """Retries when httpx.RemoteProtocolError is raised."""
        factory = AsyncMock(
            side_effect=[
                httpx.RemoteProtocolError(
                    "peer closed connection without sending complete message body"
                ),
                "recovered",
            ]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _run_with_streaming_retry(factory)

        assert result == "recovered"
        assert factory.await_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_httpx_read_timeout(self):
        """Retries when httpx.ReadTimeout is raised."""
        factory = AsyncMock(
            side_effect=[
                httpx.ReadTimeout("read timed out"),
                "recovered",
            ]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _run_with_streaming_retry(factory)

        assert result == "recovered"
        assert factory.await_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_httpcore_remote_protocol_error(self):
        """Retries when httpcore.RemoteProtocolError is raised."""
        factory = AsyncMock(
            side_effect=[
                httpcore.RemoteProtocolError(
                    "peer closed connection without sending complete message body"
                ),
                "recovered",
            ]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _run_with_streaming_retry(factory)

        assert result == "recovered"
        assert factory.await_count == 2

    @pytest.mark.asyncio
    async def test_exhausts_retries_then_raises(self):
        """Raises the last error after all retries are exhausted."""
        error = httpx.RemoteProtocolError("persistent failure")
        factory = AsyncMock(side_effect=error)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.RemoteProtocolError, match="persistent failure"):
                await _run_with_streaming_retry(factory)

        assert factory.await_count == MAX_STREAMING_RETRIES

    @pytest.mark.asyncio
    async def test_non_retryable_error_propagates_immediately(self):
        """Non-retryable exceptions are NOT caught — they propagate immediately."""
        factory = AsyncMock(side_effect=ValueError("not a network error"))

        with pytest.raises(ValueError, match="not a network error"):
            await _run_with_streaming_retry(factory)

        assert factory.await_count == 1  # No retry attempted

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self):
        """Verifies exponential backoff delay values between retries."""
        error = httpx.RemoteProtocolError("keep failing")
        factory = AsyncMock(side_effect=error)
        sleep_calls = []

        async def mock_sleep(delay):
            sleep_calls.append(delay)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(httpx.RemoteProtocolError):
                await _run_with_streaming_retry(factory)

        # Only 2 sleeps happen (between attempt 1→2 and 2→3; no sleep after last failure)
        assert sleep_calls == [1, 2]

    @pytest.mark.asyncio
    async def test_recovery_on_last_attempt(self):
        """Succeeds on the final retry attempt."""
        factory = AsyncMock(
            side_effect=[
                httpx.RemoteProtocolError("fail 1"),
                httpx.ReadTimeout("fail 2"),
                "finally worked",
            ]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _run_with_streaming_retry(factory)

        assert result == "finally worked"
        assert factory.await_count == 3

    @pytest.mark.asyncio
    async def test_mixed_retryable_errors(self):
        """Handles different retryable error types across attempts."""
        factory = AsyncMock(
            side_effect=[
                httpx.RemoteProtocolError("peer closed"),
                httpcore.RemoteProtocolError("peer closed again"),
                "success",
            ]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _run_with_streaming_retry(factory)

        assert result == "success"
        assert factory.await_count == 3

    @pytest.mark.asyncio
    async def test_retries_on_transient_modelhttperror(self):
        """Retries when ModelHTTPError with transient body is raised."""
        transient_error = ModelHTTPError(
            status_code=400,
            model_name="test-model",
            body="Connection prematurely closed BEFORE response",
        )
        factory = AsyncMock(side_effect=[transient_error, "recovered"])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _run_with_streaming_retry(factory)

        assert result == "recovered"
        assert factory.await_count == 2

    @pytest.mark.asyncio
    async def test_non_transient_modelhttperror_propagates_immediately(self):
        """Non-transient ModelHTTPError (e.g. real 400) propagates immediately."""
        non_transient_error = ModelHTTPError(
            status_code=400,
            model_name="test-model",
            body="Invalid API key",
        )
        factory = AsyncMock(side_effect=non_transient_error)

        with pytest.raises(ModelHTTPError, match="Invalid API key"):
            await _run_with_streaming_retry(factory)

        assert factory.await_count == 1  # No retry

    @pytest.mark.asyncio
    async def test_transient_modelhttperror_exhausts_retries(self):
        """Raises after exhausting retries for transient ModelHTTPError."""
        transient_error = ModelHTTPError(
            status_code=400,
            model_name="test-model",
            body="Connection prematurely closed BEFORE response",
        )
        factory = AsyncMock(side_effect=transient_error)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ModelHTTPError):
                await _run_with_streaming_retry(factory)

        assert factory.await_count == MAX_STREAMING_RETRIES

    @pytest.mark.asyncio
    async def test_mixed_transient_errors_protocol_and_model(self):
        """Handles mix of RemoteProtocolError and transient ModelHTTPError."""
        transient_model_error = ModelHTTPError(
            status_code=400,
            model_name="test-model",
            body="Connection prematurely closed BEFORE response",
        )
        factory = AsyncMock(
            side_effect=[
                httpx.RemoteProtocolError("peer closed"),
                transient_model_error,
                "success",
            ]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _run_with_streaming_retry(factory)

        assert result == "success"
        assert factory.await_count == 3
