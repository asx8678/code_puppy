"""Turbo Executor Notifications — Visual feedback for batch operations.

Hooks into pre_tool_call and post_tool_call callbacks to detect turbo_execute
tool calls and emit visual progress notifications to the user.
"""

import json
import logging
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info, emit_success, emit_warning

logger = logging.getLogger(__name__)

# Operation type to emoji mapping
_OP_EMOJIS = {
    "list_files": "📂",
    "grep": "🔍",
    "read_files": "📄",
}

# Operation type singular/plural forms for display
_OP_DISPLAY_NAMES = {
    "list_files": "list_files",
    "grep": "grep",
    "read_files": "read_files",
}


def _get_op_emoji(op_type: str) -> str:
    """Get emoji for operation type."""
    return _OP_EMOJIS.get(op_type, "⚡")


def _get_op_display_name(op_type: str, count: int = 1) -> str:
    """Get display name for operation type.

    Args:
        op_type: The operation type
        count: Number of operations (for pluralization)

    Returns:
        Display name for the operation type
    """
    return _OP_DISPLAY_NAMES.get(op_type, op_type)


def generate_plan_preview(plan_data: dict) -> str:
    """Generate a formatted plan preview string.

    Creates a concise summary showing the operation breakdown by type,
    total count, and any validation warnings.

    Args:
        plan_data: The plan dictionary (parsed from plan_json)

    Returns:
        Formatted preview string like:
        "📋 Plan preview: 1× list_files, 2× grep, 1× read_files (4 ops)"
    """
    operations = plan_data.get("operations", [])
    num_ops = len(operations)

    if num_ops == 0:
        return "📋 Plan preview: no operations"

    # Count operations by type
    op_counts: dict[str, int] = {}
    for op in operations:
        op_type = op.get("type", "unknown")
        op_counts[op_type] = op_counts.get(op_type, 0) + 1

    # Build the operation breakdown
    breakdown_parts = []
    for op_type, count in sorted(op_counts.items()):
        display_name = _get_op_display_name(op_type, count)
        breakdown_parts.append(f"{count}× {display_name}")

    breakdown = ", ".join(breakdown_parts) if breakdown_parts else "no operations"

    return f"📋 Plan preview: {breakdown} ({num_ops} ops)"


def _format_brief_args(op_type: str, args: dict) -> str:
    """Format brief argument summary for an operation."""
    if op_type == "list_files":
        directory = args.get("directory", ".")
        return f"dir={directory}"

    if op_type == "grep":
        search = args.get("search_string", "")
        # Truncate long search strings
        if len(search) > 30:
            search = search[:27] + "..."
        return f"search='{search}'"

    if op_type == "read_files":
        paths = args.get("file_paths", [])
        count = len(paths) if isinstance(paths, list) else 0
        return f"{count} files"

    return ""


def _format_brief_stats(op_type: str, data: dict) -> str:
    """Format brief stats from operation result data."""
    if op_type == "list_files":
        content = data.get("content", "")
        if isinstance(content, str):
            # Count lines (files/directories listed)
            lines = [line for line in content.split("\n") if line.strip()]
            return f"{len(lines)} items"
        return ""

    if op_type == "grep":
        matches = data.get("total_matches", 0)
        return f"{matches} matches"

    if op_type == "read_files":
        successful = data.get("successful_reads", 0)
        total = data.get("total_files", 0)
        return f"{successful}/{total} reads"

    return ""


