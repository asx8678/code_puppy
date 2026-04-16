"""Scheduler screen — Textual replacement for scheduler_menu.py.

Two-panel layout:
  Left  — searchable list of scheduled tasks with status badges
  Right — RichLog with task details (name, schedule, agent, model, prompt, last run)

Key bindings:
  Enter — toggle enable/disable for selected task
  n     — open wizard to create new task
  r     — refresh task list
  Escape/q — back

Wired via: /scheduler → app.py pushes SchedulerScreen
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, RichLog, Static

from code_puppy.tui.base_screen import MenuScreen
from code_puppy.tui.widgets.searchable_list import SearchableList, SearchableListItem
from code_puppy.tui.widgets.split_panel import SplitPanel


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _load_tasks() -> list:
    """Return scheduled tasks, or [] on error."""
    try:
        from code_puppy.scheduler.config import load_tasks

        return load_tasks()
    except Exception:
        return []


def _get_daemon_info() -> tuple[int | None, str]:
    """Return (pid, status_label)."""
    try:
        from code_puppy.scheduler.daemon import get_daemon_pid

        pid = get_daemon_pid()
        if pid:
            return pid, f"[green]RUNNING (PID {pid})[/green]"
        return None, "[red]STOPPED[/red]"
    except Exception:
        return None, "[dim]unknown[/dim]"


def _status_icon(task) -> tuple[str, str]:
    """Return (icon, color) for a task."""
    if not task.enabled:
        return ("⏸", "yellow")
    if task.last_status == "running":
        return ("⏳", "cyan")
    if task.last_status == "success":
        return ("✓", "green")
    if task.last_status == "failed":
        return ("✗", "red")
    return ("○", "dim")


# ---------------------------------------------------------------------------
# Screen
# ---------------------------------------------------------------------------


class SchedulerScreen(MenuScreen):
    """Scheduled tasks browser — replaces prompt_toolkit SchedulerMenu.

    Left panel: searchable list of all tasks.
    Right panel: rich detail view for highlighted task.

    Enter toggles enable/disable. 'n' opens the creation wizard.
    """

    BINDINGS = MenuScreen.BINDINGS + [
        Binding("enter", "toggle_task", "Toggle", show=True),
        Binding("n", "new_task", "New Task", show=True),
        Binding("r", "refresh", "Refresh", show=False),
    ]

    DEFAULT_CSS = """
    SchedulerScreen {
        layers: default;
    }
    SchedulerScreen > #screen-title {
        dock: top;
        height: 1;
        background: $primary-darken-2;
        color: $text;
        text-style: bold;
        padding: 0 2;
    }
    SchedulerScreen SplitPanel {
        height: 1fr;
    }
    SchedulerScreen .split-panel--left {
        width: 38%;
        min-width: 26;
        border-right: solid $primary-lighten-2;
    }
    SchedulerScreen .split-panel--right {
        width: 1fr;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tasks: list = []

    # ------------------------------------------------------------------
    # Compose / Mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("", id="screen-title")
        with SplitPanel(left_title="Tasks", right_title="Details"):
            yield SearchableList(
                placeholder="🔍 Search tasks...",
                id="task-list",
                classes="split-panel--left",
            )
            yield RichLog(
                id="details-panel",
                classes="split-panel--right",
                markup=True,
                highlight=False,
                wrap=True,
            )
        yield Footer()

    def on_mount(self) -> None:
        """Load tasks."""
        self._refresh_data()
        self._populate_list()
        self.query_one("#task-list", SearchableList).focus()
        details = self.query_one("#details-panel", RichLog)
        details.write("[dim]Select a task to see details.[/dim]")
        details.write("[dim]Enter=Toggle · n=New · r=Refresh · Esc=Back[/dim]")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_data(self) -> None:
        self._tasks = _load_tasks()
        _, daemon_status = _get_daemon_info()
        enabled_count = sum(1 for t in self._tasks if t.enabled)
        try:
            self.query_one("#screen-title", Static).update(
                f"📅  Scheduler — Daemon: {daemon_status}"
                f"  ({enabled_count}/{len(self._tasks)} enabled)"
            )
        except Exception:
            pass

    def _populate_list(self) -> None:
        items: list[SearchableListItem] = []
        for task in self._tasks:
            icon, _ = _status_icon(task)
            status_label = "enabled" if task.enabled else "disabled"
            badge = f"{icon} {status_label}"
            items.append(
                SearchableListItem(
                    label=task.name[:40],
                    item_id=task.id,
                    badge=badge,
                    disabled=not task.enabled,
                )
            )
        task_list = self.query_one("#task-list", SearchableList)
        task_list.add_items(items)

    def _render_task_details(self, task_id: str) -> None:
        details = self.query_one("#details-panel", RichLog)
        details.clear()

        task = None
        for t in self._tasks:
            if t.id == task_id:
                task = t
                break

        if task is None:
            details.write("[dim]Select a task to see details.[/dim]")
            return

        icon, color = _status_icon(task)
        status_label = "Enabled" if task.enabled else "Disabled"

        details.write(f"[bold cyan]{task.name}[/bold cyan]")
        details.write(
            f"  [bold]Status:[/bold] [{color}]{icon} {status_label}[/{color}]"
        )
        details.write(f"  [bold]ID:[/bold]     [dim]{task.id}[/dim]")
        details.write("")

        details.write(
            f"  [bold]Schedule:[/bold] {task.schedule_type} ({task.schedule_value})"
        )
        details.write(f"  [bold]Agent:[/bold]    [cyan]{task.agent}[/cyan]")
        if task.model:
            details.write(f"  [bold]Model:[/bold]    [cyan]{task.model}[/cyan]")
        details.write(f"  [bold]Dir:[/bold]      [dim]{task.working_directory}[/dim]")
        details.write("")

        # Prompt preview
        prompt_preview = (
            task.prompt[:200] + "..." if len(task.prompt) > 200 else task.prompt
        )
        details.write("[bold]Prompt[/bold]")
        for line in prompt_preview.split("\n")[:5]:
            details.write(f"  [dim]{line}[/dim]")
        details.write("")

        # Last run info
        if task.last_run:
            details.write("[bold]Last Run[/bold]")
            details.write(f"  [dim]{task.last_run[:19]}[/dim]")
            if task.last_exit_code is not None:
                exit_color = "green" if task.last_exit_code == 0 else "red"
                details.write(
                    f"  Exit code: [{exit_color}]{task.last_exit_code}[/{exit_color}]"
                )
            details.write("")

        # Created
        if task.created_at:
            details.write(f"  [dim]Created: {task.created_at[:19]}[/dim]")
        details.write("")
        details.write("[dim]Enter=Toggle · n=New · Esc=Back[/dim]")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_searchable_list_item_highlighted(
        self, event: SearchableList.ItemHighlighted
    ) -> None:
        self._render_task_details(event.item.item_id)

    def on_searchable_list_item_selected(
        self, event: SearchableList.ItemSelected
    ) -> None:
        self.action_toggle_task()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_toggle_task(self) -> None:
        """Toggle enabled/disabled for the highlighted task."""
        task_list = self.query_one("#task-list", SearchableList)
        item = task_list.highlighted_item
        if item is None:
            return
        try:
            from code_puppy.scheduler.config import toggle_task

            toggle_task(item.item_id)
        except Exception:
            pass
        self._refresh_data()
        self._populate_list()
        self._render_task_details(item.item_id)

    def action_new_task(self) -> None:
        """Open the scheduler wizard to create a new task."""
        from code_puppy.tui.screens.scheduler_wizard_screen import SchedulerWizardScreen

        def _on_created(task_data: dict | None) -> None:
            if task_data:
                try:
                    from code_puppy.scheduler.config import ScheduledTask, add_task

                    task = ScheduledTask(
                        name=task_data["name"],
                        prompt=task_data["prompt"],
                        agent=task_data.get("agent", "code-puppy"),
                        model=task_data.get("model", ""),
                        schedule_type=task_data.get("schedule_type", "interval"),
                        schedule_value=task_data.get("schedule_value", "1h"),
                        working_directory=task_data.get("working_directory", "."),
                    )
                    add_task(task)
                except Exception:
                    pass
                self._refresh_data()
                self._populate_list()

        self.app.push_screen(SchedulerWizardScreen(), callback=_on_created)

    def action_refresh(self) -> None:
        """Reload tasks from disk."""
        self._refresh_data()
        self._populate_list()
        details = self.query_one("#details-panel", RichLog)
        details.clear()
        details.write("[dim]Refreshed.[/dim]")
