"""Version checking utilities for Fast Puppy."""

from __future__ import annotations

import httpx

from code_puppy.messaging import emit_info, emit_success, emit_warning, get_message_bus
from code_puppy.messaging.messages import VersionCheckMessage


def normalize_version(version_str):
    if not version_str:
        return version_str
    version_str = version_str.lstrip("v")
    return version_str


def _version_tuple(version_str):
    """Convert version string to tuple of ints for proper comparison."""
    try:
        return tuple(int(x) for x in version_str.split("."))
    except ValueError, AttributeError:
        return None


def version_is_newer(latest, current):
    """Return True if latest version is strictly newer than current."""
    latest_tuple = _version_tuple(normalize_version(latest))
    current_tuple = _version_tuple(normalize_version(current))
    if latest_tuple is None or current_tuple is None:
        return False
    return latest_tuple > current_tuple


def versions_are_equal(current, latest):
    current_norm = normalize_version(current)
    latest_norm = normalize_version(latest)
    # Try numeric tuple comparison first
    current_tuple = _version_tuple(current_norm)
    latest_tuple = _version_tuple(latest_norm)
    if current_tuple is not None and latest_tuple is not None:
        return current_tuple == latest_tuple
    # Fallback to string comparison
    return current_norm == latest_norm


def fetch_latest_version(package_name):
    try:
        response = httpx.get(f"https://pypi.org/pypi/{package_name}/json", timeout=5.0)
        response.raise_for_status()
        data = response.json()
        return data["info"]["version"]
    except Exception as e:
        emit_warning(f"Error fetching version: {e}")
        return None


def default_version_mismatch_behavior(current_version):
    # Defensive: ensure current_version is never None
    if current_version is None:
        current_version = "0.0.0-unknown"
        emit_warning("Could not detect current version, using fallback")

    latest_version = fetch_latest_version("fast-puppy")

    update_available = bool(
        latest_version and version_is_newer(latest_version, current_version)
    )

    # Emit structured version check message
    version_msg = VersionCheckMessage(
        current_version=current_version,
        latest_version=latest_version or current_version,
        update_available=update_available,
    )
    get_message_bus().emit(version_msg)

    # Also emit plain text for legacy renderer
    emit_info(f"Current version: {current_version}")

    if update_available:
        emit_info(f"Latest version: {latest_version}")
        emit_warning(f"A new version of code puppy is available: {latest_version}")
        emit_success("Please consider updating!")


def check_latest_version_in_background(current_version) -> None:
    """Run the version check in a daemon thread so PyPI never blocks startup.

    ``fetch_latest_version`` does a blocking ``httpx.get`` with a 5s timeout.
    Called inline on the async startup path it freezes the interactive prompt
    for up to 5s on every launch when the network is slow or PyPI is down.
    Mirroring ``models_dev_parser.prefetch_models_dev``, we move it off the
    critical path; the version banner just appears a moment later. Output
    goes through the (thread-safe) message bus.
    """
    import threading

    threading.Thread(
        target=default_version_mismatch_behavior,
        args=(current_version,),
        name="version-check",
        daemon=True,
    ).start()
