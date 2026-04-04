"""Smart result summarization for turbo executor output.

Converts raw PlanResult data into human-readable markdown summaries:
- Truncates large file contents with a preview and file count
- Counts and organizes grep matches by file
- Summarizes list_files with file counts and directory structure
"""

from __future__ import annotations

from typing import Any

from collections.abc import Callable

from code_puppy.plugins.turbo_executor.models import (
    OperationResult,
    OperationType,
    PlanResult,
    PlanStatus,
)

# Default limits for content truncation
DEFAULT_MAX_CONTENT_LENGTH = 8000  # characters
DEFAULT_MAX_CONTENT_LINES = 100  # lines
DEFAULT_MAX_GREP_MATCHES = 50  # matches to show before summarizing


def _truncate_content(
    content: str,
    max_length: int = DEFAULT_MAX_CONTENT_LENGTH,
    max_lines: int = DEFAULT_MAX_CONTENT_LINES,
) -> str:
    """Truncate content to reasonable limits for LLM consumption.

    Args:
        content: The content to truncate
        max_length: Maximum character length
        max_lines: Maximum number of lines

    Returns:
        Truncated content with indicator if truncation occurred
    """
    if not content:
        return ""

    lines = content.split("\n")
    truncated = False

    # Truncate by lines first
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True

    # Then truncate by character length
    result = "\n".join(lines)
    if len(result) > max_length:
        result = result[:max_length]
        truncated = True
        # Try to end at a newline or word boundary
        last_newline = result.rfind("\n")
        if last_newline > max_length * 0.8:
            result = result[:last_newline]

    if truncated:
        result += "\n\n[... content truncated ...]"

    return result


def _summarize_list_files(data: dict[str, Any]) -> str:
    """Summarize list_files operation result.

    Args:
        data: The operation result data

    Returns:
        Markdown summary string
    """
    if data.get("error"):
        return f"⚠️ **Error:** {data['error']}"

    content = data.get("content", "")
    if not content:
        return "📂 *Directory is empty or no files found*"

    # Count files and directories from the listing
    lines = content.split("\n")
    file_count = 0
    dir_count = 0

    for line in lines:
        # Look for patterns like "filename (type=file)" or "filename (type=directory)"
        if "(type=file)" in line or "(type=" not in line and "." in line:
            file_count += 1
        elif "(type=directory)" in line:
            dir_count += 1

    # Provide a preview of the listing
    preview = _truncate_content(content, max_length=3000, max_lines=30)

    summary_parts = ["📂 **Directory Listing**"]
    if file_count or dir_count:
        summary_parts.append(f"*Found {file_count} files, {dir_count} directories*")
    summary_parts.append("")
    summary_parts.append("```")
    summary_parts.append(preview)
    summary_parts.append("```")

    return "\n".join(summary_parts)


def _summarize_grep(data: dict[str, Any]) -> str:
    """Summarize grep operation result.

    Args:
        data: The operation result data

    Returns:
        Markdown summary string
    """
    if data.get("error"):
        return f"⚠️ **Error:** {data['error']}"

    matches = data.get("matches", [])
    total_matches = data.get("total_matches", len(matches))

    if not matches:
        return "🔍 *No matches found*"

    # Group matches by file
    matches_by_file: dict[str, list[dict]] = {}
    for match in matches:
        file_path = match.get("file_path", "unknown")
        if file_path not in matches_by_file:
            matches_by_file[file_path] = []
        matches_by_file[file_path].append(match)

    summary_parts = [
        f"🔍 **Search Results** ({total_matches} matches in {len(matches_by_file)} files)"
    ]
    summary_parts.append("")

    # Show matches (limited)
    matches_shown = 0
    for file_path, file_matches in matches_by_file.items():
        if matches_shown >= DEFAULT_MAX_GREP_MATCHES:
            remaining_files = len(matches_by_file) - list(matches_by_file.keys()).index(
                file_path
            )
            remaining_matches = total_matches - matches_shown
            summary_parts.append(
                f"\n*... and {remaining_matches} more matches in {remaining_files} files*"
            )
            break

        summary_parts.append(f"**{file_path}** ({len(file_matches)} matches)")

        for match in file_matches:
            if matches_shown >= DEFAULT_MAX_GREP_MATCHES:
                break

            line_num = match.get("line_number", 0)
            line_content = match.get("line_content", "")
            # Truncate very long lines
            if len(line_content) > 200:
                line_content = line_content[:200] + "..."
            summary_parts.append(f"  Line {line_num}: `{line_content}`")
            matches_shown += 1

        summary_parts.append("")

    return "\n".join(summary_parts)


