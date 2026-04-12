"""Multi-crate Rust builder for Fast Puppy plugin.

This module provides generic auto-build functionality for all Rust crates
in the code_puppy workspace: code_puppy_core, turbo_ops, turbo_parse.
"""

import importlib
import importlib.util
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from code_puppy.config_package import get_puppy_config
from code_puppy.messaging import emit_info

logger = logging.getLogger(__name__)

# Registry of all Rust crates to auto-build
CRATES = [
    {
        "name": "code_puppy_core",
        "dir": "code_puppy_core",
        "probe": "_code_puppy_core",
        "bridges": ["code_puppy._core_bridge"],
        "patch_targets": [
            {
                "module": "code_puppy.agents.base_agent",
                "flags": {"RUST_AVAILABLE": "available"},
                "rebind_from": "code_puppy._core_bridge",
                "rebind_names": [],  # base_agent uses module-attribute lookup
            },
        ],
    },
    {
        "name": "turbo_ops",
        "dir": "turbo_ops",
        "probe": "turbo_ops",
        "bridges": [],
        "patch_targets": [
            {
                "module": "code_puppy.plugins.turbo_executor.orchestrator",
                "flags": {"TURBO_OPS_AVAILABLE": "available"},
                "rebind_from": "turbo_ops",
                "rebind_names": ["list_files", "grep", "read_file"],
                "rebind_as": {
                    "list_files": "turbo_list_files",
                    "grep": "turbo_grep",
                    "read_file": "turbo_read_file",
                },
            },
        ],
    },
    {
        "name": "turbo_parse",
        "dir": "turbo_parse",
        "probe": "turbo_parse",
        "bridges": ["code_puppy.turbo_parse_bridge"],
        "patch_targets": [
            {
                "module": "code_puppy.code_context.explorer",
                "flags": {"TURBO_PARSE_AVAILABLE": "available"},
                "rebind_from": "code_puppy.turbo_parse_bridge",
                "rebind_names": [
                    "is_language_supported",
                    "extract_symbols_from_file",
                ],
            },
            {
                "module": "code_puppy.plugins.turbo_parse.register_callbacks",
                "flags": {"TURBO_PARSE_AVAILABLE": "available"},
                "rebind_from": "code_puppy.turbo_parse_bridge",
                "rebind_names": [
                    "parse_source",
                    "parse_file",
                    "parse_files_batch",
                    "extract_symbols",
                    "extract_syntax_diagnostics",
                    "get_folds",
                    "get_highlights",
                    "is_language_supported",
                    "supported_languages",
                    "health_check",
                    "stats",
                ],
                "rebind_as": {
                    "parse_source": "_parse_source",
                    "parse_file": "_parse_file",
                    "parse_files_batch": "_parse_files_batch",
                    "extract_symbols": "_extract_symbols",
                    "extract_syntax_diagnostics": "_extract_diagnostics",
                    "get_folds": "_get_folds",
                    "get_highlights": "_get_highlights",
                },
            },
        ],
    },
]


def _find_repo_root() -> Path | None:
    """Find the repo root containing Cargo.toml workspace file.

    Searches in order:
    1. Development mode: traverse up from this file to find git checkout
    2. Wheel install: check if Cargo.toml is bundled with the package
    """
    # Strategy 1: Dev mode - traverse up from this file
    current = Path(__file__).resolve().parent
    for _ in range(5):
        if (current / "Cargo.toml").exists():
            try:
                content = (current / "Cargo.toml").read_text()
                if "[workspace]" in content:
                    return current
            except Exception:
                pass
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Strategy 2: Wheel install - Rust source bundled with package
    # The wheel includes Cargo.toml at the package root level
    try:
        import code_puppy

        pkg_root = Path(code_puppy.__file__).resolve().parent.parent
        cargo_path = pkg_root / "Cargo.toml"
        if cargo_path.exists():
            content = cargo_path.read_text()
            if "[workspace]" in content:
                return pkg_root
    except Exception:
        pass

    return None


def _find_crate_dir(crate_name: str) -> Path | None:
    """Find a specific crate directory relative to repo root."""
    repo_root = _find_repo_root()
    if repo_root is None:
        return None
    crate_dir = repo_root / crate_name
    if (crate_dir / "Cargo.toml").exists():
        return crate_dir
    return None


def _is_crate_installed(probe_module: str) -> bool:
    """Check if a crate's Python module is importable using importlib.util.find_spec."""
    try:
        spec = importlib.util.find_spec(probe_module)
        return spec is not None
    except Exception:
        return False


