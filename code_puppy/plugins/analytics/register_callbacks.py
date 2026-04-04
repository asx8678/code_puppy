"""Analytics plugin for Code Puppy CLI.

Stores usage data in DuckDB and provides an /analytics command for querying.
"""

import logging
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info

from .db import (
    DUCKDB_AVAILABLE,
    record_file_access,
    record_tool_call,
    record_turn_end,
    record_turn_start,
)
from .queries import (
    get_daily_summary,
    get_file_access_patterns,
    get_latency_by_model,
    get_latency_stats,
    get_summary,
    get_token_stats,
    get_token_stats_by_model,
    get_top_models,
    get_top_tools,
    get_tool_usage_stats,
)

logger = logging.getLogger(__name__)

# Track current turn ID per session (stored in run context or module level)
_current_turn_id: dict[str, int | None] = {}


# ---------------------------------------------------------------------------
# Callback Handlers
# ---------------------------------------------------------------------------


def _on_agent_run_start(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
) -> None:
    """Record the start of an agent run."""
    if not DUCKDB_AVAILABLE:
        return

    turn_id = record_turn_start(session_id, agent_name, model_name)
    if turn_id is not None:
        _current_turn_id[session_id or "default"] = turn_id
        logger.debug(f"Recorded turn start: {turn_id} for {agent_name}/{model_name}")


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Record the end of an agent run."""
    if not DUCKDB_AVAILABLE:
        return

    key = session_id or "default"
    turn_id = _current_turn_id.pop(key, None)

    if turn_id is None:
        return

    # Extract token counts from metadata
    input_tokens = 0
    output_tokens = 0
    duration_ms = None

    if metadata:
        input_tokens = metadata.get("input_tokens", metadata.get("prompt_tokens", 0))
        output_tokens = metadata.get(
            "output_tokens", metadata.get("completion_tokens", 0)
        )
        # Try to get duration from metadata if available
        duration_ms = metadata.get("duration_ms")

    error_str = str(error) if error else None

    record_turn_end(
        turn_id=turn_id,
        success=success,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        error=error_str,
    )
    logger.debug(f"Recorded turn end: {turn_id}")


async def _on_pre_tool_call(
    tool_name: str,
    tool_args: dict,
    context: Any = None,
) -> None:
    """Track file access patterns from file operations."""
    if not DUCKDB_AVAILABLE:
        return None

    # Track file operations
    file_ops = {
        "read_file": ("file_path", "read"),
        "create_file": ("file_path", "write"),
        "replace_in_file": ("file_path", "write"),
        "delete_file": ("file_path", "delete"),
        "delete_snippet": ("file_path", "write"),
        "list_files": ("directory", "list"),
        "grep": ("directory", "search"),
        "cp_list_files": ("directory", "list"),
        "cp_read_file": ("file_path", "read"),
        "cp_grep": ("directory", "search"),
    }

    if tool_name in file_ops:
        arg_key, operation = file_ops[tool_name]
        file_path = tool_args.get(arg_key, "unknown")

        # Get current turn_id
        turn_id = _current_turn_id.get(context.get("session_id") if isinstance(context, dict) else None)
        if turn_id is None:
            turn_id = _current_turn_id.get("default")

        record_file_access(turn_id, tool_name, file_path, operation)

    return None


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> None:
    """Record tool call completion."""
    if not DUCKDB_AVAILABLE:
        return

    # Get current turn_id
    session_id = context.get("session_id") if isinstance(context, dict) else None
    turn_id = _current_turn_id.get(session_id or "default")

    # Determine success from result
    success = True
    error = None
    if isinstance(result, dict):
        success = not result.get("error", False)
        if "error" in result:
            error = str(result["error"])
    elif result is None:
        success = False
        error = "No result"

    record_tool_call(
        turn_id=turn_id,
        tool_name=tool_name,
        duration_ms=int(duration_ms),
        success=success,
        error=error,
    )
    logger.debug(f"Recorded tool call: {tool_name} ({duration_ms:.0f}ms)")


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------


def _analytics_help():
    """Return help entries for the /analytics command."""
    return [
        ("analytics", "Show analytics dashboard or usage: /analytics [subcommand]"),
        ("analytics tokens", "Token usage statistics"),
        ("analytics latency", "Response time statistics"),
        ("analytics tools", "Tool usage frequency"),
        ("analytics files", "File access patterns"),
        ("analytics top", "Most used models and tools"),
        ("analytics daily", "Daily summary statistics"),
        ("analytics summary", "Overall summary"),
    ]


def _format_number(value, decimals: int = 0) -> str:
    """Format a number for display."""
    if value is None:
        return "N/A"
    if decimals == 0:
        return f"{int(value):,}"
    return f"{value:,.{decimals}f}"


def _format_ms(ms: float | None) -> str:
    """Format milliseconds for display."""
    if ms is None:
        return "N/A"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms/1000:.1f}s"


def _handle_analytics_command(command: str, name: str) -> bool | None:
    """Handle /analytics command and subcommands."""
    if name != "analytics":
        return None

    if not DUCKDB_AVAILABLE:
        emit_info("⚠️  DuckDB not available. Install with: uv add duckdb")
        return True

    # Parse subcommand
    parts = command.split()
    subcommand = parts[1] if len(parts) > 1 else "dashboard"
    days = 7  # Default lookback period

    # Extract days argument if provided (--days N)
    for i, part in enumerate(parts):
        if part == "--days" and i + 1 < len(parts):
            try:
                days = int(parts[i + 1])
            except ValueError:
                pass

    try:
        if subcommand == "tokens":
            _show_token_stats(days)
        elif subcommand == "latency":
            _show_latency_stats(days)
        elif subcommand == "tools":
            _show_tool_stats(days)
        elif subcommand == "files":
            _show_file_stats(days)
        elif subcommand == "top":
            _show_top_stats(days)
        elif subcommand == "daily":
            _show_daily_summary(days)
        elif subcommand == "summary":
            _show_summary()
        else:
            # Default dashboard
            _show_dashboard(days)
    except Exception as e:
        emit_info(f"⚠️  Error retrieving analytics: {e}")

    return True


def _show_token_stats(days: int) -> None:
    """Display token usage statistics."""
    stats = get_token_stats(days)
    by_model = get_token_stats_by_model(days)

    if not stats:
        emit_info("📊 No token data available")
        return

    emit_info(f"📊 Token Usage (last {days} days)")
    emit_info("")
    emit_info(f"  Total turns:     {_format_number(stats.get('total_turns'))}")
    emit_info(f"  Input tokens:    {_format_number(stats.get('total_input_tokens'))}")
    emit_info(f"  Output tokens:   {_format_number(stats.get('total_output_tokens'))}")
    emit_info(f"  Total tokens:    {_format_number(stats.get('total_tokens'))}")
    emit_info(f"  Avg per turn:    {_format_number(stats.get('avg_input_tokens', 0) + stats.get('avg_output_tokens', 0), 0)}")
    emit_info("")

    if by_model:
        emit_info("  By Model:")
        for model in by_model[:5]:
            name = model.get("model_name", "unknown")[:20]
            tokens = model.get("total_tokens", 0)
            turns = model.get("turns", 0)
            emit_info(f"    {name:20} {_format_number(tokens):>12} tokens ({turns} turns)")


def _show_latency_stats(days: int) -> None:
    """Display latency statistics."""
    stats = get_latency_stats(days)
    by_model = get_latency_by_model(days)

    if not stats or not stats.get("total_turns"):
        emit_info("📊 No latency data available")
        return

    emit_info(f"⏱️  Response Time (last {days} days)")
    emit_info("")
    emit_info(f"  Total turns:  {_format_number(stats.get('total_turns'))}")
    emit_info(f"  Average:      {_format_ms(stats.get('avg_duration_ms'))}")
    emit_info(f"  P50 (median): {_format_ms(stats.get('p50_ms'))}")
    emit_info(f"  P95:          {_format_ms(stats.get('p95_ms'))}")
    emit_info(f"  P99:          {_format_ms(stats.get('p99_ms'))}")
    emit_info(f"  Range:        {_format_ms(stats.get('min_duration_ms'))} - {_format_ms(stats.get('max_duration_ms'))}")
    emit_info("")

    if by_model:
        emit_info("  By Model:")
        for model in by_model[:5]:
            name = model.get("model_name", "unknown")[:20]
            avg = model.get("avg_ms")
            p95 = model.get("p95_ms")
            emit_info(f"    {name:20} avg: {_format_ms(avg):>10} p95: {_format_ms(p95):>10}")


def _show_tool_stats(days: int) -> None:
    """Display tool usage statistics."""
    stats = get_tool_usage_stats(days)

    if not stats:
        emit_info("📊 No tool usage data available")
        return

    emit_info(f"🛠️  Tool Usage (last {days} days)")
    emit_info("")
    emit_info(f"  {'Tool':<25} {'Calls':>8} {'Avg ms':>10} {'Success':>8}")
    emit_info("  " + "-" * 55)

    for tool in stats[:10]:
        name = tool.get("tool_name", "unknown")[:24]
        calls = tool.get("call_count", 0)
        avg_ms = tool.get("avg_duration_ms", 0) or 0
        success_rate = tool.get("success_rate", 100) or 100
        emit_info(f"  {name:<25} {_format_number(calls):>8} {_format_ms(avg_ms):>10} {success_rate:>7.0f}%")


def _show_file_stats(days: int) -> None:
    """Display file access patterns."""
    stats = get_file_access_patterns(days)

    if not stats:
        emit_info("📊 No file access data available")
        return

    emit_info(f"📁 File Access Patterns (last {days} days)")
    emit_info("")
    emit_info(f"  {'File Path':<45} {'Accesses':>8} {'Turns':>6}")
    emit_info("  " + "-" * 65)

    for file in stats[:10]:
        path = file.get("file_path", "unknown")[:44]
        accesses = file.get("access_count", 0)
        turns = file.get("unique_turns", 0)
        emit_info(f"  {path:<45} {_format_number(accesses):>8} {_format_number(turns):>6}")


def _show_top_stats(days: int) -> None:
    """Display top models and tools."""
    models = get_top_models(days)
    tools = get_top_tools(days)

    emit_info(f"🏆 Top Models & Tools (last {days} days)")
    emit_info("")

    if models:
        emit_info("  Top Models:")
        emit_info(f"    {'Model':<25} {'Turns':>8} {'Tokens':>12} {'Success':>8}")
        emit_info("    " + "-" * 60)
        for model in models[:5]:
            name = model.get("model_name", "unknown")[:24]
            turns = model.get("turns", 0)
            tokens = model.get("total_tokens", 0) or 0
            success = model.get("success_rate", 100) or 100
            emit_info(f"    {name:<25} {_format_number(turns):>8} {_format_number(tokens):>12} {success:>7.0f}%")
        emit_info("")

    if tools:
        emit_info("  Top Tools:")
        emit_info(f"    {'Tool':<25} {'Calls':>8} {'Turns':>8}")
        emit_info("    " + "-" * 45)
        for tool in tools[:5]:
            name = tool.get("tool_name", "unknown")[:24]
            calls = tool.get("call_count", 0)
            turns = tool.get("unique_turns", 0)
            emit_info(f"    {name:<25} {_format_number(calls):>8} {_format_number(turns):>8}")


def _show_daily_summary(days: int) -> None:
    """Display daily summary."""
    stats = get_daily_summary(days)

    if not stats:
        emit_info("📊 No daily data available")
        return

    emit_info(f"📅 Daily Summary (last {days} days)")
    emit_info("")
    emit_info(f"  {'Date':<12} {'Turns':>6} {'Models':>6} {'Tokens':>10}")
    emit_info("  " + "-" * 40)

    for day in stats[:14]:  # Show last 14 days max
        date = str(day.get("date", "unknown"))[:10]
        turns = day.get("turns", 0)
        models = day.get("models_used", 0)
        tokens = (day.get("input_tokens", 0) or 0) + (day.get("output_tokens", 0) or 0)
        emit_info(f"  {date:<12} {_format_number(turns):>6} {_format_number(models):>6} {_format_number(tokens):>10}")


def _show_summary() -> None:
    """Display overall summary."""
    stats = get_summary()

    if not stats:
        emit_info("📊 No analytics data available")
        return

    emit_info("📈 Overall Summary")
    emit_info("")
    emit_info(f"  Total turns:         {_format_number(stats.get('total_turns'))}")
    emit_info(f"  Total tool calls:      {_format_number(stats.get('total_tool_calls'))}")
    emit_info(f"  Total file accesses:   {_format_number(stats.get('total_file_accesses'))}")
    emit_info(f"  Unique models used:    {_format_number(stats.get('unique_models'))}")
    emit_info(f"  Unique agents:         {_format_number(stats.get('unique_agents'))}")
    emit_info(f"  First turn:          {stats.get('first_turn') or 'N/A'}")
    emit_info(f"  Last turn:           {stats.get('last_turn') or 'N/A'}")


def _show_dashboard(days: int) -> None:
    """Display analytics dashboard with key metrics."""
    emit_info("📊 Analytics Dashboard")
    emit_info("")

    # Summary first
    summary = get_summary()
    if summary:
        turns = summary.get("total_turns", 0) or 0
        tool_calls = summary.get("total_tool_calls", 0) or 0
        files = summary.get("total_file_accesses", 0) or 0
        emit_info(f"  Lifetime: {turns:,} turns, {tool_calls:,} tool calls, {files:,} file ops")
        emit_info("")

    # Recent activity
    daily = get_daily_summary(days)
    if daily:
        recent_turns = sum(d.get("turns", 0) or 0 for d in daily[:7])
        emit_info(f"  Last 7 days: {recent_turns:,} turns")

    # Token usage
    tokens = get_token_stats(7)
    if tokens and tokens.get("total_tokens"):
        total = tokens.get("total_tokens", 0)
        emit_info(f"  Tokens (7d): {total:,} total")

    # Top model
    models = get_top_models(7, 1)
    if models:
        name = models[0].get("model_name", "unknown")
        count = models[0].get("turns", 0)
        emit_info(f"  Top model:   {name} ({count} turns)")

    emit_info("")
    emit_info("  Use /analytics [tokens|latency|tools|files|top|daily|summary] for details")
    emit_info("  Use --days N to change the lookback period (default: 7)")


# ---------------------------------------------------------------------------
# Register Callbacks
# ---------------------------------------------------------------------------

if DUCKDB_AVAILABLE:
    register_callback("agent_run_start", _on_agent_run_start)
    register_callback("agent_run_end", _on_agent_run_end)
    register_callback("pre_tool_call", _on_pre_tool_call)
    register_callback("post_tool_call", _on_post_tool_call)
    register_callback("custom_command", _handle_analytics_command)
    register_callback("custom_command_help", _analytics_help)
else:
    # Register a minimal command that warns about missing duckdb
    def _warn_missing_duckdb(command: str, name: str) -> bool | None:
        if name == "analytics":
            emit_info("⚠️  DuckDB not available. Install with: uv add duckdb")
            return True
        return None

    def _warn_help():
        return [("analytics", "Analytics (requires duckdb: uv add duckdb)")]

    register_callback("custom_command", _warn_missing_duckdb)
    register_callback("custom_command_help", _warn_help)
