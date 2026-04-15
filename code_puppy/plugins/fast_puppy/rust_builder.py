"""Rust build functionality for Fast Puppy plugin.

This module contains all build-related code for Fast Puppy.
It is separated from builder.py (which handles discovery-only functions)
to simplify the architecture after bd-91 removed auto-build functionality.

Usage:
    from code_puppy.plugins.fast_puppy.rust_builder import build_single_crate
    success = build_single_crate("code_puppy_core")

Note:
    Builds require a restart of code-puppy to activate, as we no longer
    use importlib.reload() for runtime patching (bd-91).
"""

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from code_puppy.messaging import emit_info

# Import discovery functions from builder.py (avoid circular import)
from code_puppy.plugins.fast_puppy.builder import (
    CRATES,
    _find_crate_dir,
    _is_crate_installed,
)

logger = logging.getLogger(__name__)


def _has_rust_toolchain() -> bool:
    """Check if Rust compiler is available."""
    return shutil.which("rustc") is not None


def _has_maturin() -> bool:
    """Check if maturin is available (in PATH, via uv run, or as Python module)."""
    # Direct PATH lookup
    if shutil.which("maturin"):
        return True

    # Check uv can run maturin (works in uvx environments with [rust] extra)
    if shutil.which("uv"):
        # Try 'uv run maturin' (uses project/uvx environment)
        try:
            result = subprocess.run(
                ["uv", "run", "maturin", "--version"],
                capture_output=True,
                timeout=10,
                env=_build_env(),
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass

        # Try 'uv tool run maturin' (uses uv tool directory)
        try:
            result = subprocess.run(
                ["uv", "tool", "run", "maturin", "--version"],
                capture_output=True,
                timeout=10,
                env=_build_env(),
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass

    # Try as Python module (pip-installed maturin)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "maturin", "--version"],
            capture_output=True,
            timeout=10,
            env=_build_env(),
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    return False


def _install_maturin() -> tuple[bool, str]:
    """Try to install maturin using uv or pip.

    Returns (success, error_message). If successful, error_message is empty.
    """
    errors: list[str] = []

    # Try uv tool install first (works best in uvx environments)
    if shutil.which("uv"):
        try:
            result = subprocess.run(
                ["uv", "tool", "install", "maturin"],
                capture_output=True,
                text=True,
                timeout=120,
                env=_build_env(),
            )
            if result.returncode == 0:
                logger.debug("Installed maturin via uv tool install")
                return True, ""
            else:
                err = result.stderr.strip() if result.stderr else "(no output)"
                errors.append(f"uv tool install: {err[:200]}")
                logger.debug("uv tool install maturin failed: %s", err)
        except Exception as exc:
            errors.append(f"uv tool install: {exc}")
            logger.debug("uv tool install maturin failed: %s", exc)

    # Try uv pip install (fallback for virtualenv users)
    if shutil.which("uv"):
        try:
            result = subprocess.run(
                ["uv", "pip", "install", "maturin"],
                capture_output=True,
                text=True,
                timeout=120,
                env=_build_env(),
            )
            if result.returncode == 0:
                logger.debug("Installed maturin via uv pip")
                return True, ""
            else:
                err = result.stderr.strip() if result.stderr else "(no output)"
                errors.append(f"uv pip install: {err[:200]}")
                logger.debug("uv pip install maturin failed: %s", err)
        except Exception as exc:
            errors.append(f"uv pip install: {exc}")
            logger.debug("uv pip install maturin failed: %s", exc)

    # Fall back to pip
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "maturin"],
            capture_output=True,
            text=True,
            timeout=120,
            env=_build_env(),
        )
        if result.returncode == 0:
            logger.debug("Installed maturin via pip")
            return True, ""
        else:
            err = result.stderr.strip() if result.stderr else "(no output)"
            errors.append(f"pip install: {err[:200]}")
            logger.debug("pip install maturin failed: %s", err)
    except Exception as exc:
        errors.append(f"pip install: {exc}")
        logger.debug("pip install maturin failed: %s", exc)

    error_summary = " | ".join(errors) if errors else "all methods failed"
    return False, error_summary


