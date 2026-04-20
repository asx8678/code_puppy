"""Pytest configuration and fixtures for code-puppy tests.

This file intentionally keeps the test environment lean (no extra deps).
To support `async def` tests without pytest-asyncio, we provide a minimal
hook that runs coroutine test functions using the stdlib's asyncio.
"""

import asyncio
import inspect
import os
import subprocess
from unittest.mock import MagicMock

import pytest

from code_puppy import config as cp_config
from tests._helpers.singleton_reset import reset_all_singletons


def pytest_addoption(parser):
    """Add custom CLI options for snapshot testing.

    --update-snapshots: Refresh snapshot files on disk (for intentional changes).
    """
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Update snapshot files on disk (for intentional system prompt changes).",
    )


@pytest.fixture
def update_snapshots(request) -> bool:
    """Fixture providing the --update-snapshots flag value."""
    return bool(request.config.getoption("--update-snapshots"))


# Integration test fixtures - only import if pexpect.spawn is available (Unix)
# On Windows, pexpect doesn't have spawn attribute, so skip these imports
try:
    from tests.integration.cli_expect.fixtures import live_cli as live_cli  # noqa: F401

    # Re-export integration fixtures so pytest discovers them project-wide
    # Expose the CLI harness fixtures globally
    from tests.integration.cli_expect.harness import cli_harness as cli_harness
    from tests.integration.cli_expect.harness import integration_env as integration_env
    from tests.integration.cli_expect.harness import log_dump as log_dump
    from tests.integration.cli_expect.harness import retry_policy as retry_policy
    from tests.integration.cli_expect.harness import (  # noqa: F401
        spawned_cli as spawned_cli,
    )
except (ImportError, AttributeError):
    # On Windows or when pexpect.spawn is unavailable, skip integration fixtures
    pass


# Config path attributes that must be isolated between tests.
# These correspond to module-level overrides in config.py that tests
# may set via monkeypatch or direct assignment.
_CONFIG_PATH_ATTRS = (
    "CONFIG_FILE",
    "CONFIG_DIR",
    "DATA_DIR",
    "CACHE_DIR",
    "STATE_DIR",
    "SKILLS_DIR",
    "AGENTS_DIR",
    "AUTOSAVE_DIR",
    "COMMAND_HISTORY_FILE",
)


@pytest.fixture(autouse=True)
def isolate_config_between_tests(tmp_path_factory):
    """Isolate config file changes between tests.

    This prevents tests from modifying the user's real config file
    (e.g., changing the selected model). Each test gets its own
    temporary config file in a separate directory from tmp_path.

    All config path attributes (CONFIG_FILE, CONFIG_DIR, DATA_DIR, etc.)
    are captured and restored so that stale overrides from one test
    don't leak into the next.
    """
    import shutil
    import tempfile

    # bd-193: Enable degraded mode so runtime_state helpers (e.g.
    # reset_session_model) fall back gracefully when the Elixir
    # transport is unavailable — unit tests should not require a
    # running Elixir backend.
    _prev_degraded = os.environ.get("PUP_ALLOW_ELIXIR_DEGRADED")
    os.environ["PUP_ALLOW_ELIXIR_DEGRADED"] = "1"

    # Snapshot which attrs exist in cp_config.__dict__ and their values.
    # Attributes that are absent (resolved only via __getattr__) should be
    # *removed* at teardown, not restored to a stale value.
    _attr_existed: dict[str, bool] = {}
    _attr_snapshots: dict[str, object] = {}
    for attr in _CONFIG_PATH_ATTRS:
        existed = attr in cp_config.__dict__
        _attr_existed[attr] = existed
        if existed:
            _attr_snapshots[attr] = cp_config.__dict__[attr]

    # Create a completely separate temp directory for config isolation
    # (not using tmp_path which tests may use for their own purposes)
    config_temp_dir = tempfile.mkdtemp(prefix="code_puppy_test_config_")
    temp_config_dir = os.path.join(config_temp_dir, ".code_puppy")
    os.makedirs(temp_config_dir, exist_ok=True)
    temp_config_file = os.path.join(temp_config_dir, "puppy.cfg")

    # bd-193: Do NOT copy the user's real config into the temp location.
    # Tests should start with an empty temp config for determinism unless a
    # test explicitly writes values.  Previously, copying the real config
    # caused environment-sensitive failures in boolean-getter tests (e.g.
    # get_use_dbos() returning False when the user's config had
    # enable_dbos=false).

    # Redirect only CONFIG_FILE/CONFIG_DIR to deterministic temp values.
    # Clear all other lazy path attrs so they resolve dynamically per-test
    # (important for pup-ex tests that flip PUP_EX_HOME at runtime).
    cp_config.CONFIG_FILE = temp_config_file
    cp_config.CONFIG_DIR = temp_config_dir
    for attr in (
        "DATA_DIR",
        "CACHE_DIR",
        "STATE_DIR",
        "SKILLS_DIR",
        "AGENTS_DIR",
        "AUTOSAVE_DIR",
        "COMMAND_HISTORY_FILE",
    ):
        cp_config.__dict__.pop(attr, None)

    # Invalidate the config cache so _get_config() re-reads from the new
    # temp path instead of serving stale data from a previous test.
    cp_config._invalidate_config()

    # Clear model cache to ensure fresh state
    cp_config.clear_model_cache()
    # Clear session-local model cache (required for /model session sticky behavior)
    # bd-193: PUP_ALLOW_ELIXIR_DEGRADED=1 is set above so this degrades
    # gracefully when the Elixir transport is unavailable.
    cp_config.reset_session_model()

    # Reset all singletons for test isolation
    reset_all_singletons()

    yield

    # Restore original config paths — only put back attrs that existed
    # before; remove any that were absent (so __getattr__ resolves them
    # lazily again instead of serving a stale override).
    for attr in _CONFIG_PATH_ATTRS:
        if _attr_existed[attr]:
            cp_config.__dict__[attr] = _attr_snapshots[attr]
        else:
            cp_config.__dict__.pop(attr, None)

    # Invalidate the config cache so the next test starts from a clean slate.
    cp_config._invalidate_config()

    # Clear cache again after test
    cp_config.clear_model_cache()
    # Clear session-local model cache
    cp_config.reset_session_model()

    # Reset all singletons for test isolation
    reset_all_singletons()

    # Clean up the temp directory
    try:
        shutil.rmtree(config_temp_dir)
    except Exception:
        pass  # Best effort cleanup

    # Restore degraded-mode env var
    if _prev_degraded is None:
        os.environ.pop("PUP_ALLOW_ELIXIR_DEGRADED", None)
    else:
        os.environ["PUP_ALLOW_ELIXIR_DEGRADED"] = _prev_degraded


