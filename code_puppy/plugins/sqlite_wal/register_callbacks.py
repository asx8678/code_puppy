"""SQLite WAL mode plugin for DBOS database.

Enables Write-Ahead Logging (WAL) mode on the DBOS SQLite database at startup
for better concurrency and performance.
"""

import os
import sqlite3
from pathlib import Path

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info


def _on_startup():
    """Enable WAL mode on the DBOS SQLite database at startup."""
    # Get the database path from environment or use default
    db_url = os.environ.get("DBOS_SYSTEM_DATABASE_URL", "")

    # Extract the SQLite file path from the URL
    sqlite_file = None
    if db_url.startswith("sqlite:///"):
        # sqlite:///path/to/db or sqlite:////absolute/path/to/db
        sqlite_file = db_url[10:]
    elif db_url:
        # Non-SQLite database URL (PostgreSQL, etc.) - skip WAL setup
        return

    # Default to ~/.code_puppy/dbos_store.sqlite if no env var set
    if sqlite_file is None:
        data_dir = Path.home() / ".code_puppy"
        sqlite_file = data_dir / "dbos_store.sqlite"
    else:
        sqlite_file = Path(sqlite_file)

    # Handle missing database gracefully - if it doesn't exist yet, skip
    # DBOS will create it later and we can rely on DBOS defaults
    if not sqlite_file.exists():
        return

    try:
        conn = sqlite3.connect(str(sqlite_file), timeout=10.0)
        try:
            cursor = conn.cursor()

            # Enable WAL mode for better concurrency
            cursor.execute("PRAGMA journal_mode=WAL")
            journal_mode = cursor.fetchone()

            # Set synchronous to NORMAL for balanced safety/performance
            cursor.execute("PRAGMA synchronous=NORMAL")

            # Set busy timeout to 5000ms (5 seconds) to handle concurrent access
            cursor.execute("PRAGMA busy_timeout=5000")

            conn.commit()

            if journal_mode and journal_mode[0] == "wal":
                emit_info(f"SQLite WAL mode enabled for DBOS database: {sqlite_file}")
        finally:
            conn.close()
    except sqlite3.Error:
        # Silently ignore SQLite errors - DBOS will handle its own database
        pass


register_callback("startup", _on_startup)