def _get_maturin_command() -> list[str]:
    """Get the appropriate maturin command as a list.

    Priority:
    1. 'uv run maturin' (preferred - uses project/uvx environment, managed by uv)
    2. 'uv tool run maturin' (uses uv tool directory - works after 'uv tool install')
    3. Direct maturin in PATH (fallback if uv is unavailable)
    4. Python module fallback
    """
    if shutil.which("uv"):
        # Prefer 'uv run maturin' for reliable environment management
        try:
            result = subprocess.run(
                ["uv", "run", "maturin", "--version"],
                capture_output=True,
                timeout=5,
                env=_build_env(),
            )
            if result.returncode == 0:
                return ["uv", "run", "maturin"]
        except Exception:
            pass

        # Try 'uv tool run maturin' (works after 'uv tool install maturin')
        try:
            result = subprocess.run(
                ["uv", "tool", "run", "maturin", "--version"],
                capture_output=True,
                timeout=5,
                env=_build_env(),
            )
            if result.returncode == 0:
                return ["uv", "tool", "run", "maturin"]
        except Exception:
            pass

    # Direct PATH lookup as fallback
    if shutil.which("maturin"):
        return ["maturin"]

    # Fallback to Python module
    return [sys.executable, "-m", "maturin"]


def _build_env() -> dict[str, str]:
    """Build the environment dict for maturin subprocesses.

    Ensures VIRTUAL_ENV is set so maturin can locate the target venv.
    When running via ``uv run`` or certain entry-points, the parent
    process may not have VIRTUAL_ENV in its own env even though
    ``sys.prefix`` points inside a venv.  Maturin relies on this variable
    to decide where to install the compiled extension.
    """
    env = os.environ.copy()

    # If VIRTUAL_ENV is already set, trust it.
    if env.get("VIRTUAL_ENV"):
        logger.debug("VIRTUAL_ENV already set: %s", env.get("VIRTUAL_ENV"))
        return env

    # Detect active venv via sys.prefix vs sys.base_prefix.
    # Inside a venv, sys.prefix points to the venv root while
    # sys.base_prefix points to the system Python.
    if sys.prefix != sys.base_prefix:
        env["VIRTUAL_ENV"] = sys.prefix
        logger.debug("Deriving VIRTUAL_ENV from sys.prefix: %s", sys.prefix)
    else:
        # Not in a venv — check for a .venv next to the repo root
        # or cwd.  This handles cases where the user activated a
        # venv in a parent shell but the env var didn't propagate.
        logger.debug("Falling back to .venv detection (sys.prefix == sys.base_prefix)")
        if sys.platform == "win32":
            python_rel = Path("Scripts") / "python.exe"
        else:
            python_rel = Path("bin") / "python"

        for candidate in (
            Path(sys.prefix).parent / ".venv",
            Path.cwd() / ".venv",
        ):
            if candidate.is_dir() and (candidate / python_rel).exists():
                env["VIRTUAL_ENV"] = str(candidate)
                logger.debug(
                    "Auto-detected VIRTUAL_ENV=%s for maturin subprocess",
                    candidate,
                )
                break

    # Log the final VIRTUAL_ENV value or indicate none was found
    if env.get("VIRTUAL_ENV"):
        logger.debug("Final VIRTUAL_ENV value: %s", env.get("VIRTUAL_ENV"))
    else:
        logger.debug("No VIRTUAL_ENV found (none will be set for maturin subprocess)")
        logger.warning(
            "No virtual environment detected. Rust builds may fail to find Python."
        )

    return env


def _emit_build_heartbeat(
    proc: subprocess.Popen, crate_name: str, stop_event: threading.Event
) -> None:
    """Emit heartbeat messages during long builds.

    Runs in a daemon thread, emits message every 20 seconds.
    """
    start_time = time.time()
    next_heartbeat = 20.0

    while not stop_event.is_set() and proc.poll() is None:
        elapsed = time.time() - start_time
        if elapsed >= next_heartbeat:
            emit_info(
                f"🐕⚡ Fast Puppy: Still building {crate_name}… ({int(elapsed)}s elapsed)"
            )
            next_heartbeat += 20.0
        time.sleep(1.0)


