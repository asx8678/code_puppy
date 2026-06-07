"""SubAgentConsoleManager - Aggregated display for parallel sub-agents.

Provides a Rich Live dashboard that shows real-time status of multiple
running sub-agents, each in its own panel with spinner animations,
status badges, and performance metrics.

Usage:
    >>> manager = SubAgentConsoleManager.get_instance()
    >>> manager.register_agent("session-123", "fast-puppy", "gpt-4o")
    >>> manager.update_agent("session-123", status="running", tool_call_count=5)
    >>> manager.unregister_agent("session-123")
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from code_puppy.messaging.messages import SubAgentStatusMessage

logger = logging.getLogger(__name__)

# =============================================================================
# Status Configuration
# =============================================================================

STATUS_STYLES = {
    "starting": {"color": "cyan", "spinner": "dots", "emoji": "🚀"},
    "running": {"color": "green", "spinner": "dots", "emoji": "🐕"},
    "thinking": {"color": "magenta", "spinner": "dots", "emoji": "🤔"},
    "tool_calling": {"color": "yellow", "spinner": "dots12", "emoji": "🔧"},
    "completed": {"color": "green", "spinner": None, "emoji": "✅"},
    "error": {"color": "red", "spinner": None, "emoji": "❌"},
}

DEFAULT_STYLE = {"color": "white", "spinner": "dots", "emoji": "⏳"}


# =============================================================================
# Agent State Tracking
# =============================================================================


@dataclass
class AgentState:
    """Internal state tracking for a single sub-agent.

    Tracks all metrics needed for rendering the agent's status panel,
    including timing, tool usage, and error information.
    """

    session_id: str
    agent_name: str
    model_name: str
    status: str = "starting"
    tool_call_count: int = 0
    token_count: int = 0
    token_limit: int | None = None
    current_tool: str | None = None
    start_time: float = field(default_factory=time.time)
    error_message: str | None = None
    completed_at: float | None = None

    def elapsed_seconds(self) -> float:
        """Calculate elapsed time since agent started."""
        return time.time() - self.start_time

    def elapsed_formatted(self) -> str:
        """Format elapsed time as human-readable string."""
        elapsed = self.elapsed_seconds()
        if elapsed < 60:
            return f"{elapsed:.1f}s"
        minutes = int(elapsed // 60)
        seconds = elapsed % 60
        return f"{minutes}m {seconds:.1f}s"

    def token_percent(self) -> float | None:
        """Percent of the model's context window used (None when no limit)."""
        if not self.token_limit:
            return None
        return (self.token_count / self.token_limit) * 100

    def to_status_message(self) -> SubAgentStatusMessage:
        """Convert to a SubAgentStatusMessage for bus emission."""
        return SubAgentStatusMessage(
            session_id=self.session_id,
            agent_name=self.agent_name,
            model_name=self.model_name,
            status=self.status,  # type: ignore[arg-type]
            tool_call_count=self.tool_call_count,
            token_count=self.token_count,
            token_limit=self.token_limit,
            token_percent=self.token_percent(),
            current_tool=self.current_tool,
            elapsed_seconds=self.elapsed_seconds(),
            error_message=self.error_message,
        )


# =============================================================================
# SubAgent Console Manager
# =============================================================================


