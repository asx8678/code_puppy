"""Discovery functions for Fast Puppy plugin.

This module provides discovery and status-checking functionality for Rust crates
in the code_puppy workspace: code_puppy_core, turbo_parse.

Note:
    Build-related functionality has been moved to rust_builder.py.
    This module is for discovery-only operations.

    bd-91: Auto-build functionality was removed. Fast Puppy now operates
    as a runtime selector rather than a crate manager.

See Also:
    rust_builder.py - For building crates via /fast_puppy build command.
"""

import importlib
import importlib.util
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Registry of all Rust crates
# bd-63: Removed patch_targets - NativeBackend handles capability routing
CRATES = [
    {
        "name": "code_puppy_core",
        "dir": "code_puppy_core",
        "probe": "_code_puppy_core",
        "bridges": ["code_puppy._core_bridge"],
        # No patch_targets - NativeBackend handles routing
    },
    {
        "name": "turbo_parse",
        "dir": "turbo_parse",
        "probe": "turbo_parse",
        "bridges": [],  # bd-31: turbo_parse_bridge removed; NativeBackend handles routing
        # No patch_targets - NativeBackend handles routing
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


# bd-91: Runtime backend detection without building
def get_available_backends() -> dict[str, bool]:
    """Detect available backends without triggering any builds.

    Returns a dict with:
        - elixir_available: True if Elixir bridge is connected
        - rust_installed: True if Rust crates are installed (not built, just checked)
        - python_fallback: Always True (Python is always available as fallback)

    This function is used during startup to show backend status without
    the performance penalty of auto-building Rust crates.
    """
    status: dict[str, bool] = {
        "elixir_available": False,
        "rust_installed": False,
        "python_fallback": True,
    }

    # Check if Elixir bridge is connected
    try:
        from code_puppy.native_backend import NativeBackend

        cap_status = NativeBackend.get_status()
        # Elixir is available if any capability is active (meaning bridge is connected)
        status["elixir_available"] = any(info.active for info in cap_status.values())
    except Exception:
        status["elixir_available"] = False

    # Check if Rust crates are installed (without building)
    rust_count = 0
    for crate_spec in CRATES:
        probe = crate_spec["probe"]
        if _is_crate_installed(probe):
            rust_count += 1
    # Consider Rust "installed" if at least one crate is available
    status["rust_installed"] = rust_count > 0

    # Python fallback is always available
    status["python_fallback"] = True

    return status
