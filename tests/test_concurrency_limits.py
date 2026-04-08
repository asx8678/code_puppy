"""Tests for concurrency limiters."""

import asyncio
import os
from pathlib import Path

import pytest

from code_puppy.concurrency_limits import (
    ConcurrencyConfig,
    FileOpsLimiter,
    ApiCallsLimiter,
    ToolCallsLimiter,
    get_concurrency_status,
    reload_concurrency_config,
    create_default_config,
    ensure_config_file,
)


class TestConcurrencyConfig:
    """Test ConcurrencyConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ConcurrencyConfig()
        assert config.file_ops_limit == 4
        assert config.api_calls_limit == 2
        assert config.tool_calls_limit == 8

    def test_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            "file_ops_limit": 10,
            "api_calls_limit": 5,
            "tool_calls_limit": 20,
        }
        config = ConcurrencyConfig.from_dict(data)
        assert config.file_ops_limit == 10
        assert config.api_calls_limit == 5
        assert config.tool_calls_limit == 20

    def test_minimum_values(self):
        """Test that values are clamped to minimum of 1."""
        data = {
            "file_ops_limit": 0,
            "api_calls_limit": -5,
            "tool_calls_limit": 0,
        }
        config = ConcurrencyConfig.from_dict(data)
        assert config.file_ops_limit == 1
        assert config.api_calls_limit == 1
        assert config.tool_calls_limit == 1


class TestConcurrencyStatus:
    """Test concurrency status reporting."""

    def test_get_status(self):
        """Test getting concurrency status."""
        status = get_concurrency_status()
        assert "file_ops_limit" in status
        assert "api_calls_limit" in status
        assert "tool_calls_limit" in status
        assert "file_ops_available" in status
        assert "api_calls_available" in status
        assert "tool_calls_available" in status

        # All values should be positive integers
        for key, value in status.items():
            assert isinstance(value, int)
            assert value >= 1


class TestLimiters:
    """Test context managers for limiting."""

    @pytest.mark.asyncio
    async def test_file_ops_limiter(self):
        """Test FileOpsLimiter context manager."""
        async with FileOpsLimiter():
            # Should acquire and release without error
            pass

    @pytest.mark.asyncio
    async def test_api_calls_limiter(self):
        """Test ApiCallsLimiter context manager."""
        async with ApiCallsLimiter():
            # Should acquire and release without error
            pass

    @pytest.mark.asyncio
    async def test_tool_calls_limiter(self):
        """Test ToolCallsLimiter context manager."""
        async with ToolCallsLimiter():
            # Should acquire and release without error
            pass

    @pytest.mark.asyncio
    async def test_multiple_limiters(self):
        """Test multiple limiters can be used independently."""
        async with FileOpsLimiter():
            async with ApiCallsLimiter():
                async with ToolCallsLimiter():
                    pass

    @pytest.mark.asyncio
    async def test_limiter_respects_limit(self):
        """Test that limiter actually limits concurrency."""
        # This test verifies the semaphore behavior
        acquired_count = 0
        max_concurrent = 0
        current = 0

        async def acquire_and_count():
            nonlocal acquired_count, max_concurrent, current
            async with FileOpsLimiter():
                current += 1
                acquired_count += 1
                max_concurrent = max(max_concurrent, current)
                await asyncio.sleep(0.01)  # Hold for a moment
                current -= 1

        # Start many concurrent tasks
        tasks = [acquire_and_count() for _ in range(20)]
        await asyncio.gather(*tasks)

        # All should have completed
        assert acquired_count == 20
        # But no more than limit should have been concurrent
        # (limit is 4 by default)
        assert max_concurrent <= 4


class TestConfigFile:
    """Test configuration file handling."""

    def test_create_default_config(self):
        """Test creating default configuration."""
        config = create_default_config()
        assert "file_ops_limit" in config
        assert "api_calls_limit" in config
        assert "tool_calls_limit" in config
        assert "[concurrency]" in config

    def test_ensure_config_file(self, tmp_path):
        """Test ensuring config file exists."""
        # Just verify the function works
        result = ensure_config_file()
        assert isinstance(result, Path)