class SubAgentConsoleManager:
    """Manager for displaying multiple parallel sub-agents in Rich Live panels.

    This is a singleton that tracks all running sub-agents and renders them
    in a unified Rich Live display. Each agent gets its own panel with:
    - Agent name and session ID
    - Model being used
    - Status with spinner animation (for active states)
    - Tool call count and current tool
    - Token count
    - Elapsed time

    The display auto-starts when the first agent registers and auto-stops
    when the last agent unregisters.

    Thread-safe: All operations are protected by locks.
    """

    _instance: "SubAgentConsoleManager" | None = None
    _lock = threading.Lock()
    _LINGER_SECONDS: float = 1.5

    def __init__(self, console: Console | None = None):
        """Initialize the manager.

        Args:
            console: Optional Rich Console instance. If not provided,
                    a new one will be created.
        """
        self.console = console or Console()
        self._agents: dict[str, AgentState] = {}
        self._agents_lock = threading.RLock()  # Reentrant lock for agent operations
        self._live: Live | None = None
        self._update_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @classmethod
    def get_instance(cls, console: Console | None = None) -> "SubAgentConsoleManager":
        """Get or create the singleton instance.

        Thread-safe singleton pattern using double-checked locking.

        Args:
            console: Optional Rich Console to use. Only used when creating
                    the initial instance.

        Returns:
            The singleton SubAgentConsoleManager instance.
        """
        if cls._instance is None:
            with cls._lock:
                # Double-check inside lock
                if cls._instance is None:
                    cls._instance = cls(console)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (primarily for testing).

        Stops any running display and clears the singleton.
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance._stop_display()
                cls._instance = None

    # =========================================================================
    # Agent Registration
    # =========================================================================

    def register_agent(
        self,
        session_id: str,
        agent_name: str,
        model_name: str,
        *,
        token_count: int = 0,
        token_limit: int | None = None,
    ) -> None:
        """Register a new sub-agent and start display if needed.

        Args:
            session_id: Unique identifier for this agent session.
            agent_name: Name of the agent (e.g., 'fast-puppy', 'qa-kitten').
            model_name: Name of the model being used (e.g., 'gpt-4o').
            token_count: Initial token count seed (e.g., from history + prompt
                + system overhead). Streamed deltas accumulate on top of this.
            token_limit: Optional model context-window size, used to render
                the context-% in the dashboard.
        """
        with self._agents_lock:
            self._agents[session_id] = AgentState(
                session_id=session_id,
                agent_name=agent_name,
                model_name=model_name,
                token_count=token_count,
                token_limit=token_limit,
            )
            if len(self._agents) == 1:
                self._start_display()

    def update_agent(self, session_id: str, **kwargs) -> None:
        """Update status of an existing agent.

        Args:
            session_id: The session ID of the agent to update.
            **kwargs: Fields to update. Valid fields:
                - status: Current status string
                - tool_call_count: Number of tools called
                - token_count: Tokens in context
                - current_tool: Name of tool being called (or None)
                - error_message: Error message if status is 'error'
        """
        with self._agents_lock:
            if session_id not in self._agents:
                return  # Silently ignore updates for unknown agents

            agent = self._agents[session_id]

            # Update only provided fields
            if "status" in kwargs:
                agent.status = kwargs["status"]
            if "tool_call_count" in kwargs:
                agent.tool_call_count = kwargs["tool_call_count"]
            if "token_count" in kwargs:
                agent.token_count = kwargs["token_count"]
            if "current_tool" in kwargs:
                agent.current_tool = kwargs["current_tool"]
            if "error_message" in kwargs:
                agent.error_message = kwargs["error_message"]

    def unregister_agent(
        self, session_id: str, final_status: str = "completed"
    ) -> None:
        """Mark an agent finished; the update loop removes it after a linger window."""
        with self._agents_lock:
            agent = self._agents.get(session_id)
            if agent is not None:
                agent.status = final_status
                agent.completed_at = time.time()

    def get_agent_state(self, session_id: str) -> AgentState | None:
        """Get the current state of an agent.

        Args:
            session_id: The session ID to look up.

        Returns:
            The AgentState if found, None otherwise.
        """
        with self._agents_lock:
            return self._agents.get(session_id)

    def get_all_agents(self) -> list[AgentState]:
        """Get a list of all currently tracked agents.

        Returns:
            List of AgentState objects (copies to prevent mutation).
        """
        with self._agents_lock:
            return list(self._agents.values())

    # =========================================================================
    # Display Management
    # =========================================================================

    def _start_display(self) -> None:
        """Start the Rich Live display.

        Creates the Live context and starts a background thread to
        continuously refresh the display.
        """
        if self._live is not None:
            return  # Already running

        self._stop_event.clear()

        # Pause the main spinner so its Live releases the shared console's single
        # Live slot; otherwise Rich raises LiveError (only one Live per console).
        # No-op when called from a sub-agent context (see spinner module).
        from code_puppy.messaging.spinner import pause_all_spinners

        pause_all_spinners()

        # Create Live display
        self._live = Live(
            self._render_display(),
            console=self.console,
            refresh_per_second=2,
            transient=True,  # Clear when stopped
        )
        self._live.start()

        # Start background update thread
        self._update_thread = threading.Thread(
            target=self._update_loop, daemon=True, name="SubAgentDisplayUpdater"
        )
        self._update_thread.start()

    def _stop_display(self) -> None:
        """Stop the Live display. Safe to call from the update thread itself."""
        self._stop_event.set()
        if (
            self._update_thread is not None
            and self._update_thread is not threading.current_thread()
        ):
            self._update_thread.join(timeout=1.0)
        self._update_thread = None
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None
        from code_puppy.messaging.spinner import resume_all_spinners

        resume_all_spinners()

    def _update_loop(self) -> None:
        """Background refresh: prune lingered rows, stop when empty."""
        while not self._stop_event.is_set():
            try:
                now = time.time()
                with self._agents_lock:
                    expired = [
                        sid
                        for sid, a in self._agents.items()
                        if a.completed_at is not None
                        and (now - a.completed_at) >= self._LINGER_SECONDS
                    ]
                    for sid in expired:
                        del self._agents[sid]
                    empty = not self._agents
                if empty:
                    self._stop_display()
                    return
                if self._live is not None:
                    self._live.update(self._render_display())
            except Exception as e:
                # Keep trying, but don't fail silently — a persistent render
                # bug would otherwise just freeze the dashboard with no trace.
                logger.debug("Sub-agent dashboard render error: %s", e)

            # Sleep between updates. The only per-frame-changing content is the
            # elapsed timer (second granularity), so ~4 FPS is plenty and far
            # cheaper than rebuilding every panel 10x/second.
            self._stop_event.wait(0.25)

    # =========================================================================
    # Rendering
    # =========================================================================

    def _render_display(self) -> Group:
        from code_puppy.messaging.spinner import SpinnerBase

        with self._agents_lock:
            if not self._agents:
                return Group(Text(""))
            table = Table.grid(padding=(0, 2))
            for _ in range(5):
                table.add_column()
            for agent in self._agents.values():
                style_config = STATUS_STYLES.get(agent.status, DEFAULT_STYLE)
                color = style_config["color"]
                emoji = style_config["emoji"]
                if agent.token_limit:
                    proportion = agent.token_count / agent.token_limit
                    tokens = SpinnerBase.format_context_info(
                        agent.token_count, agent.token_limit, proportion
                    )
                else:
                    tokens = f"Tokens: {agent.token_count:,}"
                table.add_row(
                    Text(f"{emoji} [{agent.agent_name}]", style=f"bold {color}"),
                    Text(agent.model_name, style="cyan"),
                    Text(agent.status, style=color),
                    Text(tokens, style="white"),
                    Text(
                        f"tool: {agent.current_tool}" if agent.current_tool else "",
                        style="yellow",
                    ),
                )
            return Group(
                Panel(
                    table,
                    title="Active sub-agents",
                    border_style="bright_blue",
                )
            )

    # =========================================================================
    # Context Manager Support
    # =========================================================================

    def __enter__(self) -> "SubAgentConsoleManager":
        """Support use as context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Clean up on context exit."""
        self._stop_display()


# =============================================================================
# Convenience Functions
# =============================================================================


def get_subagent_console_manager(
    console: Console | None = None,
) -> SubAgentConsoleManager:
    """Get the singleton SubAgentConsoleManager instance.

    Convenience function for accessing the manager.

    Args:
        console: Optional Rich Console (only used on first call).

    Returns:
        The singleton SubAgentConsoleManager.
    """
    return SubAgentConsoleManager.get_instance(console)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "AgentState",
    "SubAgentConsoleManager",
    "get_subagent_console_manager",
    "STATUS_STYLES",
    "DEFAULT_STYLE",
]
