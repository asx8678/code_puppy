"""
/render-check - Visual diagnostic command for verifying terminal rendering.

Prints a comprehensive test pattern exercising Rich features:
- Plain and styled text
- Panels with borders
- Tables
- Markdown rendering
- Syntax-highlighted code
- Progress bar
- Status spinner
- Color palette

Users run `/render-check` to verify their terminal is rendering correctly.
If anything looks wrong, they have evidence of the specific failure.
"""

from __future__ import annotations

import os
import sys
import time

from code_puppy.callbacks import register_callback
from code_puppy.console import build_console

COMMAND_NAME = "render-check"
COMMAND_ALIASES = ("rendercheck", "check-render")


def _get_console():
    """Get a Console honoring CODE_PUPPY_NO_COLOR and CODE_PUPPY_FORCE_COLOR."""
    return build_console()


def _print_header(console, title: str) -> None:
    from rich.rule import Rule

    console.print()
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]", style="cyan"))


def _test_plain_and_styled(console) -> None:
    _print_header(console, "1. Plain and Styled Text")
    console.print("This is plain text.")
    console.print(
        "[bold]Bold[/bold] [italic]italic[/italic] [underline]underline[/underline]"
    )
    console.print(
        "[red]red[/red] [green]green[/green] [blue]blue[/blue] [yellow]yellow[/yellow] [magenta]magenta[/magenta] [cyan]cyan[/cyan]"
    )
    console.print(
        "[bold red on white] alert [/bold red on white] [bold green on black] ok [/bold green on black]"
    )


def _test_panels(console) -> None:
    from rich.panel import Panel

    _print_header(console, "2. Panels")
    console.print(Panel("This is a panel with default styling.", title="Default"))
    console.print(
        Panel.fit(
            "[bold yellow]Warning![/bold yellow] Fit panel with rich content.",
            border_style="yellow",
            title="Warning",
        )
    )
    console.print(
        Panel(
            "[green]Success[/green] — operation completed.",
            border_style="green",
            title="Success",
            subtitle="[dim]subtitle[/dim]",
        )
    )


def _test_tables(console) -> None:
    from rich.table import Table

    _print_header(console, "3. Tables")
    table = Table(title="Sample Table", show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim", width=6)
    table.add_column("Name")
    table.add_column("Status", justify="right")
    table.add_row("001", "alpha", "[green]ok[/green]")
    table.add_row("002", "beta", "[yellow]pending[/yellow]")
    table.add_row("003", "gamma", "[red]failed[/red]")
    console.print(table)


def _test_markdown(console) -> None:
    from rich.markdown import Markdown

    _print_header(console, "4. Markdown")
    md_source = (
        "# Heading 1\n\n"
        "## Heading 2\n\n"
        "Regular paragraph with **bold** and *italic* and `inline code`.\n\n"
        "- Bullet one\n"
        "- Bullet two\n"
        "- Bullet three\n\n"
        "1. Numbered\n"
        "2. List\n\n"
        "> A blockquote for good measure.\n\n"
        "```python\n"
        "def greet(name: str) -> str:\n"
        "    return f'Hello, {name}!'\n"
        "```\n"
    )
    console.print(Markdown(md_source))


def _test_syntax(console) -> None:
    from rich.syntax import Syntax

    _print_header(console, "5. Syntax Highlighting")
    code = (
        "from typing import Iterator\n\n"
        "def fibonacci(n: int) -> Iterator[int]:\n"
        "    a, b = 0, 1\n"
        "    for _ in range(n):\n"
        "        yield a\n"
        "        a, b = b, a + b\n\n"
        "print(list(fibonacci(10)))\n"
    )
    console.print(Syntax(code, "python", theme="monokai", line_numbers=True))


def _test_progress(console) -> None:
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn

    _print_header(console, "6. Progress Bar (2 seconds)")
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("rendering test…", total=20)
            for _ in range(20):
                time.sleep(0.1)
                progress.advance(task)
    except Exception as e:
        console.print(f"[red]Progress test failed:[/red] {e}")


def _test_colors(console) -> None:
    _print_header(console, "7. 256 Color Palette Sample")
    for row in range(4):
        line = ""
        for col in range(16):
            idx = row * 16 + col
            line += f"[on color({idx})]  [/on color({idx})]"
        console.print(line)


def _test_environment(console) -> None:
    from rich.table import Table

    _print_header(console, "8. Environment Diagnostics")
    t = Table(show_header=False, box=None)
    t.add_column("Key", style="cyan")
    t.add_column("Value")
    t.add_row("sys.stdout.isatty()", str(sys.stdout.isatty()))
    t.add_row("TERM", os.environ.get("TERM", "<unset>"))
    t.add_row("COLORTERM", os.environ.get("COLORTERM", "<unset>"))
    t.add_row("NO_COLOR", os.environ.get("NO_COLOR", "<unset>"))
    t.add_row("CODE_PUPPY_NO_COLOR", os.environ.get("CODE_PUPPY_NO_COLOR", "<unset>"))
    t.add_row(
        "CODE_PUPPY_FORCE_COLOR", os.environ.get("CODE_PUPPY_FORCE_COLOR", "<unset>")
    )
    t.add_row("console.is_terminal", str(console.is_terminal))
    t.add_row("console.color_system", str(console.color_system))
    t.add_row("console.width", str(console.width))
    t.add_row("console.encoding", str(console.encoding))
    console.print(t)


def _run_render_check() -> None:
    console = _get_console()
    console.print()
    console.print("[bold cyan]🐕 Code Puppy — Render Check[/bold cyan]")
    console.print(
        "[dim]If anything below looks wrong, your terminal may not support certain Rich features.[/dim]"
    )
    try:
        _test_plain_and_styled(console)
        _test_panels(console)
        _test_tables(console)
        _test_markdown(console)
        _test_syntax(console)
        _test_progress(console)
        _test_colors(console)
        _test_environment(console)
        console.print()
        console.print("[bold green]✓ Render check complete.[/bold green]")
        console.print(
            "[dim]Tip: set CODE_PUPPY_FORCE_COLOR=1 to force colors when piping, or CODE_PUPPY_NO_COLOR=1 to disable.[/dim]"
        )
        console.print()
    except Exception as e:
        console.print(f"[bold red]✗ Render check failed:[/bold red] {e}")


def _on_custom_command(command: str, name: str):
    """Handle /render-check and its aliases."""
    if name in (COMMAND_NAME, *COMMAND_ALIASES):
        try:
            _run_render_check()
        except Exception as e:
            print(f"render-check plugin error: {e}")
        return True
    return None


def _on_custom_command_help():
    return [
        (f"/{COMMAND_NAME}", "Run a visual test pattern to verify terminal rendering")
    ]


register_callback("custom_command", _on_custom_command)
register_callback("custom_command_help", _on_custom_command_help)
