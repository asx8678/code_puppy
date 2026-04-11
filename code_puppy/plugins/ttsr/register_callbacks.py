"""Callback registrations for the Lazy TTSR plugin.

Wires together rule loading, stream watching, and prompt injection via
Code Puppy's plugin callback system.

Rule file locations (scanned on startup):
  - ``.code_puppy/rules/*.md``   — project-level rules
  - ``~/.code_puppy/rules/*.md`` — user-level rules
"""

import logging
from pathlib import Path
from typing import Any

from code_puppy.callbacks import register_callback

from .rule_loader import TtsrRule, load_rules_from_dir
from .stream_watcher import TtsrStreamWatcher

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_watcher: TtsrStreamWatcher | None = None


def _get_watcher() -> TtsrStreamWatcher:
    """Return the module-level watcher, initialising with empty rules if needed."""
    global _watcher
    if _watcher is None:
        _watcher = TtsrStreamWatcher([])
    return _watcher


# ---------------------------------------------------------------------------
# Rule directories
# ---------------------------------------------------------------------------


def _rule_directories() -> list[Path]:
    """Return candidate rule directories in priority order.

    Returns:
        List of :class:`~pathlib.Path` objects to scan for ``*.md`` rules.
        Lower-index entries take priority (project > user).
    """
    dirs: list[Path] = []

    # Project-level: .code_puppy/rules/ relative to cwd
    project_rules = Path.cwd() / ".code_puppy" / "rules"
    dirs.append(project_rules)

    # User-level: ~/.code_puppy/rules/
    user_rules = Path.home() / ".code_puppy" / "rules"
    dirs.append(user_rules)

    return dirs


# ---------------------------------------------------------------------------
# startup hook
# ---------------------------------------------------------------------------


def load_rules() -> None:
    """Discover and load all TTSR rule files.

    Called on the ``startup`` hook.  Scans project-level and user-level
    rule directories and populates the module-level watcher.
    """
    global _watcher

    all_rules: list[TtsrRule] = []
    for directory in _rule_directories():
        rules = load_rules_from_dir(directory)
        all_rules.extend(rules)

    _watcher = TtsrStreamWatcher(all_rules)

    if all_rules:
        logger.info("ttsr: loaded %d rule(s)", len(all_rules))
    else:
        logger.debug("ttsr: no rules found in rule directories")


# ---------------------------------------------------------------------------
# stream_event hook
# ---------------------------------------------------------------------------


def watch_stream(
    event_type: str,
    event_data: Any,
    agent_session_id: str | None = None,
) -> None:
    """Forward stream events to the TTSR watcher.

    Signature matches the ``stream_event`` callback:
    ``(event_type, event_data, agent_session_id=None) -> None``.

    Args:
        event_type: Type string of the streaming event.
        event_data: Associated event payload.
        agent_session_id: Optional session identifier.
    """
    watcher = _get_watcher()
    try:
        watcher.watch(event_type, event_data, agent_session_id)
    except Exception:
        logger.exception("ttsr: error in watch_stream")


# ---------------------------------------------------------------------------
# agent_run_end hook — advance the turn counter
# ---------------------------------------------------------------------------


def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Any = None,
    response_text: str | None = None,
    metadata: Any = None,
) -> None:
    """Increment the watcher turn counter after each agent run.

    Args:
        agent_name: Name of the agent that finished.
        model_name: Model used for the run.
        session_id: Optional session identifier.
        success: Whether the run succeeded.
        error: Any error that occurred.
        response_text: The response text (unused).
        metadata: Additional metadata (unused).
    """
    watcher = _get_watcher()
    watcher.increment_turn()
    logger.debug("ttsr: turn advanced to %d after agent_run_end", watcher.turn_count)


# ---------------------------------------------------------------------------
# load_prompt hook
# ---------------------------------------------------------------------------


