"""DuckDB connection and operations for analytics.

Manages the DuckDB database connection and provides operations for
storing and querying analytics data.
"""

import logging
import threading
from pathlib import Path
from typing import Any

try:
    import duckdb

    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False
    duckdb = None  # type: ignore

from code_puppy.config import DATA_DIR

from .schema import CREATE_TABLES_SQL

logger = logging.getLogger(__name__)

# Database path
DB_PATH = Path(DATA_DIR) / "analytics.duckdb"

# Thread-local storage for connections
_local = threading.local()

# Global lock for initialization
_init_lock = threading.Lock()
_db_initialized = False


def _get_connection() -> Any:
    """Get a DuckDB connection for the current thread."""
    if not DUCKDB_AVAILABLE:
        return None

    if not hasattr(_local, "conn") or _local.conn is None:
        try:
            # Ensure parent directory exists
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _local.conn = duckdb.connect(str(DB_PATH))
        except Exception as e:
            logger.warning(f"Failed to connect to analytics database: {e}")
            _local.conn = None
            return None

    return _local.conn


def _initialize_db() -> bool:
    """Initialize the database schema. Thread-safe, runs only once."""
    global _db_initialized

    if _db_initialized:
        return True

    with _init_lock:
        if _db_initialized:
            return True

        conn = _get_connection()
        if conn is None:
            return False

        try:
            # Execute each CREATE statement separately
            for statement in CREATE_TABLES_SQL.split(';'):
                statement = statement.strip()
                if statement:
                    conn.execute(statement)
            _db_initialized = True
            logger.debug("Analytics database initialized successfully")
            return True
        except Exception as e:
            logger.warning(f"Failed to initialize analytics database: {e}")
            return False


def _ensure_initialized(func):
    """Decorator to ensure database is initialized before operation."""

    def wrapper(*args, **kwargs):
        if not _initialize_db():
            return None
        return func(*args, **kwargs)

    return wrapper


@_ensure_initialized
def record_turn_start(
    session_id: str | None,
    agent_name: str,
    model_name: str,
) -> int | None:
    """Record the start of a turn. Returns turn_id or None on failure."""
    conn = _get_connection()
    if conn is None:
        return None

    try:
        result = conn.execute(
            """
            INSERT INTO turns (session_id, agent_name, model_name)
            VALUES (?, ?, ?)
            RETURNING turn_id
            """,
            [session_id, agent_name, model_name],
        ).fetchone()
        conn.commit()
        return result[0] if result else None
    except Exception as e:
        logger.debug(f"Failed to record turn start: {e}")
        return None


@_ensure_initialized
def record_turn_end(
    turn_id: int,
    success: bool,
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: int | None = None,
    error: str | None = None,
) -> bool:
    """Record the end of a turn."""
    conn = _get_connection()
    if conn is None:
        return False

    try:
        conn.execute(
            """
            UPDATE turns
            SET ended_at = CURRENT_TIMESTAMP,
                success = ?,
                input_tokens = ?,
                output_tokens = ?,
                duration_ms = ?,
                error = ?
            WHERE turn_id = ?
            """,
            [success, input_tokens, output_tokens, duration_ms, error, turn_id],
        )
        conn.commit()
        return True
    except Exception as e:
        logger.debug(f"Failed to record turn end: {e}")
        return False


@_ensure_initialized
def record_tool_call(
    turn_id: int | None,
    tool_name: str,
    duration_ms: int | None = None,
    success: bool = True,
    error: str | None = None,
) -> int | None:
    """Record a tool call. Returns call_id or None on failure."""
    conn = _get_connection()
    if conn is None:
        return None

    try:
        result = conn.execute(
            """
            INSERT INTO tool_calls (turn_id, tool_name, duration_ms, success, error)
            VALUES (?, ?, ?, ?, ?)
            RETURNING call_id
            """,
            [turn_id, tool_name, duration_ms, success, error],
        ).fetchone()
        conn.commit()
        return result[0] if result else None
    except Exception as e:
        logger.debug(f"Failed to record tool call: {e}")
        return None


@_ensure_initialized
def record_file_access(
    turn_id: int | None,
    tool_name: str,
    file_path: str,
    operation: str,
) -> bool:
    """Record a file access."""
    conn = _get_connection()
    if conn is None:
        return False

    try:
        conn.execute(
            """
            INSERT INTO file_accesses (turn_id, tool_name, file_path, operation)
            VALUES (?, ?, ?, ?)
            """,
            [turn_id, tool_name, file_path, operation],
        )
        conn.commit()
        return True
    except Exception as e:
        logger.debug(f"Failed to record file access: {e}")
        return False


def close_connection() -> None:
    """Close the database connection for the current thread."""
    if hasattr(_local, "conn") and _local.conn is not None:
        try:
            _local.conn.close()
        except Exception:
            pass
        _local.conn = None