def _on_pre_tool_call(tool_name: str, tool_args: dict, context: Any = None) -> None:
    """Handle pre_tool_call callback for turbo_execute.

    Emits startup banner when a turbo_execute tool call begins.

    Args:
        tool_name: Name of the tool being called
        tool_args: Arguments passed to the tool (contains plan_json)
        context: Optional context object
    """
    # Ignore non-turbo_execute tool calls
    if tool_name != "turbo_execute":
        return

    try:
        plan_json_str = tool_args.get("plan_json", "{}")
        plan_data = json.loads(plan_json_str)

        plan_id = plan_data.get("id", "unnamed")
        operations = plan_data.get("operations", [])
        num_ops = len(operations)

        # Build operation type summary
        op_counts: dict[str, int] = {}
        for op in operations:
            op_type = op.get("type", "unknown")
            op_counts[op_type] = op_counts.get(op_type, 0) + 1

        summary_parts = []
        for op_type, count in sorted(op_counts.items()):
            emoji = _get_op_emoji(op_type)
            summary_parts.append(f"{emoji} {count} {op_type}")

        summary = ", ".join(summary_parts) if summary_parts else "no operations"

        # Emit startup banner
        emit_info(f"🚀 Turbo Plan '{plan_id}' starting — {num_ops} operations")

        # Emit plan preview (new feature!)
        plan_preview = generate_plan_preview(plan_data)
        emit_info(f"   {plan_preview}")

        # Emit detailed type summary
        emit_info(f"   {summary}")

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse turbo_execute plan_json: {e}")
        emit_info("🚀 Turbo Plan starting — parsing plan...")
    except Exception as e:
        logger.warning(f"Error in turbo_execute pre_tool_call notification: {e}")
        # Fail silently - don't break the actual tool execution


def _on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> None:
    """Handle post_tool_call callback for turbo_execute.

    Emits completion summary and error warnings when turbo_execute completes.

    Args:
        tool_name: Name of the tool that was called
        tool_args: Arguments passed to the tool
        result: Result returned by the tool (dict with status, counts, etc.)
        duration_ms: Duration of the tool call in milliseconds
        context: Optional context object
    """
    # Ignore non-turbo_execute tool calls
    if tool_name != "turbo_execute":
        return

    try:
        # Handle result as dict (expected format)
        if isinstance(result, dict):
            status = result.get("status", "unknown")

            success_count = result.get("success_count", 0)
            error_count = result.get("error_count", 0)
            total_duration = result.get("total_duration_ms", duration_ms)

            # Emit completion summary
            emit_success(
                f"✅ Turbo Plan completed — {success_count} success, {error_count} errors in {total_duration:.0f}ms"
            )

            # Emit accomplishment summary
            summary = generate_accomplishment_summary(result)
            if summary:
                emit_info(summary)

            # Emit warnings for each failed operation
            if error_count > 0:
                op_results = result.get("operation_results", [])
                for op_result in op_results:
                    if op_result.get("status") == "error":
                        op_id = op_result.get("operation_id", "unknown")
                        op_type = op_result.get("type", "unknown")
                        error_msg = op_result.get("error", "Unknown error")
                        emit_warning(f"   ❌ {op_type} ({op_id}): {error_msg}")

            # If overall status indicates failure but no individual errors recorded
            if status == "failed" and error_count == 0:
                emit_warning(
                    "   ❌ Turbo Plan failed with no specific operation errors"
                )

        else:
            # Unexpected result format - emit basic completion
            emit_success(f"✅ Turbo Plan completed in {duration_ms:.0f}ms")

    except Exception as e:
        logger.warning(f"Error in turbo_execute post_tool_call notification: {e}")
        # Fail silently - don't break the actual tool execution


def generate_accomplishment_summary(result_data: dict) -> str:
    """Generate a formatted accomplishment summary from turbo execution results.

    Groups operation results by type and summarizes what was accomplished:
    - list_files: count of items listed
    - grep: total matches and unique files matched
    - read_files: total files and successful reads

    Args:
        result_data: The result dictionary containing operation_results and total_duration_ms

    Returns:
        Formatted summary string, or empty string if no data to summarize
    """
    if not isinstance(result_data, dict):
        return ""

    operation_results = result_data.get("operation_results", [])
    if not operation_results:
        return ""

    total_duration = result_data.get("total_duration_ms", 0.0)

    # Counters for each operation type
    list_files_count = 0
    grep_total_matches = 0
    grep_unique_files: set[str] = set()
    read_files_total = 0
    read_files_successful = 0

    for op in operation_results:
        if not isinstance(op, dict):
            continue

        op_type = op.get("type", "")
        op_status = op.get("status", "")
        op_data = op.get("data", {}) or {}

        # Skip failed operations in summary counts
        if op_status != "success":
            continue

        if op_type == "list_files":
            content = op_data.get("content", "")
            if isinstance(content, list):
                list_files_count += len(content)
            elif isinstance(content, str):
                # Count non-empty lines
                lines = [line for line in content.split("\n") if line.strip()]
                list_files_count += len(lines)

        elif op_type == "grep":
            matches = op_data.get("matches", [])
            grep_total_matches += op_data.get("total_matches", len(matches))

            # Count unique files from matches
            for match in matches:
                if isinstance(match, dict):
                    file_path = match.get("file", "")
                    if file_path:
                        grep_unique_files.add(file_path)

        elif op_type == "read_files":
            read_files_total += op_data.get("total_files", 0)
            read_files_successful += op_data.get("successful_reads", 0)

    # Build summary lines
    summary_parts: list[str] = []

    if list_files_count > 0:
        summary_parts.append(f"   📂 Listed {list_files_count} files")

    if grep_total_matches > 0 or grep_unique_files:
        summary_parts.append(f"   🔍 Found {grep_total_matches} matches across {len(grep_unique_files)} files")

    if read_files_total > 0 or read_files_successful > 0:
        summary_parts.append(f"   📄 Read {read_files_successful} files")

    if not summary_parts:
        return ""

    summary_parts.append(f"   Total: {total_duration:.0f}ms")

    return "📊 Turbo Accomplishments:\n" + "\n".join(summary_parts)


