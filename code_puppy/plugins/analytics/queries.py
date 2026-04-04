"""Analytics queries for DuckDB.

Provides functions to query and aggregate analytics data.
"""

import logging
from typing import Any

from .db import _ensure_initialized, _get_connection

logger = logging.getLogger(__name__)


def _execute_query(sql: str, params: list | None = None) -> list[dict] | None:
    """Execute a query and return results as list of dicts."""
    conn = _get_connection()
    if conn is None:
        return None

    try:
        result = conn.execute(sql, params or []).fetchall()
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in result]
    except Exception as e:
        logger.debug(f"Query failed: {e}")
        return None


@_ensure_initialized
def get_token_stats(days: int = 7) -> dict[str, Any] | None:
    """Get token usage statistics for the last N days."""
    sql = f"""
        SELECT
            COUNT(*) as total_turns,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(input_tokens + output_tokens) as total_tokens,
            AVG(input_tokens) as avg_input_tokens,
            AVG(output_tokens) as avg_output_tokens,
            MAX(input_tokens) as max_input_tokens,
            MAX(output_tokens) as max_output_tokens
        FROM turns
        WHERE started_at >= CURRENT_DATE - INTERVAL '{days} days'
        AND input_tokens IS NOT NULL
    """
    result = _execute_query(sql)
    return result[0] if result else None


@_ensure_initialized
def get_token_stats_by_model(days: int = 7) -> list[dict] | None:
    """Get token usage statistics grouped by model."""
    sql = f"""
        SELECT
            model_name,
            COUNT(*) as turns,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(input_tokens + output_tokens) as total_tokens,
            AVG(input_tokens + output_tokens) as avg_tokens_per_turn
        FROM turns
        WHERE started_at >= CURRENT_DATE - INTERVAL '{days} days'
        AND input_tokens IS NOT NULL
        GROUP BY model_name
        ORDER BY total_tokens DESC
    """
    return _execute_query(sql)


@_ensure_initialized
def get_latency_stats(days: int = 7) -> dict[str, Any] | None:
    """Get response time statistics for the last N days."""
    sql = f"""
        SELECT
            COUNT(*) as total_turns,
            AVG(duration_ms) as avg_duration_ms,
            MIN(duration_ms) as min_duration_ms,
            MAX(duration_ms) as max_duration_ms,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms) as p50_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_ms,
            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) as p99_ms
        FROM turns
        WHERE started_at >= CURRENT_DATE - INTERVAL '{days} days'
        AND duration_ms IS NOT NULL
    """
    result = _execute_query(sql)
    return result[0] if result else None


@_ensure_initialized
def get_latency_by_model(days: int = 7) -> list[dict] | None:
    """Get latency statistics grouped by model."""
    sql = f"""
        SELECT
            model_name,
            COUNT(*) as turns,
            AVG(duration_ms) as avg_ms,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms) as p50_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_ms,
            MAX(duration_ms) as max_ms
        FROM turns
        WHERE started_at >= CURRENT_DATE - INTERVAL '{days} days'
        AND duration_ms IS NOT NULL
        GROUP BY model_name
        ORDER BY avg_ms DESC
    """
    return _execute_query(sql)


@_ensure_initialized
def get_tool_usage_stats(days: int = 7, limit: int = 20) -> list[dict] | None:
    """Get tool usage frequency statistics."""
    sql = f"""
        SELECT
            tool_name,
            COUNT(*) as call_count,
            AVG(duration_ms) as avg_duration_ms,
            SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
            SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as error_count,
            100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*) as success_rate
        FROM tool_calls
        WHERE started_at >= CURRENT_DATE - INTERVAL '{days} days'
        GROUP BY tool_name
        ORDER BY call_count DESC
        LIMIT {limit}
    """
    return _execute_query(sql)


@_ensure_initialized
def get_file_access_patterns(days: int = 7, limit: int = 20) -> list[dict] | None:
    """Get file access pattern statistics."""
    sql = f"""
        SELECT
            file_path,
            COUNT(*) as access_count,
            COUNT(DISTINCT turn_id) as unique_turns,
            STRING_AGG(DISTINCT operation, ', ') as operations
        FROM file_accesses
        WHERE accessed_at >= CURRENT_DATE - INTERVAL '{days} days'
        GROUP BY file_path
        ORDER BY access_count DESC
        LIMIT {limit}
    """
    return _execute_query(sql)


@_ensure_initialized
def get_top_models(days: int = 7, limit: int = 10) -> list[dict] | None:
    """Get most used models."""
    sql = f"""
        SELECT
            model_name,
            COUNT(*) as turns,
            SUM(input_tokens + output_tokens) as total_tokens,
            AVG(duration_ms) as avg_duration_ms,
            100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*) as success_rate
        FROM turns
        WHERE started_at >= CURRENT_DATE - INTERVAL '{days} days'
        GROUP BY model_name
        ORDER BY turns DESC
        LIMIT {limit}
    """
    return _execute_query(sql)


@_ensure_initialized
def get_top_tools(days: int = 7, limit: int = 10) -> list[dict] | None:
    """Get most used tools."""
    sql = f"""
        SELECT
            tc.tool_name,
            COUNT(*) as call_count,
            COUNT(DISTINCT tc.turn_id) as unique_turns,
            AVG(tc.duration_ms) as avg_duration_ms,
            100.0 * SUM(CASE WHEN tc.success THEN 1 ELSE 0 END) / COUNT(*) as success_rate
        FROM tool_calls tc
        WHERE tc.started_at >= CURRENT_DATE - INTERVAL '{days} days'
        GROUP BY tc.tool_name
        ORDER BY call_count DESC
        LIMIT {limit}
    """
    return _execute_query(sql)


@_ensure_initialized
def get_daily_summary(days: int = 7) -> list[dict] | None:
    """Get daily summary statistics."""
    sql = f"""
        SELECT
            DATE(started_at) as date,
            COUNT(*) as turns,
            COUNT(DISTINCT model_name) as models_used,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            AVG(duration_ms) as avg_duration_ms
        FROM turns
        WHERE started_at >= CURRENT_DATE - INTERVAL '{days} days'
        GROUP BY DATE(started_at)
        ORDER BY date DESC
    """
    return _execute_query(sql)


@_ensure_initialized
def get_summary() -> dict[str, Any] | None:
    """Get overall summary statistics."""
    sql = """
        SELECT
            (SELECT COUNT(*) FROM turns) as total_turns,
            (SELECT COUNT(*) FROM tool_calls) as total_tool_calls,
            (SELECT COUNT(*) FROM file_accesses) as total_file_accesses,
            (SELECT COUNT(DISTINCT model_name) FROM turns) as unique_models,
            (SELECT COUNT(DISTINCT agent_name) FROM turns) as unique_agents,
            (SELECT MIN(started_at) FROM turns) as first_turn,
            (SELECT MAX(started_at) FROM turns) as last_turn
    """
    result = _execute_query(sql)
    return result[0] if result else None