def _build_crate(crate_dir: Path, crate_name: str) -> tuple[bool, str]:
    """Build and install a Rust crate into the current environment.

    Returns (success, error_msg).
    Uses 600 second timeout (turbo_parse is slow).
    """
    # Log free-threading status for build diagnostics
    try:
        gil_enabled = sys._is_gil_enabled()
        logger.info(
            "Building %s (GIL %s)",
            crate_name,
            "enabled" if gil_enabled else "disabled — free-threaded",
        )
    except AttributeError:
        pass
    cmd_base = _get_maturin_command()
    cmd = cmd_base + [
        "develop",
        "--release",
        "--manifest-path",
        str(crate_dir / "Cargo.toml"),
    ]

    build_env = _build_env()

    try:
        # Use Popen for heartbeat support on long builds
        # NOTE: cwd must be repo root (parent of crate_dir), NOT the crate dir itself.
        # When using 'uv run maturin', running from inside a directory with pyproject.toml
        # causes uv to try building that package first, which fails with free-threaded Python.
        # The --manifest-path flag already tells maturin where Cargo.toml is, so crate_dir as cwd is redundant AND harmful.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(crate_dir.parent),
            env=build_env,
        )

        # Start heartbeat thread for builds >30s
        stop_event = threading.Event()
        heartbeat_thread = threading.Thread(
            target=_emit_build_heartbeat,
            args=(proc, crate_name, stop_event),
            daemon=True,
        )
        heartbeat_thread.start()

        try:
            stdout, stderr = proc.communicate(timeout=600)  # 10 min max
        finally:
            stop_event.set()
            heartbeat_thread.join(timeout=2.0)

        if proc.returncode == 0:
            return True, ""
        else:
            # Filter out warning lines from stderr so real errors are visible
            if stderr:
                filtered_lines = [
                    line
                    for line in stderr.strip().splitlines()
                    if not line.strip().startswith("warning:")
                ]
                error_msg = "\n".join(filtered_lines)
                if not error_msg:
                    # All lines were warnings - fall back to stdout or generic message
                    error_msg = (
                        stdout.strip()
                        if stdout
                        else "(build failed with warnings only — see logs)"
                    )
            elif stdout:
                error_msg = stdout.strip()
            else:
                error_msg = "Unknown error"
            return False, error_msg

    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return False, "Build timed out after 600 seconds"
    except Exception as e:
        return False, str(e)


def _prewarm_workspace(repo_root: Path) -> None:
    """Pre-warm cargo workspace by building shared dependencies once.

    Runs `cargo build --release --workspace` as a non-fatal optimization.
    Individual maturin builds will handle any issues if this fails.
    """
    try:
        result = subprocess.run(
            ["cargo", "build", "--release", "--workspace"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 min for prewarm
            cwd=str(repo_root),
            env=_build_env(),
        )
        if result.returncode == 0:
            logger.debug("Workspace prewarm completed successfully")
    except Exception as e:
        logger.debug("Workspace prewarm failed (non-fatal): %s", e)


def notify_build_complete(crate_name: str) -> str:
    """Notify user that build completed and restart may be needed.

    bd-91: Replaces the deprecated importlib.reload() approach.
    We no longer attempt runtime reloading - user must restart code-puppy
    to activate the newly built crate.

    Args:
        crate_name: Name of the crate that was built.

    Returns:
        A user-friendly message indicating build success and next steps.
    """
    return (
        f"✅ {crate_name} built successfully.\n"
        f"   Note: Restart code-puppy to activate the new build."
    )


def build_single_crate(crate_name: str) -> bool:
    """Build one specific crate by name from the CRATES registry.

    Returns True on success, False otherwise.

    Note:
        After successful build, the crate is installed in the environment
        but requires a restart of code-puppy to be activated.
        Use notify_build_complete() to inform the user.
    """
    # Find the crate spec
    crate_spec = None
    for spec in CRATES:
        if spec["name"] == crate_name:
            crate_spec = spec
            break

    if crate_spec is None:
        logger.debug("Unknown crate name: %s", crate_name)
        return False

    # Check prerequisites
    if not _has_rust_toolchain():
        logger.debug("Rust toolchain not available for building %s", crate_name)
        return False

    if not _has_maturin():
        install_ok, _ = _install_maturin()
        if not install_ok:
            logger.debug("Could not install maturin for building %s", crate_name)
            return False

    crate_dir = _find_crate_dir(crate_spec["dir"])
    if crate_dir is None:
        logger.debug("Crate directory not found for %s", crate_name)
        return False

    # Build it
    success, error_msg = _build_crate(crate_dir, crate_name)

    if success:
        # bd-91: No runtime reload - just log success
        # The crate is now in the environment but requires restart
        probe_name = crate_spec["probe"]
        is_available = _is_crate_installed(probe_name)
        if is_available:
            logger.debug("Crate %s built and is now available (restart to activate)", crate_name)
            return True
        else:
            logger.debug("Crate %s build succeeded but module not found in path", crate_name)
            return False
    else:
        logger.debug("Build error for %s: %s", crate_name, error_msg)
        return False
