"""Multi-crate Rust builder for Fast Puppy plugin.

This module provides generic auto-build functionality for all Rust crates
in the code_puppy workspace: code_puppy_core, turbo_ops, turbo_parse.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

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
            ("code_puppy.agents.base_agent", "RUST_AVAILABLE"),
        ],
    },
    {
        "name": "turbo_ops",
        "dir": "turbo_ops",
        "probe": "turbo_ops",
        "bridges": [],
        "patch_targets": [
            ("code_puppy.plugins.turbo_executor.orchestrator", "TURBO_OPS_AVAILABLE"),
        ],
    },
    {
        "name": "turbo_parse",
        "dir": "turbo_parse",
        "probe": "turbo_parse",
        "bridges": ["code_puppy.turbo_parse_bridge"],
        "patch_targets": [
            ("code_puppy.code_context.explorer", "TURBO_PARSE_AVAILABLE"),
            ("code_puppy.plugins.turbo_parse.register_callbacks", "TURBO_PARSE_AVAILABLE"),
        ],
    },
]


def _find_repo_root() -> Path | None:
    """Find the repo root containing Cargo.toml workspace file."""
    # Start from this file's location and traverse up
    current = Path(__file__).resolve().parent
    for _ in range(5):  # Don't search too far
        if (current / "Cargo.toml").exists():
            # Verify it's a workspace by reading it
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
    """Check if installed crate is fresh (binary mtime newer than all .rs sources).

    Returns True if installed .so/.dylib mtime is newer than every .rs file
    in crate_dir/src/. If not installed at all, returns False.
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

    # Check all .rs files in src/ directory
    src_dir = crate_dir / "src"
    if not src_dir.exists():
        return False

    try:
        for rs_file in src_dir.rglob("*.rs"):
            if rs_file.stat().st_mtime > binary_mtime:
                return False  # Source is newer than binary
        return True
    except Exception:
        return False


def _has_rust_toolchain() -> bool:
    """Check if Rust compiler is available."""
    return shutil.which("rustc") is not None


def _has_maturin() -> bool:
    """Check if maturin is available (in PATH, as uv module, or as Python module)."""
    if shutil.which("maturin"):
        return True
    if shutil.which("uv"):
        # Check if uv can run maturin
        try:
            result = subprocess.run(
                ["uv", "run", "maturin", "--version"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            pass
    # Try as Python module
    try:
        result = subprocess.run(
            [sys.executable, "-m", "maturin", "--version"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _install_maturin() -> bool:
    """Try to install maturin using pip."""
    try:
        install_result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "maturin"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return install_result.returncode == 0
    except Exception as exc:
        logger.debug("Could not install maturin: %s", exc)
        return False


def _get_maturin_command() -> list[str]:
    """Get the appropriate maturin command as a list."""
    if shutil.which("maturin"):
        return ["maturin"]
    if shutil.which("uv"):
        return ["uv", "run", "maturin"]
    return [sys.executable, "-m", "maturin"]


def _emit_build_heartbeat(proc: subprocess.Popen, crate_name: str, stop_event: threading.Event) -> None:
    """Emit heartbeat messages during long builds.

    Runs in a daemon thread, emits message every 20 seconds.
    """
    start_time = time.time()
    next_heartbeat = 20.0

    while not stop_event.is_set() and proc.poll() is None:
        elapsed = time.time() - start_time
        if elapsed >= next_heartbeat:
            emit_info(f"🐕⚡ Fast Puppy: Still building {crate_name}… ({int(elapsed)}s elapsed)")
            next_heartbeat += 20.0
        time.sleep(1.0)


def _build_crate(crate_dir: Path, crate_name: str) -> tuple[bool, str]:
    """Build and install a Rust crate into the current environment.

    Returns (success, error_msg).
    Uses 600 second timeout (turbo_parse is slow).
    """
    cmd_base = _get_maturin_command()
    cmd = cmd_base + [
        "develop",
        "--release",
        "--manifest-path",
        str(crate_dir / "Cargo.toml"),
    ]

    try:
        # Use Popen for heartbeat support on long builds
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(crate_dir),
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
            error_msg = stderr.strip() if stderr else stdout.strip() if stdout else "Unknown error"
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
        )
        if result.returncode == 0:
            logger.debug("Workspace prewarm completed successfully")
    except Exception as e:
        logger.debug("Workspace prewarm failed (non-fatal): %s", e)


def _reload_and_patch_crate(crate_spec: dict) -> bool:
    """Reload bridge modules and patch availability flags after a build.

    Args:
        crate_spec: The crate specification dict from CRATES.

    Returns:
        True if the crate is now importable after reload.
    """
    probe_module = crate_spec["probe"]
    bridges = crate_spec.get("bridges", [])
    patch_targets = crate_spec.get("patch_targets", [])

    # First, check if it's now importable
    try:
        importlib.import_module(probe_module)
        is_available = True
    except ImportError:
        is_available = False

    # Reload all bridge modules
    for bridge_module in bridges:
        try:
            mod = importlib.import_module(bridge_module)
            importlib.reload(mod)
        except Exception as e:
            logger.debug("Failed to reload bridge %s: %s", bridge_module, e)

    # Patch the patch_targets with fresh availability
    for module_name, attr_name in patch_targets:
        try:
            mod = importlib.import_module(module_name)
            setattr(mod, attr_name, is_available)
        except Exception as e:
            logger.debug("Failed to patch %s.%s: %s", module_name, attr_name, e)

    return is_available


def _check_disable_autobuild() -> bool:
    """Check if rust autobuild is disabled in config."""
    try:
        from code_puppy.config import get_value
        val = get_value("disable_rust_autobuild")
        return str(val).strip().lower() in {"1", "true", "yes", "on"}
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
        if not _install_maturin():
            emit_info("🐕 Fast Puppy: Could not install maturin — skipping Rust builds")
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
                emit_info(f"🐕 Fast Puppy: ⚠️ {crate_name}: build succeeded but module not loadable")
                results[crate_name] = False
        else:
            emit_info(f"🐕 Fast Puppy: ❌ {crate_name}: build failed — {error_msg[:100]}")
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

        statuses.append({
            "name": crate_name,
            "installed": installed,
            "fresh": fresh,
            "active": active,
            "crate_dir_found": crate_dir is not None,
        })

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
        if not _install_maturin():
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
