"""Change tracker for incremental code intelligence.

Tracks file hashes to avoid reparsing unchanged files.
"""

import hashlib
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ChangeTracker:
    """Tracks file content hashes for incremental updates.

    Maintains a mapping of file paths to content hashes. Used by the
    symbol graph to determine which files need reparsing.

    Example:
        tracker = ChangeTracker()
        tracker.update_hash("/path/to/file.py", file_content)
        if tracker.has_changed("/path/to/file.py", new_content):
            # File changed, needs reparsing
            tracker.update_hash("/path/to/file.py", new_content)
    """

    def __init__(self):
        """Initialize an empty change tracker."""
        self._hashes: dict[str, str] = {}

    def compute_hash(self, content: str | bytes) -> str:
        """Compute xxhash of file content.

        Uses xxhash for fast non-cryptographic hashing.

        Args:
            content: File content as string or bytes.

        Returns:
            Hexadecimal hash string.
        """
        import xxhash

        if isinstance(content, str):
            content = content.encode("utf-8")
        return xxhash.xxh64(content).hexdigest()

    def get_hash(self, file_path: str | Path) -> Optional[str]:
        """Get stored hash for a file.

        Args:
            file_path: Path to the file.

        Returns:
            Stored hash or None if file not tracked.
        """
        key = str(Path(file_path).resolve())
        return self._hashes.get(key)

    def update_hash(self, file_path: str | Path, content: str | bytes) -> str:
        """Update stored hash for a file.

        Args:
            file_path: Path to the file.
            content: Current file content.

        Returns:
            The new hash value.
        """
        key = str(Path(file_path).resolve())
        new_hash = self.compute_hash(content)
        self._hashes[key] = new_hash
        logger.debug(f"Updated hash for {key}: {new_hash}")
        return new_hash

    def has_changed(self, file_path: str | Path, content: str | bytes) -> bool:
        """Check if file content has changed from stored hash.

        Args:
            file_path: Path to the file.
            content: Current file content to compare.

        Returns:
            True if file changed or not tracked, False otherwise.
        """
        key = str(Path(file_path).resolve())
        current_hash = self.compute_hash(content)
        stored_hash = self._hashes.get(key)

        if stored_hash is None:
            logger.debug(f"File not tracked, treating as changed: {key}")
            return True

        changed = stored_hash != current_hash
        if changed:
            logger.debug(f"File changed: {key}")
        return changed

    def remove_file(self, file_path: str | Path) -> bool:
        """Remove a file from tracking.

        Args:
            file_path: Path to the file.

        Returns:
            True if file was tracked and removed, False otherwise.
        """
        key = str(Path(file_path).resolve())
        if key in self._hashes:
            del self._hashes[key]
            logger.debug(f"Removed file from tracking: {key}")
            return True
        return False

    def get_tracked_files(self) -> set[str]:
        """Get set of all tracked file paths.

        Returns:
            Set of absolute file paths being tracked.
        """
        return set(self._hashes.keys())

    def clear(self) -> None:
        """Clear all tracked hashes."""
        self._hashes.clear()
        logger.debug("Cleared all tracked hashes")

    def get_stats(self) -> dict:
        """Get statistics about tracked files.

        Returns:
            Dict with count of tracked files.
        """
        return {
            "tracked_count": len(self._hashes),
        }