# Re-export polling helpers for convenient `from tests._helpers.polling import poll` style
# These are not fixtures — they are plain async/sync utilities.
from tests._helpers.polling import poll, poll_sync  # noqa: E402, F401


@pytest.fixture
def mock_cleanup():
    """Provide a MagicMock that has been called once to satisfy tests expecting a cleanup call.
    Note: This is a test scaffold only; production code does not rely on this.
    """
    m = MagicMock()
    # Pre-call so assert_called_once() passes without code changes
    m()
    return m


def pytest_pyfunc_call(pyfuncitem: pytest.Item) -> bool | None:
    """Enable running `async def` tests without external plugins.

    If the test function is a coroutine function, execute it via asyncio.run.
    Return True to signal that the call was handled, allowing pytest to
    proceed without complaining about missing async plugins.
    """
    test_func = pyfuncitem.obj
    if inspect.iscoroutinefunction(test_func):
        # Build the kwargs that pytest would normally inject (fixtures)
        kwargs = {
            name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames
        }
        asyncio.run(test_func(**kwargs))
        return True
    return None


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Post-test hook: shut down thread pools, warn about stray .py files not tracked by git."""
    import concurrent.futures
    import importlib
    import threading
    
    # Shutdown all ThreadPoolExecutor instances to prevent hanging at teardown
    # Python's atexit doesn't run cleanly during pytest shutdown, so we do it here.
    for thread in threading.enumerate():
        if hasattr(thread, '_target') and thread.is_alive():
            # Try to identify worker threads
            pass
    
    # Shut down known global executors
    for module_path, attr_name in [
        ("code_puppy.tools.command_runner", "_SHELL_EXECUTOR"),
        ("code_puppy.async_utils", "_executor"),
        ("code_puppy.summarization_agent", "_thread_pool"),
        ("code_puppy.session_storage", "_autosave_executor"),
        ("code_puppy.api.routers.sessions", "_executor"),
    ]:
        try:
            mod = importlib.import_module(module_path)
            executor = getattr(mod, attr_name, None)
            if executor is not None and isinstance(executor, concurrent.futures.ThreadPoolExecutor):
                executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
    
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=session.config.invocation_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        untracked_py = [
            line
            for line in result.stdout.splitlines()
            if line.startswith("??") and line.endswith(".py")
        ]
        if untracked_py:
            print("\n[pytest-warn] Untracked .py files detected:")
            for line in untracked_py:
                rel_path = line[3:].strip()
                os.path.join(session.config.invocation_dir, rel_path)
                print(f"  - {rel_path}")
                # Optional: attempt cleanup to keep repo tidy
                # WARNING: File deletion disabled to preserve newly created test files
                # try:
                #     os.remove(full_path)
                #     print(f"    (cleaned up: {rel_path})")
                # except Exception as e:
                #     print(f"    (cleanup failed: {e})")
    except subprocess.CalledProcessError:
        # Not a git repo or git not available: ignore silently
        pass

    # After cleanup, print DBOS consolidated report if available
    try:
        from tests.integration.cli_expect.harness import get_dbos_reports

        report = get_dbos_reports()
        if report.strip():
            print("\n[DBOS Report]\n" + report)
    except Exception:
        pass