def _format_progress_line(
    current: int, total: int, op_type: str, args: dict, is_start: bool = True
) -> str:
    """Format a progress line for an operation.

    Args:
        current: Current operation number (1-indexed)
        total: Total number of operations
        op_type: Type of operation (list_files, grep, read_files)
        args: Operation arguments dict
        is_start: True for start line, False for completion

    Returns:
        Formatted progress line string
    """
    emoji = _get_op_emoji(op_type)
    brief = _format_brief_args(op_type, args)

    if is_start:
        return f"⚡ [{current}/{total}] {emoji} {op_type} {brief} ..."
    return f"⚡ [{current}/{total}] {emoji} {op_type} {brief}"


def emit_operation_start(current: int, total: int, op_type: str, args: dict, elapsed_ms: float = 0.0) -> None:
    """Emit operation start progress line.

    This is called from the orchestrator before each operation begins.

    Args:
        current: Current operation number (1-indexed)
        total: Total number of operations
        op_type: Type of operation
        args: Operation arguments
        elapsed_ms: Elapsed time since plan start in milliseconds
    """
    emoji = _get_op_emoji(op_type)
    brief = _format_brief_args(op_type, args)
    emit_info(f"⚡ [{current}/{total}] {emoji} {op_type} {brief} starting...")


def emit_operation_complete(
    current: int, total: int, op_type: str, args: dict, duration_ms: float, data: dict, elapsed_ms: float = 0.0
) -> None:
    """Emit operation completion progress line.

    This is called from the orchestrator after each operation completes.

    Args:
        current: Current operation number (1-indexed)
        total: Total number of operations
        op_type: Type of operation
        args: Operation arguments
        duration_ms: Duration in milliseconds for this operation
        data: Result data from the operation
        elapsed_ms: Elapsed time since plan start in milliseconds
    """
    stats = _format_brief_stats(op_type, data)
    emit_info(
        f"⚡ [{current}/{total}] ✅ {op_type} done ({duration_ms:.0f}ms, {stats}) — "
        f"{elapsed_ms:.0f}ms elapsed, {current}/{total} complete"
    )


def emit_operation_error(current: int, total: int, op_type: str, error: str, elapsed_ms: float = 0.0) -> None:
    """Emit operation error progress line.

    This is called from the orchestrator when an operation fails.

    Args:
        current: Current operation number (1-indexed)
        total: Total number of operations
        op_type: Type of operation
        error: Error message
        elapsed_ms: Elapsed time since plan start in milliseconds
    """
    emit_info(f"⚡ [{current}/{total}] ❌ {op_type} failed: {error} — {elapsed_ms:.0f}ms elapsed, {current}/{total} complete")


def register() -> None:
    """Register turbo_execute notification callbacks.

    Call this function from the plugin's register_callbacks.py to enable
    visual notifications for turbo_execute tool calls.
    """
    register_callback("pre_tool_call", _on_pre_tool_call)
    register_callback("post_tool_call", _on_post_tool_call)
    logger.debug("Turbo Executor notification callbacks registered")