def _summarize_read_files(data: dict[str, Any]) -> str:
    """Summarize read_files operation result.

    Args:
        data: The operation result data

    Returns:
        Markdown summary string
    """
    files = data.get("files", [])
    total_files = data.get("total_files", len(files))
    successful = data.get("successful_reads", sum(1 for f in files if f.get("success")))

    summary_parts = [
        f"📄 **File Contents** ({successful}/{total_files} files read successfully)"
    ]
    summary_parts.append("")

    for file_info in files:
        file_path = file_info.get("file_path", "unknown")
        content = file_info.get("content", "")
        error = file_info.get("error")
        success = file_info.get("success", False)

        if not success:
            summary_parts.append(f"❌ **{file_path}** - Error: {error}")
            summary_parts.append("")
            continue

        if content is None:
            summary_parts.append(f"⚠️ **{file_path}** - No content")
            summary_parts.append("")
            continue

        # Truncate content
        truncated = _truncate_content(content)
        token_count = file_info.get("num_tokens", 0)

        summary_parts.append(f"**{file_path}**")
        if token_count:
            summary_parts.append(f"*{token_count} tokens*")
        summary_parts.append("```")
        summary_parts.append(truncated)
        summary_parts.append("```")
        summary_parts.append("")

    return "\n".join(summary_parts)


def _summarize_run_tests(data: dict[str, Any]) -> str:
    """Summarize run_tests operation result.

    Args:
        data: The operation result data

    Returns:
        Markdown summary string
    """
    if data.get("error"):
        return f"⚠️ **Error:** {data['error']}"

    # Extract test counts
    passed = data.get("passed", 0)
    failed = data.get("failed", 0)
    skipped = data.get("skipped", 0)
    errors = data.get("errors", 0)
    total = data.get("total", 0)
    duration = data.get("duration_seconds", 0.0)
    success = data.get("success", False)
    exit_code = data.get("exit_code", 0)
    runner = data.get("runner", "unknown")
    test_path = data.get("test_path", ".")

    # Status emoji based on results
    if success and failed == 0 and errors == 0:
        emoji = "✅"
        status_text = "Passed"
    elif failed > 0 or errors > 0:
        emoji = "❌"
        status_text = "Failed"
    elif skipped > 0 and passed == 0:
        emoji = "⏭️"
        status_text = "Skipped"
    else:
        emoji = "⚠️"
        status_text = "Partial"

    summary_parts = [
        f"{emoji} **Test Results** ({runner})",
        f"*Path: {test_path}*",
        "",
        f"**Status:** {status_text} (exit code {exit_code})",
        f"**Summary:** {passed} passed, {failed} failed, {skipped} skipped, {errors} errors",
    ]

    if total > 0:
        summary_parts.append(f"**Total:** {total} tests")

    if duration > 0:
        summary_parts.append(f"**Duration:** {duration:.2f}s")

    summary_parts.append("")

    # Show failure preview if there are failures
    if failed > 0 or errors > 0:
        output = data.get("output", "")
        if output:
            summary_parts.append("**Failure Preview:**")
            summary_parts.append("```")
            # Extract the first failure traceback (limited lines)
            failure_preview = _extract_failure_preview(output)
            summary_parts.append(failure_preview)
            summary_parts.append("```")
            summary_parts.append("")

    return "\n".join(summary_parts)


def _extract_failure_preview(output: str, max_lines: int = 30) -> str:
    """Extract a preview of the first failure from test output.

    Args:
        output: The full test output
        max_lines: Maximum lines to include in preview

    Returns:
        Truncated failure preview
    """
    if not output:
        return "No output available"

    lines = output.split("\n")

    # Look for failure patterns
    # Common patterns: "FAILED", "ERROR", "= FAILURES =", "AssertionError"
    failure_start = -1
    for i, line in enumerate(lines):
        line_upper = line.upper()
        if any(
            pattern in line_upper
            for pattern in ["FAILED", "ERROR", "= FAILURES =", "= ERRORS ="]
        ):
            failure_start = i
            break
        # Also check for traceback patterns
        if "Traceback (most recent call last)" in line:
            failure_start = i
            break

    if failure_start == -1:
        # No clear failure marker found, show last portion of output
        return "\n".join(lines[-max_lines:]) if len(lines) > max_lines else output

    # Get lines from failure start
    preview_lines = lines[failure_start : failure_start + max_lines]
    result = "\n".join(preview_lines)

    # Add truncation indicator if there's more content
    if failure_start + max_lines < len(lines):
        result += "\n\n[... additional failures truncated ...]"

    return result