def _is_crate_fresh(crate_dir: Path, probe_module: str) -> bool:
    """Check if installed crate is fresh (binary mtime newer than all source files).

    Returns True if installed .so/.dylib mtime is newer than every source file.
    Checks Rust sources (.rs), tree-sitter queries (.scm), and config files.
    If not installed at all, returns False.
    """
    # Find the installed extension module
    try:
        spec = importlib.util.find_spec(probe_module)
        if spec is None or spec.origin is None:
            return False
        binary_path = Path(spec.origin)
        if not binary_path.exists():
            return False
        binary_mtime = binary_path.stat().st_mtime
    except Exception:
        return False

    # Collect all source files to check
    source_files: list[Path] = []

    # Rust sources in src/
    src_dir = crate_dir / "src"
    if src_dir.exists():
        source_files.extend(src_dir.rglob("*.rs"))

    # Tree-sitter queries (for turbo_parse)
    queries_dir = crate_dir / "queries"
    if queries_dir.exists():
        source_files.extend(queries_dir.rglob("*.scm"))

    # Build config files
    for name in ("Cargo.toml", "Cargo.lock", "pyproject.toml", "build.rs"):
        config_file = crate_dir / name
        if config_file.exists():
            source_files.append(config_file)

    # Check all collected sources
    try:
        for src_file in source_files:
            if src_file.stat().st_mtime > binary_mtime:
                return False  # Source is newer than binary
        return True
    except Exception:
        return False


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
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(crate_dir),
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


def _reload_and_patch_crate(crate_spec: dict) -> bool:
    """Reload bridge modules and patch consumer flags/function references.

    Args:
        crate_spec: The crate specification dict from CRATES.

    Returns:
        True if the probe module is now importable after reload.
    """
    import importlib
    import importlib.util
    import sys

    # 1. Reload all bridge modules
    for bridge_name in crate_spec.get("bridges", []):
        if bridge_name in sys.modules:
            try:
                importlib.reload(sys.modules[bridge_name])
                logger.debug("Reloaded bridge module %s", bridge_name)
            except Exception as e:
                logger.warning("Failed to reload bridge %s: %s", bridge_name, e)
        else:
            try:
                importlib.import_module(bridge_name)
            except Exception as e:
                logger.warning("Failed to import bridge %s: %s", bridge_name, e)

    # 2. Verify the probe module is now importable
    probe_name = crate_spec["probe"]
    try:
        # Use find_spec first (doesn't execute code, just finds the module)
        spec = importlib.util.find_spec(probe_name)
        if spec is None:
            is_available = False
        else:
            # Module exists, try to import/reload it
            if probe_name in sys.modules:
                try:
                    importlib.reload(sys.modules[probe_name])
                except Exception:
                    pass  # reload failed but spec exists, still available
            else:
                try:
                    importlib.import_module(probe_name)
                except Exception:
                    pass  # import failed but spec exists, still available
            is_available = True
    except Exception:
        is_available = False

    # 3. Patch each consumer module
    for target in crate_spec.get("patch_targets", []):
        module_name = target["module"]
        if module_name not in sys.modules:
            continue  # consumer not yet imported, nothing to patch
        consumer = sys.modules[module_name]

        # 3a. Patch flags
        for flag_name, value_source in target.get("flags", {}).items():
            if value_source == "available":
                value = is_available
            else:
                value = value_source
            try:
                setattr(consumer, flag_name, value)
                logger.debug("Patched %s.%s = %r", module_name, flag_name, value)
            except Exception as e:
                logger.warning("Failed to patch %s.%s: %s", module_name, flag_name, e)

        # 3b. Rebind function references from the fresh module
        rebind_from = target.get("rebind_from")
        rebind_names = target.get("rebind_names", [])
        rebind_as = target.get("rebind_as", {})

        if rebind_from and rebind_names and is_available:
            try:
                fresh_module = importlib.import_module(rebind_from)
            except ImportError as e:
                logger.warning("Cannot import %s for rebinding: %s", rebind_from, e)
                continue

            for fresh_name in rebind_names:
                local_name = rebind_as.get(fresh_name, fresh_name)
                try:
                    fresh_value = getattr(fresh_module, fresh_name)
                    setattr(consumer, local_name, fresh_value)
                    logger.debug(
                        "Rebound %s.%s = %s.%s",
                        module_name,
                        local_name,
                        rebind_from,
                        fresh_name,
                    )
                except AttributeError as e:
                    logger.warning(
                        "Cannot rebind %s.%s from %s: %s",
                        module_name,
                        local_name,
                        rebind_from,
                        e,
                    )

    return is_available


def _check_disable_autobuild() -> bool:
    """Check if rust autobuild is disabled in config."""
    try:
        cfg = get_puppy_config()
        return cfg.rust_autobuild_disabled
    except Exception:
        return False