def inject_triggered_rules() -> str | None:
    """Inject pending rule content into the system prompt.

    Called on the ``load_prompt`` hook before each model call.  Any rules
    flagged as ``pending`` are formatted as ``<system-rule>`` blocks,
    appended to the returned string, and then marked as injected.

    Returns:
        A string of ``<system-rule>`` blocks, or ``None`` if nothing is
        pending.
    """
    watcher = _get_watcher()
    pending = watcher.get_pending_rules()

    if not pending:
        return None

    current_turn = watcher.turn_count
    parts: list[str] = []

    for rule in pending:
        block = f'\n\n<system-rule name="{rule.name}">\n{rule.content}\n</system-rule>'
        parts.append(block)
        watcher.mark_injected(rule, current_turn)
        logger.info(
            "ttsr: injecting rule %r into system prompt at turn %d",
            rule.name,
            current_turn,
        )

    return "".join(parts)


# ---------------------------------------------------------------------------
# custom_command hook — /ttsr
# ---------------------------------------------------------------------------


def handle_ttsr_command(command: str, name: str) -> bool | None:
    """Handle the ``/ttsr`` slash command.

    Shows all loaded rules with their trigger patterns and current status.

    Args:
        command: The full command string (e.g. ``"/ttsr"``).
        name: The command name extracted by the dispatcher (e.g. ``"ttsr"``).

    Returns:
        ``True`` if handled, ``None`` to pass to the next handler.
    """
    if name != "ttsr":
        return None

    try:
        from code_puppy.messaging import emit_info, emit_warning
    except ImportError:
        print("[ttsr] messaging not available")
        return True

    watcher = _get_watcher()
    rules = watcher.rules

    if not rules:
        emit_warning(
            "🔭 TTSR: No rules loaded.\n"
            "Add ``*.md`` files to ``.code_puppy/rules/`` or "
            "``~/.code_puppy/rules/`` to get started."
        )
        return True

    lines: list[str] = [
        f"🔭 **TTSR** — {len(rules)} rule(s) loaded  (turn {watcher.turn_count})\n"
    ]

    for rule in rules:
        status_parts: list[str] = []

        if rule.pending:
            status_parts.append("⏳ pending injection")
        elif rule.triggered_at_turn is not None:
            if rule.repeat == "once":
                status_parts.append(
                    f"✅ injected at turn {rule.triggered_at_turn} (won't repeat)"
                )
            else:
                gap = int(rule.repeat[4:])
                turns_since = watcher.turn_count - rule.triggered_at_turn
                remaining = max(0, gap - turns_since)
                if remaining == 0:
                    status_parts.append("🔄 eligible again")
                else:
                    status_parts.append(
                        f"⏱ repeat in {remaining} turn(s) "
                        f"(last: turn {rule.triggered_at_turn})"
                    )
        else:
            status_parts.append("💤 not yet triggered")

        status = ", ".join(status_parts) if status_parts else "—"

        lines.append(
            f"  **{rule.name}**  "
            f"scope=`{rule.scope}`  repeat=`{rule.repeat}`\n"
            f"    trigger: `{rule.trigger.pattern}`\n"
            f"    status: {status}\n"
            f"    source: {rule.source_path}\n"
        )

    emit_info("\n".join(lines))
    return True


# ---------------------------------------------------------------------------
# custom_command_help hook
# ---------------------------------------------------------------------------


def ttsr_help() -> list[tuple[str, str]]:
    """Return help entries for the ``/ttsr`` command.

    Returns:
        List of ``(name, description)`` tuples for the help menu.
    """
    return [
        (
            "ttsr",
            "Show loaded TTSR rules and their trigger/injection status",
        ),
    ]


# ---------------------------------------------------------------------------
# Register all callbacks
# ---------------------------------------------------------------------------

register_callback("startup", load_rules)
register_callback("stream_event", watch_stream)
register_callback("load_prompt", inject_triggered_rules)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("custom_command", handle_ttsr_command)
register_callback("custom_command_help", ttsr_help)

logger.debug("ttsr plugin registered")
