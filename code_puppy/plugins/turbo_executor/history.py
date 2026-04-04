"""Execution history tracking for Turbo Executor.

Provides in-memory (session-scoped) tracking of plan execution history
with a ring buffer of recent executions.
"""

from datetime import datetime

from code_puppy.messaging import emit_info


class ExecutionHistory:
    """Tracks execution history of turbo plans.

    Uses a ring buffer with a maximum number of entries.
    History is session-scoped (in-memory only, no persistence).

    Example:
        history = ExecutionHistory()
        history.add_entry("plan-abc", 4, 150.5, "completed")
        entries = history.get_entries(limit=10)
        formatted = history.format_history()
    """

    MAX_ENTRIES = 50  # Ring buffer size

    def __init__(self):
        """Initialize an empty execution history."""
        self._entries: list[dict] = []

    def add_entry(
        self, plan_id: str, num_ops: int, duration_ms: float, status: str
    ) -> None:
        """Add a completed execution to history.

        Args:
            plan_id: Unique identifier for the plan
            num_ops: Number of operations in the plan
            duration_ms: Total execution time in milliseconds
            status: Execution status (e.g., "completed", "partial", "failed")
        """
        entry = {
            "plan_id": plan_id,
            "num_ops": num_ops,
            "duration_ms": duration_ms,
            "status": status,
            "timestamp": datetime.now().isoformat(),
        }
        self._entries.append(entry)
        # Ring buffer: remove oldest if exceeding max
        if len(self._entries) > self.MAX_ENTRIES:
            self._entries.pop(0)

    def get_entries(self, limit: int = 10) -> list[dict]:
        """Get recent entries from history.

        Args:
            limit: Maximum number of entries to return (default 10)

        Returns:
            List of history entries, most recent last
        """
        return self._entries[-limit:]

    def format_history(self, limit: int = 10) -> str:
        """Format history for display using emit_info.

        Args:
            limit: Maximum number of entries to display (default 10)

        Returns:
            Formatted string for display
        """
        entries = self.get_entries(limit)

        if not entries:
            return "📜 Turbo Execution History: (no executions yet)"

        lines = ["📜 Turbo Execution History:"]

        for i, entry in enumerate(entries, 1):
            plan_id = entry["plan_id"]
            num_ops = entry["num_ops"]
            duration_ms = entry["duration_ms"]
            status = entry["status"].upper()

            # Parse and format timestamp
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
                timestamp_str = ts.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                timestamp_str = entry["timestamp"]

            # Status emoji
            status_emoji = {
                "COMPLETED": "✅",
                "PARTIAL": "⚠️",
                "FAILED": "❌",
                "PENDING": "⏳",
                "RUNNING": "🔄",
            }.get(status, "❓")

            lines.append(
                f"  #{i} {plan_id} — {num_ops} ops, {duration_ms:.0f}ms, "
                f"{status_emoji} {status} ({timestamp_str})"
            )

        return "\n".join(lines)

    def display_history(self, limit: int = 10) -> None:
        """Display history using emit_info.

        Args:
            limit: Maximum number of entries to display (default 10)
        """
        formatted = self.format_history(limit)
        emit_info(formatted)

    def clear(self) -> None:
        """Clear all history entries."""
        self._entries.clear()

    def __len__(self) -> int:
        """Return the number of entries in history."""
        return len(self._entries)


# Module-level singleton instance
_history = ExecutionHistory()


def get_history() -> ExecutionHistory:
    """Get the global execution history instance.

    Returns:
        The singleton ExecutionHistory instance
    """
    return _history
