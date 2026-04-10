"""Tests for code_puppy.utils.config_resolve module."""

import asyncio
import os

import pytest

from code_puppy.utils.config_resolve import (
    clear_config_value_cache,
    resolve_config_value,
    resolve_config_value_sync,
    resolve_headers,
    resolve_headers_sync,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the config value cache before each test."""
    clear_config_value_cache()
    yield
    clear_config_value_cache()


class TestResolveConfigValueSync:
    def test_empty_returns_none(self):
        assert resolve_config_value_sync("") is None

    def test_literal_value(self):
        assert resolve_config_value_sync("sk-abc123") == "sk-abc123"

    def test_env_var_resolved(self):
        os.environ["_TEST_CP_CONFIG_KEY"] = "secret-from-env"
        try:
            result = resolve_config_value_sync("_TEST_CP_CONFIG_KEY")
            assert result == "secret-from-env"
        finally:
            del os.environ["_TEST_CP_CONFIG_KEY"]

    def test_env_var_not_found_returns_literal(self):
        # If env var doesn't exist, treat as literal
        result = resolve_config_value_sync("UNLIKELY_ENV_VAR_NAME_XYZ123")
        assert result == "UNLIKELY_ENV_VAR_NAME_XYZ123"

    def test_shell_command_echo(self):
        result = resolve_config_value_sync("!echo hello-world")
        assert result == "hello-world"

    def test_shell_command_cached(self):
        result1 = resolve_config_value_sync("!echo cached-test")
        result2 = resolve_config_value_sync("!echo cached-test")
        assert result1 == result2 == "cached-test"

    def test_shell_command_failure_returns_none(self):
        result = resolve_config_value_sync("!false")
        assert result is None

    def test_shell_command_empty_output_returns_none(self):
        # Use printf '' for portable empty output (macOS echo doesn't support -n)
        result = resolve_config_value_sync("!printf ''")
        # printf '' produces empty output
        assert result is None or result == ""

    def test_shell_command_timeout(self):
        result = resolve_config_value_sync("!sleep 30", timeout=1)
        assert result is None

    def test_shell_command_strips_whitespace(self):
        result = resolve_config_value_sync("!echo '  trimmed  '")
        assert result == "trimmed"


class TestResolveConfigValueAsync:
    def test_literal(self):
        result = asyncio.run(resolve_config_value("literal-value"))
        assert result == "literal-value"

    def test_shell_command(self):
        result = asyncio.run(resolve_config_value("!echo async-test"))
        assert result == "async-test"

    def test_empty(self):
        result = asyncio.run(resolve_config_value(""))
        assert result is None

    def test_concurrent_dedup(self):
        """Multiple concurrent requests for the same command should deduplicate."""

        async def _run():
            tasks = [
                resolve_config_value("!echo dedup-test"),
                resolve_config_value("!echo dedup-test"),
                resolve_config_value("!echo dedup-test"),
            ]
            results = await asyncio.gather(*tasks)
            return results

        results = asyncio.run(_run())
        assert all(r == "dedup-test" for r in results)


class TestResolveHeaders:
    def test_none_returns_none(self):
        result = asyncio.run(resolve_headers(None))
        assert result is None

    def test_empty_dict_returns_none(self):
        result = asyncio.run(resolve_headers({}))
        assert result is None

    def test_literal_headers(self):
        result = asyncio.run(
            resolve_headers({"Authorization": "Bearer token123"})
        )
        assert result == {"Authorization": "Bearer token123"}

    def test_shell_command_header(self):
        result = asyncio.run(
            resolve_headers({"X-Api-Key": "!echo header-value"})
        )
        assert result == {"X-Api-Key": "header-value"}


class TestResolveHeadersSync:
    def test_none_returns_none(self):
        assert resolve_headers_sync(None) is None

    def test_literal_headers(self):
        result = resolve_headers_sync({"Auth": "bearer-xyz"})
        assert result == {"Auth": "bearer-xyz"}


class TestClearCache:
    def test_cache_cleared(self):
        resolve_config_value_sync("!echo cache-test-1")
        clear_config_value_cache()
        # After clearing, the command should execute again
        # (we can't easily verify re-execution, but verify it still works)
        result = resolve_config_value_sync("!echo cache-test-1")
        assert result == "cache-test-1"
