"""Swarm execution visualization screen — Textual overlay.

Displays multi-agent consensus execution in real-time:
- Side-by-side agent results comparison in a DataTable
- Confidence scores shown as progress bars
- Consensus points vs disagreements highlighted
- Scrollable debate transcript in RichLog
- Real-time updates as agents complete
- Action buttons: Accept Consensus, Re-run Swarm, View Details

Wired via: /swarm → pushes SwarmScreen
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    ProgressBar,
    RichLog,
    Static,
)

from code_puppy.tui.base_screen import MenuScreen

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _get_status_emoji(confidence: float, is_consensus: bool = False) -> str:
    """Get appropriate emoji for confidence level."""
    if is_consensus:
        return "🎯"
    if confidence >= 0.8:
        return "🔥"
    if confidence >= 0.6:
        return "✅"
    if confidence >= 0.4:
        return "⚠️"
    return "❌"


def _format_confidence_bar(confidence: float, width: int = 20) -> str:
    """Format a text-based confidence bar."""
    filled = int(confidence * width)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return f"[{bar}] {confidence:.0%}"


# ---------------------------------------------------------------------------
# Screen
# ---------------------------------------------------------------------------


class SwarmScreen(MenuScreen):
    """Swarm consensus visualization screen.

    Top section: DataTable comparing agent responses side-by-side
    Middle: Progress bars showing confidence scores
    Bottom left: Debate transcript (scrollable)
    Bottom right: Consensus summary and action buttons

    Updates in real-time as agents complete their tasks.
    """

    BINDINGS = MenuScreen.BINDINGS + [
        Binding("a", "accept_consensus", "Accept", show=True),
        Binding("r", "rerun_swarm", "Re-run", show=True),
        Binding("d", "view_details", "Details", show=True),
        Binding("c", "toggle_consensus_only", "Consensus Only", show=False),
    ]

    DEFAULT_CSS = """
    SwarmScreen {
        layout: vertical;
    }

    SwarmScreen > #swarm-title {
        height: 1;
        background: $primary-darken-2;
        color: $text;
        text-style: bold;
        padding: 0 2;
    }

    SwarmScreen > #status-bar {
        height: 1;
        background: $surface-darken-1;
        color: $text-muted;
        padding: 0 2;
    }

    /* Top section: Results table */
    SwarmScreen > #results-section {
        height: 45%;
        border: solid $primary-lighten-2;
    }

    SwarmScreen #results-table {
        height: 100%;
        width: 100%;
    }

    /* Middle section: Confidence bars */
    SwarmScreen > #confidence-section {
        height: 20%;
        border: solid $primary-lighten-2;
        padding: 0 1;
    }

    SwarmScreen .confidence-row {
        height: auto;
        margin: 0 1;
    }

    SwarmScreen .confidence-label {
        width: 20;
        content-align: left middle;
    }

    SwarmScreen .confidence-bar {
        width: 1fr;
    }

    /* Bottom section: split view */
    SwarmScreen > #bottom-section {
        height: 35%;
    }

    SwarmScreen #transcript-panel {
        width: 60%;
        border-right: solid $primary-lighten-2;
        padding: 0 1;
    }

    SwarmScreen #transcript-log {
        height: 1fr;
        border: solid $surface-darken-1;
    }

    SwarmScreen #summary-panel {
        width: 40%;
        padding: 0 1;
    }

    SwarmScreen #consensus-summary {
        height: 60%;
        border: solid $surface-darken-1;
        padding: 1;
    }

    SwarmScreen #action-buttons {
        height: 40%;
        align: center middle;
    }

    SwarmScreen Button {
        margin: 0 1;
    }

    /* Status styling */
    SwarmScreen .consensus-reached {
        color: $success;
        text-style: bold;
    }

    SwarmScreen .consensus-pending {
        color: $warning;
        text-style: bold;
    }

    SwarmScreen .consensus-failed {
        color: $error;
        text-style: bold;
    }
    """

    # Reactive state
    swarm_result = reactive(None)
    is_running = reactive(False)
    show_consensus_only = reactive(False)

    def __init__(
        self,
        task_prompt: str = "",
        task_type: str = "default",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._task_prompt = task_prompt
        self._task_type = task_type
        self._agent_results: list = []
        self._orchestrator = None

    # ------------------------------------------------------------------
    # Compose / Mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("🤖 Agent Swarm Consensus", id="swarm-title")
        yield Static("Initializing swarm...", id="status-bar")

        # Results table section
        with Vertical(id="results-section"):
            yield DataTable(id="results-table", show_header=True, show_row_labels=False)

        # Confidence bars section
        with Vertical(id="confidence-section"):
            yield Static("[bold]Agent Confidence Scores[/bold]", classes="section-header")
            # Confidence bars will be added dynamically

        # Bottom section: transcript + summary
        with Horizontal(id="bottom-section"):
            with Vertical(id="transcript-panel"):
                yield Static("[bold]Debate Transcript[/bold]", classes="section-header")
                yield RichLog(
                    id="transcript-log",
                    markup=True,
                    highlight=False,
                    wrap=True,
                )

            with Vertical(id="summary-panel"):
                yield Static("[bold]Consensus Summary[/bold]", classes="section-header")
                yield Static("Waiting for agents...", id="consensus-summary")
                with Horizontal(id="action-buttons"):
                    yield Button("✓ Accept", id="btn-accept", variant="success")
                    yield Button("↻ Re-run", id="btn-rerun", variant="primary")
                    yield Button("ℹ Details", id="btn-details", variant="default")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize the screen and start swarm execution."""
        self._setup_table()
        self._update_status("Initializing swarm execution...")
        if self._task_prompt:
            self._start_swarm_execution()

    def _setup_table(self) -> None:
        """Configure the results DataTable."""
        table = self.query_one("#results-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Agent", "Approach", "Status", "Time", "Preview")
        table.zebra_stripes = True
        table.cursor_type = "row"

    def _update_status(self, message: str) -> None:
        """Update the status bar."""
        try:
            self.query_one("#status-bar", Static).update(message)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Swarm Execution
    # ------------------------------------------------------------------

    def _start_swarm_execution(self) -> None:
        """Start the async swarm execution."""
        import asyncio

        self.is_running = True
        self._update_status(f"Running swarm for: {self._task_prompt[:50]}...")

        # Run swarm in background
        asyncio.create_task(self._run_swarm_async())

    async def _run_swarm_async(self) -> None:
        """Execute swarm and update UI as results come in."""
        try:
            from code_puppy.plugins.swarm_consensus.config import (
                get_consensus_threshold,
                get_default_swarm_size,
                get_swarm_timeout_seconds,
            )
            from code_puppy.plugins.swarm_consensus.models import SwarmConfig
            from code_puppy.plugins.swarm_consensus.orchestrator import SwarmOrchestrator

            config = SwarmConfig(
                swarm_size=get_default_swarm_size(),
                consensus_threshold=get_consensus_threshold(),
                timeout_seconds=get_swarm_timeout_seconds(),
            )

            self._orchestrator = SwarmOrchestrator(config)

            # Execute swarm (this blocks until complete)
            result = await self._orchestrator.execute_swarm(
                task_prompt=self._task_prompt,
                task_type=self._task_type,
            )

            self.swarm_result = result
            self.is_running = False
            self._update_ui_with_result(result)

        except Exception as e:
            self.is_running = False
            self._update_status(f"❌ Swarm failed: {e}")
            self._log_transcript(f"[red]Error: {e}[/red]")

    # ------------------------------------------------------------------
    # UI Update Methods
    # ------------------------------------------------------------------

    def _update_ui_with_result(self, result) -> None:
        """Update all UI components with swarm result."""
        self._update_status_bar(result)
        self._populate_results_table(result)
        self._update_confidence_bars(result)
        self._update_transcript(result)
        self._update_summary(result)

    def _update_status_bar(self, result) -> None:
        """Update status bar with consensus info."""
        if result.consensus_reached:
            avg_conf = result.get_average_confidence()
            self._update_status(
                f"🎯 Consensus reached! Average confidence: {avg_conf:.0%}"
            )
        else:
            self._update_status("⚠️ No consensus reached - review individual results")

    def _populate_results_table(self, result) -> None:
        """Fill the DataTable with agent results."""
        table = self.query_one("#results-table", DataTable)
        table.clear()

        for agent_result in result.individual_results:
            emoji = _get_status_emoji(agent_result.confidence_score)
            status = f"{emoji} {agent_result.confidence_score:.0%}"
            time_str = f"{agent_result.execution_time_ms:.0f}ms"
            preview = agent_result.response_text[:50].replace("\n", " ") + "..."

            table.add_row(
                agent_result.agent_name,
                agent_result.approach_used,
                status,
                time_str,
                preview,
            )

    def _update_confidence_bars(self, result) -> None:
        """Update or create confidence progress bars."""
        section = self.query_one("#confidence-section", Vertical)

        # Remove old bars (keep header)
        for child in list(section.children)[1:]:
            child.remove()

        # Add progress bars for each agent
        for agent_result in result.individual_results:
            with Horizontal(classes="confidence-row"):
                label = Static(
                    f"{agent_result.agent_name}:",
                    classes="confidence-label",
                )
                bar = ProgressBar(
                    total=100,
                    show_eta=False,
                    show_percentage=True,
                    classes="confidence-bar",
                )
                bar.progress = int(agent_result.confidence_score * 100)

                # Color based on confidence
                if agent_result.confidence_score >= 0.8:
                    bar.update_styles("bar--complete", "green")
                elif agent_result.confidence_score >= 0.5:
                    bar.update_styles("bar--complete", "yellow")
                else:
                    bar.update_styles("bar--complete", "red")

                section.mount(label)
                section.mount(bar)

    def _update_transcript(self, result) -> None:
        """Update the debate transcript panel."""
        log = self.query_one("#transcript-log", RichLog)
        log.clear()

        if result.debate_transcript:
            log.write(result.debate_transcript)
        else:
            log.write("[dim]No debate transcript available.[/dim]")
            log.write("")
            log.write("[dim]Individual agent responses:[/dim]")
            for agent in result.individual_results:
                log.write(f"\n[bold cyan]{agent.agent_name}[/bold cyan] ({agent.approach_used}):")
                log.write(f"[dim]{agent.response_text[:200]}...[/dim]")

    def _log_transcript(self, message: str) -> None:
        """Add a message to the transcript log."""
        log = self.query_one("#transcript-log", RichLog)
        log.write(message)

    def _update_summary(self, result) -> None:
        """Update the consensus summary panel."""
        summary = self.query_one("#consensus-summary", Static)

        lines = []

        # Consensus status
        if result.consensus_reached:
            lines.append("[green bold]✓ Consensus Reached[/green bold]")
        else:
            lines.append("[yellow bold]⚠ No Consensus[/yellow bold]")

        lines.append("")

        # Stats
        avg_conf = result.get_average_confidence()
        agreement = result.get_agreement_ratio()

        lines.append(f"Average Confidence: {avg_conf:.0%}")
        lines.append(f"Agreement Ratio: {agreement:.0%}")
        lines.append(f"Agents Run: {len(result.individual_results)}")

        if result.execution_stats:
            lines.append("")
            lines.append("[dim]Execution Stats:[/dim]")
            total_time = result.execution_stats.get("total_time_ms", 0)
            lines.append(f"  Total Time: {total_time:.0f}ms")
            successful = result.execution_stats.get("successful_runs", 0)
            lines.append(f"  Successful: {successful}/{len(result.individual_results)}")

        lines.append("")
        lines.append("[dim]Press 'a' to accept, 'r' to re-run, 'd' for details[/dim]")

        summary.update("\n".join(lines))

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        button_id = event.button.id

        if button_id == "btn-accept":
            self.action_accept_consensus()
        elif button_id == "btn-rerun":
            self.action_rerun_swarm()
        elif button_id == "btn-details":
            self.action_view_details()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_accept_consensus(self) -> None:
        """Accept the consensus result and close the screen."""
        if self.swarm_result:
            self.dismiss({
                "action": "accept",
                "result": self.swarm_result,
            })
        else:
            self.dismiss(None)

    def action_rerun_swarm(self) -> None:
        """Re-run the swarm with the same task."""
        if not self.is_running:
            self._agent_results = []
            self._setup_table()
            self._start_swarm_execution()

    def action_view_details(self) -> None:
        """Show detailed view of the swarm result."""
        if not self.swarm_result:
            return

        # Show detailed view in transcript panel
        log = self.query_one("#transcript-log", RichLog)
        log.clear()

        result = self.swarm_result
        log.write("[bold cyan]=== DETAILED SWARM RESULT ===[/bold cyan]\n")
        log.write(f"[bold]Consensus Reached:[/bold] {result.consensus_reached}")
        log.write(f"[bold]Average Confidence:[/bold] {result.get_average_confidence():.2f}")
        log.write(f"[bold]Agreement Ratio:[/bold] {result.get_agreement_ratio():.2f}")
        log.write("")

        log.write("[bold cyan]Final Answer:[/bold cyan]")
        log.write(result.final_answer)
        log.write("")

        log.write("[bold cyan]Individual Responses:[/bold cyan]")
        for agent in result.individual_results:
            log.write(f"\n[bold]{agent.agent_name}[/bold] ({agent.approach_used})")
            log.write(f"Confidence: {agent.confidence_score:.2f} | Time: {agent.execution_time_ms:.0f}ms")
            log.write(f"Response: {agent.response_text}")
            log.write("---")

    def action_toggle_consensus_only(self) -> None:
        """Toggle showing only consensus-level results."""
        self.show_consensus_only = not self.show_consensus_only
        if self.swarm_result:
            self._populate_results_table(self.swarm_result)

    # ------------------------------------------------------------------
    # Watchers
    # ------------------------------------------------------------------

    def watch_is_running(self, running: bool) -> None:
        """Update UI when running state changes."""
        try:
            buttons = self.query_one("#action-buttons", Horizontal)
            for button in buttons.query(Button):
                button.disabled = running
        except Exception:
            # DOM not ready yet, ignore
            pass


# ---------------------------------------------------------------------------
# Standalone runner for testing
# ---------------------------------------------------------------------------


async def run_swarm_screen(task_prompt: str, task_type: str = "default") -> dict | None:
    """Run the swarm screen standalone and return the result.

    Args:
        task_prompt: The task to run swarm consensus on
        task_type: Type of task for approach selection

    Returns:
        Dict with action and result, or None if cancelled
    """
    from textual.app import App

    class SwarmApp(App):
        def compose(self) -> ComposeResult:
            yield SwarmScreen(task_prompt=task_prompt, task_type=task_type)

    app = SwarmApp()
    result = None

    def on_dismiss(value):
        nonlocal result
        result = value

    screen = SwarmScreen(task_prompt=task_prompt, task_type=task_type)
    app.push_screen(screen, on_dismiss)
    await app.run_async()

    return result