def _try_auto_build_all() -> dict[str, bool]:
    """Attempt to auto-build all Rust crates if not installed/fresh.

    Returns dict of {crate_name: success_bool}.
    """
    results: dict[str, bool] = {}

    # Check config flag
    if _check_disable_autobuild():
        logger.debug("Rust autobuild disabled via config")
        return results

    # Check Rust toolchain once (fail fast)
    if not _has_rust_toolchain():
        emit_info("🐕 Fast Puppy: Rust toolchain not found — pure Python mode")
        return results

    # Check maturin availability, install if missing
    if not _has_maturin():
        emit_info("🐕⚡ Fast Puppy: Installing maturin…")
        install_ok, install_error = _install_maturin()
        if not install_ok:
            emit_info(
                "🐕 Fast Puppy: Could not install maturin — skipping Rust builds\n"
                f"   Error: {install_error[:150]}\n"
                "   To enable Rust acceleration:\n"
                "   • With uvx: uvx --from 'codepp[rust]' code-puppy\n"
                "   • With uv: uv pip install maturin\n"
                "   • With pip: pip install maturin\n"
                "   Then restart code-puppy or run /fast_puppy build"
            )
            return results

    # Find repo root
    repo_root = _find_repo_root()
    if repo_root is None:
        logger.debug("Could not find repo root with Cargo.toml")
        return results

    # Determine which crates need rebuilding
    crates_to_build = []
    for crate_spec in CRATES:
        crate_name = crate_spec["name"]
        probe = crate_spec["probe"]
        crate_dir = _find_crate_dir(crate_spec["dir"])

        if crate_dir is None:
            logger.debug("Crate dir not found for %s", crate_name)
            results[crate_name] = False
            continue

        if _is_crate_installed(probe) and _is_crate_fresh(crate_dir, probe):
            emit_info(f"🐕⚡ Fast Puppy: ✅ {crate_name}: already fresh")
            results[crate_name] = True
        else:
            crates_to_build.append(crate_spec)

    if not crates_to_build:
        return results

    # Prewarm workspace once before building (optimization)
    _prewarm_workspace(repo_root)

    # Build each crate that needs it
    for crate_spec in crates_to_build:
        crate_name = crate_spec["name"]
        probe = crate_spec["probe"]
        crate_dir = _find_crate_dir(crate_spec["dir"])

        if crate_dir is None:
            results[crate_name] = False
            continue

        emit_info(f"🐕⚡ Fast Puppy: 🔨 Building {crate_name}…")
        success, error_msg = _build_crate(crate_dir, crate_name)

        if success:
            # Reload and patch
            is_available = _reload_and_patch_crate(crate_spec)
            if is_available:
                emit_info(f"🐕⚡ Fast Puppy: ✅ {crate_name}: built and ready")
                results[crate_name] = True
            else:
                emit_info(
                    f"🐕 Fast Puppy: ⚠️ {crate_name}: build succeeded but module not loadable"
                )
                results[crate_name] = False
        else:
            emit_info(
                f"🐕 Fast Puppy: ❌ {crate_name}: build failed — {error_msg[:300]}"
            )
            logger.debug("Build error for %s: %s", crate_name, error_msg)
            results[crate_name] = False

    return results


def _try_auto_build() -> bool:
    """Legacy function for backward compatibility - builds only code_puppy_core.

    Returns True if code_puppy_core is available (either already installed or built).
    """
    results = _try_auto_build_all()
    return results.get("code_puppy_core", False)


def get_all_crate_status() -> list[dict]:
    """Return status dict for each crate in CRATES registry.

    Each dict has: name, installed, fresh, active, crate_dir_found.
    """
    statuses = []
    for crate_spec in CRATES:
        crate_name = crate_spec["name"]
        probe = crate_spec["probe"]
        crate_dir = _find_crate_dir(crate_spec["dir"])

        installed = _is_crate_installed(probe)
        fresh = False
        if installed and crate_dir is not None:
            fresh = _is_crate_fresh(crate_dir, probe)

        # Check if active (importable now)
        active = False
        try:
            importlib.import_module(probe)
            active = True
        except ImportError:
            pass

        statuses.append(
            {
                "name": crate_name,
                "installed": installed,
                "fresh": fresh,
                "active": active,
                "crate_dir_found": crate_dir is not None,
            }
        )

    return statuses


def build_single_crate(crate_name: str) -> bool:
    """Build one specific crate by name from the CRATES registry.

    Returns True on success, False otherwise.
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
        # Reload and patch
        is_available = _reload_and_patch_crate(crate_spec)
        if is_available:
            logger.debug("Crate %s built and is now available", crate_name)
            return True
        else:
            logger.debug("Crate %s build succeeded but module not loadable", crate_name)
            return False
    else:
        logger.debug("Build error for %s: %s", crate_name, error_msg)
        return False
