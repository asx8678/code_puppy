"""Acceleration status slash command.

Provides /accel status to show the hybrid Zig/Rust acceleration configuration.
"""

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info


def _custom_help() -> list[tuple[str, str]]:
    return [
        ("accel", "Show acceleration backend status (Zig/Rust hybrid)"),
        ("accel status", "Detailed acceleration backend information"),
    ]


def _format_status_badge(status: str, active: bool) -> Text:
    """Format a status badge with color."""
    if active:
        return Text("● active", style="bold green")
    elif status == "disabled":
        return Text("● disabled", style="dim")
    else:
        return Text("○ unavailable", style="yellow")


def _render_accel_status_panel() -> Panel:
    """Render the acceleration status panel with hybrid backend info."""
    from code_puppy.acceleration import get_backend_info
    from code_puppy.config import get_acceleration_config

    try:
        config = get_acceleration_config()
        info = get_backend_info()
    except Exception as e:
        return Panel(
            f"Error loading acceleration status: {e}",
            title="Acceleration Status",
            border_style="red"
        )

    # Build status lines
    lines = []

    # Header
    lines.append(Text("Hybrid Architecture: Rust + Zig", style="bold cyan"))
    lines.append(Text(""))

    # puppy_core (Rust)
    puppy_core = info.get("puppy_core", {})
    badge = _format_status_badge(
        puppy_core.get("status", "unknown"),
        puppy_core.get("active", False)
    )
    lines.append(Text.assemble(
        "  puppy_core  ",
        (f"({puppy_core.get('configured', 'python')}) ", "dim"),
        badge
    ))
    lines.append(Text("              Message processing, session serialization", style="dim"))
    lines.append(Text(""))

    # turbo_parse (Rust)
    turbo_parse = info.get("turbo_parse", {})
    badge = _format_status_badge(
        turbo_parse.get("status", "unknown"),
        turbo_parse.get("active", False)
    )
    lines.append(Text.assemble(
        "  turbo_parse ",
        (f"({turbo_parse.get('configured', 'python')}) ", "dim"),
        badge
    ))
    lines.append(Text("              Tree-sitter grammars, syntax highlighting", style="dim"))
    lines.append(Text(""))

    # turbo_ops (Zig)
    turbo_ops = info.get("turbo_ops", {})
    badge = _format_status_badge(
        turbo_ops.get("status", "unknown"),
        turbo_ops.get("active", False)
    )
    lines.append(Text.assemble(
        "  turbo_ops   ",
        (f"({turbo_ops.get('configured', 'python')}) ", "dim"),
        badge
    ))
    lines.append(Text("              File I/O, directory listing, grep", style="dim"))
    lines.append(Text(""))

    # Configuration hint
    lines.append(Text("Configuration via environment:", style="bold"))
    lines.append(Text("  PUP_ACCEL_PUPPY_CORE=rust|zig|python", style="dim"))
    lines.append(Text("  PUP_ACCEL_TURBO_PARSE=rust|zig|python", style="dim"))
    lines.append(Text("  PUP_ACCEL_TURBO_OPS=rust|zig|python", style="dim"))

    content = Group(*lines)
    return Panel(
        content,
        title="Acceleration Status",
        border_style="cyan"
    )


def _handle_accel_command(command: str, name: str) -> bool | None:
    """Handle /accel commands."""
    if not name:
        return None

    if name != "accel":
        return None

    # Parse subcommand if any
    tokens = command.strip().split()
    subcommand = tokens[1] if len(tokens) > 1 else "status"

    if subcommand == "status":
        panel = _render_accel_status_panel()
        emit_info(panel)
        return True
    elif subcommand == "help":
        emit_info("Usage: /accel status - Show acceleration backend configuration")
        return True
    else:
        emit_info(f"Unknown accel subcommand: {subcommand}. Use 'status' or 'help'.")
        return True


register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_accel_command)
