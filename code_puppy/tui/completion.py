"""Tab completion system for the Code Puppy TUI input.

Provides slash command completion, file path completion, and model/agent
completion. Shows results in an OptionList overlay above the input.
"""

import glob
import os
from dataclasses import dataclass, field


@dataclass
class CompletionItem:
    """A single completion suggestion."""

    text: str
    display: str = ""
    description: str = ""

    def __post_init__(self):
        if not self.display:
            self.display = self.text


def get_completions(text: str, cursor_pos: int | None = None) -> list[CompletionItem]:
    """Get completions for the current input text.

    This is the main dispatcher. It checks what kind of completion
    is needed based on the input text and delegates to specific completers.

    Args:
        text: Current input text
        cursor_pos: Cursor position (defaults to end of text)

    Returns:
        List of CompletionItem suggestions
    """
    if cursor_pos is None:
        cursor_pos = len(text)

    text_before_cursor = text[:cursor_pos].lstrip()

    # Slash command completion: /com...
    if text_before_cursor.startswith("/"):
        return _complete_slash_command(text_before_cursor)

    # @ file path completion: @src/...
    if "@" in text_before_cursor:
        return _complete_file_path(text_before_cursor)

    return []


def _complete_slash_command(text: str) -> list[CompletionItem]:
    """Complete slash commands like /model, /settings, /help.

    Also handles subcommands:
    - /model <name> — completes model names
    - /agent <name> — completes agent names
    - /set <key> — completes config keys
    - /cd <path> — completes directory paths
    """
    parts = text.split(None, 1)  # Split on first whitespace
    command = parts[0]  # e.g., "/model"

    if len(parts) == 1 and not text.endswith(" "):
        # Still typing the command name — complete commands
        return _complete_command_names(command)

    # We have a command + subcommand/argument
    arg = parts[1] if len(parts) > 1 else ""
    cmd_lower = command.lower()

    if cmd_lower in ("/model", "/m"):
        return _complete_model_names(arg)
    elif cmd_lower in ("/agent", "/a"):
        return _complete_agent_names(arg)
    elif cmd_lower == "/set":
        return _complete_config_keys(arg)
    elif cmd_lower == "/cd":
        return _complete_directories(arg)

    return []


def _complete_command_names(partial: str) -> list[CompletionItem]:
    """Complete slash command names from the command registry."""
    # Strip the leading /
    partial_name = partial[1:].lower() if partial.startswith("/") else partial.lower()

    items = []
    try:
        from code_puppy.command_line.command_registry import get_unique_commands

        commands = get_unique_commands()

        for cmd in commands:
            if cmd.name.lower().startswith(partial_name):
                items.append(
                    CompletionItem(
                        text=f"/{cmd.name}",
                        display=f"/{cmd.name}",
                        description=cmd.description or "",
                    )
                )
            # Also check aliases
            for alias in getattr(cmd, "aliases", []):
                if alias.lower().startswith(partial_name):
                    items.append(
                        CompletionItem(
                            text=f"/{alias}",
                            display=f"/{alias} → /{cmd.name}",
                            description=cmd.description or "",
                        )
                    )
    except Exception:
        pass

    items.sort(key=lambda c: c.text.lower())
    return items


def _complete_model_names(partial: str) -> list[CompletionItem]:
    """Complete model names for /model command."""
    partial_lower = partial.lower()
    items = []
    try:
        from code_puppy.model_factory import ModelFactory

        models_config = ModelFactory.load_config()
        for name in sorted(models_config.keys()):
            if name.lower().startswith(partial_lower):
                items.append(CompletionItem(text=name, description="model"))
    except Exception:
        pass
    return items


def _complete_agent_names(partial: str) -> list[CompletionItem]:
    """Complete agent names for /agent command."""
    partial_lower = partial.lower()
    items = []
    try:
        from code_puppy.agents import get_available_agents

        agents = get_available_agents()
        for name in sorted(agents.keys()):
            display_name = agents[name]
            if name.lower().startswith(partial_lower):
                items.append(
                    CompletionItem(
                        text=name,
                        display=name,
                        description=display_name if isinstance(display_name, str) else str(display_name),
                    )
                )
    except Exception:
        pass
    return items


def _complete_config_keys(partial: str) -> list[CompletionItem]:
    """Complete config keys for /set command."""
    partial_lower = partial.lower()
    items = []
    try:
        from code_puppy.config import get_config_keys, get_value

        for key in sorted(get_config_keys()):
            if key == "puppy_token":
                continue
            if key.lower().startswith(partial_lower):
                current = get_value(key)
                desc = f"= {current}" if current is not None else ""
                items.append(CompletionItem(text=key, description=desc))
    except Exception:
        pass
    return items


def _complete_file_path(text: str) -> list[CompletionItem]:
    """Complete file paths after @ symbol."""
    # Find the last @ in the text
    at_pos = text.rfind("@")
    if at_pos == -1:
        return []

    partial_path = text[at_pos + 1:]
    items = []

    try:
        # Expand the path for globbing
        if partial_path:
            pattern = partial_path + "*"
        else:
            pattern = "*"

        matches = glob.glob(pattern)
        # Also try with the partial as a directory prefix
        if partial_path and not partial_path.endswith(os.sep):
            dir_pattern = partial_path + os.sep + "*"
            matches.extend(glob.glob(dir_pattern))

        seen: set[str] = set()
        for match in sorted(matches):
            if match in seen:
                continue
            seen.add(match)

            is_dir = os.path.isdir(match)
            display_path = match + os.sep if is_dir else match
            icon = "📁" if is_dir else "📄"

            items.append(
                CompletionItem(
                    text=match,
                    display=f"{icon} {display_path}",
                    description="directory" if is_dir else "",
                )
            )
    except Exception:
        pass

    return items[:50]  # Limit to 50 results


def _complete_directories(partial: str) -> list[CompletionItem]:
    """Complete directory paths for /cd command."""
    items = []
    try:
        expanded = os.path.expanduser(partial) if partial else "."
        if os.path.isdir(expanded):
            base = expanded
            prefix = ""
        else:
            base = os.path.dirname(expanded) or "."
            prefix = os.path.basename(expanded)

        for entry in sorted(os.listdir(base)):
            full = os.path.join(base, entry)
            if os.path.isdir(full) and entry.lower().startswith(prefix.lower()):
                display_path = os.path.join(base, entry) if base != "." else entry
                items.append(
                    CompletionItem(
                        text=display_path + os.sep,
                        display=f"📁 {entry}/",
                        description="directory",
                    )
                )
    except Exception:
        pass
    return items