def _summarize_discover_tests(data: dict[str, Any]) -> str:
    """Summarize discover_tests operation result.

    Args:
        data: The operation result data

    Returns:
        Markdown summary string
    """
    if data.get("error"):
        return f"⚠️ **Error:** {data['error']}"

    test_count = data.get("test_count", 0)
    test_files = data.get("test_files", [])
    test_modules = data.get("test_modules", [])
    test_items = data.get("test_items", [])
    test_path = data.get("test_path", ".")
    runner = data.get("runner", "unknown")
    pattern = data.get("pattern", "")
    success = data.get("success", False)

    # Status emoji
    if test_count > 0:
        emoji = "🔍"
        status_text = f"Found {test_count} tests"
    elif success:
        emoji = "✅"
        status_text = "No tests found (success)"
    else:
        emoji = "⚠️"
        status_text = "Discovery failed"

    summary_parts = [
        f"{emoji} **Test Discovery** ({runner})",
        f"*Path: {test_path}{f', pattern: {pattern}' if pattern else ''}*",
        "",
        f"**Status:** {status_text}",
    ]

    if test_count > 0:
        summary_parts.append(f"**Total Tests:** {test_count}")

    if test_files:
        summary_parts.append(f"**Test Files:** {len(test_files)} files")
        # Show first few test files
        preview_files = test_files[:10]
        summary_parts.append("```")
        for f in preview_files:
            summary_parts.append(f"  {f}")
        if len(test_files) > 10:
            summary_parts.append(f"  ... and {len(test_files) - 10} more")
        summary_parts.append("```")

    if test_modules and not test_files:
        summary_parts.append(f"**Test Modules:** {len(test_modules)} directories")

    if test_items and len(test_items) <= 20:
        summary_parts.append("")
        summary_parts.append("**Test Cases:**")
        summary_parts.append("```")
        for item in test_items[:20]:
            item_type = item.get("type", "Test")
            item_name = item.get("name", "unknown")
            summary_parts.append(f"  {item_type}: {item_name}")
        if len(test_items) > 20:
            summary_parts.append(f"  ... and {len(test_items) - 20} more")
        summary_parts.append("```")

    summary_parts.append("")

    return "\n".join(summary_parts)


# Mapping of operation types to their summarizers
_OPERATION_SUMMARIZERS: dict[OperationType, Callable] = {
    OperationType.LIST_FILES: _summarize_list_files,
    OperationType.GREP: _summarize_grep,
    OperationType.READ_FILES: _summarize_read_files,
    OperationType.RUN_TESTS: _summarize_run_tests,
    OperationType.DISCOVER_TESTS: _summarize_discover_tests,
}


def summarize_operation_result(result: OperationResult) -> str:
    """Generate a human-readable summary for a single operation result.

    Args:
        result: The operation result to summarize

    Returns:
        Markdown-formatted summary string
    """
    if result.status == "error":
        return f"❌ **Operation Failed:** {result.error}"

    summarizer = _OPERATION_SUMMARIZERS.get(result.type)
    if not summarizer:
        return f"📋 **{result.type.value}** (no summary available)"

    return summarizer(result.data)


def summarize_plan_result(
    plan_result: PlanResult,
    include_operation_details: bool = True,
) -> str:
    """Generate a comprehensive markdown summary of a plan execution result.

    Args:
        plan_result: The plan result to summarize
        include_operation_details: Whether to include detailed operation summaries

    Returns:
        Markdown-formatted summary string
    """
    # Status emoji mapping
    status_emojis = {
        PlanStatus.COMPLETED: "✅",
        PlanStatus.PARTIAL: "⚠️",
        PlanStatus.FAILED: "❌",
        PlanStatus.RUNNING: "⏳",
        PlanStatus.PENDING: "⏸️",
    }

    emoji = status_emojis.get(plan_result.status, "📋")

    # Build header
    lines = [
        f"{emoji} **Plan Execution: {plan_result.plan_id}**",
        "",
        f"**Status:** {plan_result.status.value}",
        f"**Operations:** {plan_result.success_count} success, {plan_result.error_count} errors",
        f"**Duration:** {plan_result.total_duration_ms:.1f}ms",
    ]

    if plan_result.metadata:
        total_ops = plan_result.metadata.get("total_operations", 0)
        if total_ops:
            lines.append(f"**Total Operations:** {total_ops}")

    lines.append("")

    # Add operation summaries
    if include_operation_details and plan_result.operation_results:
        lines.append("---")
        lines.append("")
        lines.append("### Operation Results")
        lines.append("")

        for i, op_result in enumerate(plan_result.operation_results, 1):
            lines.append(f"#### {i}. {op_result.type.value}")
            if op_result.operation_id:
                lines.append(f"*ID: {op_result.operation_id}*")
            lines.append("")
            lines.append(summarize_operation_result(op_result))
            lines.append("")

    # Add error summary if there are errors
    if plan_result.error_count > 0:
        lines.append("---")
        lines.append("")
        lines.append("### Errors")
        lines.append("")

        for op_result in plan_result.get_errors():
            lines.append(
                f"- **{op_result.type.value}** (`{op_result.operation_id}`): {op_result.error}"
            )

    return "\n".join(lines)


def quick_summary(plan_result: PlanResult) -> str:
    """Generate a one-line summary of plan execution.

    Args:
        plan_result: The plan result to summarize

    Returns:
        Short summary string
    """
    status_emoji = {
        PlanStatus.COMPLETED: "✅",
        PlanStatus.PARTIAL: "⚠️",
        PlanStatus.FAILED: "❌",
    }.get(plan_result.status, "📋")

    return (
        f"{status_emoji} Plan '{plan_result.plan_id}': "
        f"{plan_result.success_count}/{plan_result.success_count + plan_result.error_count} ops, "
        f"{plan_result.total_duration_ms:.0f}ms"
    )
