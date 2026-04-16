"""Bridge to Rust PathClassifier with Python fallback.

This module provides transparent routing for path classification operations:
- should_ignore_path: Check if a path should be ignored
- should_ignore_dir_path: Check if a directory path should be ignored
- is_sensitive_path: Check if a path is sensitive (credentials, keys, etc.)
- classify_path: Classify a path, returning (is_ignored, is_sensitive)

When the Rust extension _code_puppy_core is available, all operations
are routed through the native PathClassifier for maximum performance.
When unavailable, the bridge falls back to the Python implementations.
"""

try:
    from _code_puppy_core import PathClassifier as _RustPathClassifier

    _classifier = _RustPathClassifier()
    RUST_AVAILABLE = True
except ImportError:
    _classifier = None
    RUST_AVAILABLE = False


def should_ignore_path(path: str) -> bool:
    """Return True if path matches any ignore pattern.

    Uses Rust PathClassifier when available, otherwise falls back to
    the Python implementation in code_puppy.tools.common.

    Args:
        path: Path to check (may be relative, absolute, or contain ~).

    Returns:
        True if path should be ignored.
    """
    if RUST_AVAILABLE:
        return _classifier.py_should_ignore(path)
    from code_puppy.tools.common import should_ignore_path as _py_impl

    return _py_impl(path)


def should_ignore_dir_path(path: str) -> bool:
    """Return True if directory path matches any directory ignore pattern.

    Uses Rust PathClassifier when available, otherwise falls back to
    the Python implementation in code_puppy.tools.common.

    Args:
        path: Directory path to check.

    Returns:
        True if directory path should be ignored.
    """
    if RUST_AVAILABLE:
        return _classifier.py_should_ignore_dir(path)
    from code_puppy.tools.common import should_ignore_dir_path as _py_impl

    return _py_impl(path)


def is_sensitive_path(path: str) -> bool:
    """Return True if path points to sensitive credentials/keys.

    Uses Rust PathClassifier when available, otherwise falls back to
    the Python implementation in code_puppy.sensitive_paths.

    Args:
        path: Path to check (may be relative, absolute, or contain ~).

    Returns:
        True if path is sensitive and should be blocked.
    """
    if RUST_AVAILABLE:
        return _classifier.py_is_sensitive(path)
    from code_puppy.sensitive_paths import is_sensitive_path as _py_impl

    return _py_impl(path)


def classify_path(path: str) -> tuple[bool, bool]:
    """Classify a path, returning (is_ignored, is_sensitive).

    Uses Rust PathClassifier when available (via a single call that
    returns both values), otherwise falls back to calling the individual
    Python implementations.

    Args:
        path: Path to classify.

    Returns:
        Tuple of (should_ignore, is_sensitive).
    """
    if RUST_AVAILABLE:
        return _classifier.py_classify_path(path)
    return (should_ignore_path(path), is_sensitive_path(path))
