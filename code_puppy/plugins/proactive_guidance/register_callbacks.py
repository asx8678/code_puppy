"""Proactive Guidance Plugin - Next-step suggestions after tool execution.

This plugin provides contextual guidance and follow-up suggestions after
tools like write_file, run_shell_command, and invoke_agent are executed.

Configuration (puppy.cfg):
    [default]
    proactive_guidance_enabled = true  # Enable/disable the plugin
    guidance_verbosity = normal      # minimal|normal|verbose

Hooks:
    - post_tool_call: Injects next-step guidance after tool execution
    - custom_command: Provides /guidance command for status/toggle
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from code_puppy.callbacks import register_callback

# ---------------------------------------------------------------------------
# Config helpers (lazy-imported to avoid cycles at plugin load time)
# ---------------------------------------------------------------------------

_CONFIG_KEY_ENABLED = "proactive_guidance_enabled"
_CONFIG_KEY_VERBOSITY = "guidance_verbosity"
_VALID_VERBOSITY = {"minimal", "normal", "verbose"}

# Track state
_state: dict[str, Any] = {
    "enabled": True,
    "verbosity": "normal",
    "last_tool": None,
    "guidance_count": 0,
}


def _get_config_enabled() -> bool:
    """Read the enabled state from puppy.cfg; default to True."""
    try:
        from code_puppy.config import get_value

        raw = get_value(_CONFIG_KEY_ENABLED)
        if raw is not None:
            return raw.strip().lower() in ("true", "1", "yes", "on")
    except Exception:
        pass
    return True


def _get_config_verbosity() -> str:
    """Read verbosity from puppy.cfg; default to 'normal'."""
    try:
        from code_puppy.config import get_value

        raw = get_value(_CONFIG_KEY_VERBOSITY)
        if raw and raw.strip().lower() in _VALID_VERBOSITY:
            return raw.strip().lower()
    except Exception:
        pass
    return "normal"


def _is_enabled() -> bool:
    """Check if guidance is enabled (config + runtime state)."""
    return _state["enabled"] and _get_config_enabled()


# ---------------------------------------------------------------------------
# Guidance generators
# ---------------------------------------------------------------------------


def _get_write_guidance(file_path: str, content_preview: str | None = None) -> str | None:
    """Generate guidance after write_file tool usage.

    Args:
        file_path: Path to the file that was written
        content_preview: Optional preview of content for context

    Returns:
        Guidance string or None if no guidance applicable
    """
    verbosity = _state.get("verbosity", "normal")
    path = Path(file_path)
    extension = path.suffix.lower()

    suggestions = []

    # Check file type and offer relevant next steps
    if extension in (".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".java"):
        suggestions.append(f"💡 Run tests: `/shell pytest {file_path}` or `/shell npm test`")
        suggestions.append(f"🔍 Check syntax: `/shell python -m py_compile {file_path}`")

    elif extension in (".md", ".rst", ".txt"):
        suggestions.append("📝 Preview: `/shell cat {} | head -20`".format(file_path))

    elif extension in (".json", ".yaml", ".yml", ".toml"):
        suggestions.append(f"✅ Validate: `/shell python -c 'import json; json.load(open(\"{file_path}\"))'`")

    elif extension in (".sh", ".bash", ".zsh"):
        suggestions.append(f"🔐 Check script: `/shell shellcheck {file_path}` (if installed)")
        suggestions.append(f"▶️ Make executable: `/shell chmod +x {file_path}`")

    # General suggestions for all files
    if verbosity != "minimal":
        suggestions.append(f"📂 View file: `/file {file_path}`")
        suggestions.append("🔎 Search for usages: `/grep pattern directory`")

    if verbosity == "verbose":
        suggestions.append("🧪 Create a test file for this implementation")
        suggestions.append("📊 Check git diff: `/shell git diff --stat`")

    if not suggestions:
        return None

    return "\n".join(["✨ Next steps for your new file:"] + suggestions[:4])


def _get_shell_guidance(command: str, exit_code: int = 0) -> str | None:
    """Generate guidance after run_shell_command tool usage.

    Args:
        command: The shell command that was executed
        exit_code: Exit code from the command (0 = success)

    Returns:
        Guidance string or None if no guidance applicable
    """
    verbosity = _state.get("verbosity", "normal")
    suggestions = []

    # Parse command to understand context
    cmd_lower = command.lower().strip()

    # Success case
    if exit_code == 0:
        if any(x in cmd_lower for x in ("pytest", "test", "npm test", "cargo test")):
            suggestions.append("✅ Tests passed! Ready to commit? `/git commit -m '...'`")
            if verbosity != "minimal":
                suggestions.append("📊 Coverage report: `/shell pytest --cov` (if pytest-cov installed)")

        elif any(x in cmd_lower for x in ("git add", "git commit")):
            suggestions.append("🚀 Push changes: `/shell git push origin $(git branch --show-current)`")
            if verbosity == "verbose":
                suggestions.append("🔄 Or create PR: `/shell gh pr create` (if gh CLI installed)")

        elif any(x in cmd_lower for x in ("build", "make", "cargo build", "npm run build")):
            suggestions.append("🎯 Build succeeded! Run it: `/shell ./your_binary`")
            if verbosity != "minimal":
                suggestions.append("📦 Or package: Check your build artifacts")

        elif "pip install" in cmd_lower or "npm install" in cmd_lower or "cargo add" in cmd_lower:
            suggestions.append("📦 Dependencies updated! Consider locking: `/shell pip freeze > requirements.txt`")

        elif "grep" in cmd_lower or "find" in cmd_lower:
            suggestions.append("🔍 Found matches! Open a file: `/file path/to/file.py`")

        elif "ls" in cmd_lower or "tree" in cmd_lower:
            suggestions.append("📂 Explore further: `/files directory` for detailed listing")

        else:
            suggestions.append("✅ Command completed successfully!")

    # Error case
    else:
        suggestions.append(f"⚠️ Command failed with exit code {exit_code}")
        suggestions.append("🔧 Debug options:")
        suggestions.append("   - Check error output above")
        suggestions.append("   - Run with verbose: Add `-v` or `--verbose` flags")
        suggestions.append("   - Check environment: `/shell env | grep -i <key>`")

    if verbosity != "minimal" and exit_code == 0:
        suggestions.append("📜 Run similar command: Use ↑ or `/shell your_command`")

    return "\n".join(suggestions)


def _get_agent_guidance(agent_name: str, result_preview: str | None = None) -> str | None:
    """Generate guidance after invoke_agent tool usage.

    Args:
        agent_name: Name of the agent that was invoked
        result_preview: Optional preview of agent result

    Returns:
        Guidance string or None if no guidance applicable
    """
    verbosity = _state.get("verbosity", "normal")
    suggestions = []

    suggestions.append(f"🤖 Agent '{agent_name}' completed!")

    if verbosity != "minimal":
        suggestions.append("📋 Review the agent's output above")
        suggestions.append("🔄 Iterate: Make adjustments and re-invoke if needed")

    if verbosity == "verbose":
        suggestions.append("🔍 Compare with parent task context")
        suggestions.append("📝 Document learnings in code comments")

    return "\n".join(suggestions)


# ---------------------------------------------------------------------------
# Post-tool call hook
# ---------------------------------------------------------------------------


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> None:
    """Inject next-step guidance after tool execution.

    Args:
        tool_name: Name of the tool that was called
        tool_args: Arguments passed to the tool
        result: The result returned by the tool
        duration_ms: Execution time in milliseconds
        context: Optional context data for the tool call
    """
    if not _is_enabled():
        return

    try:
        from code_puppy.messaging import emit_info

        guidance: str | None = None

        if tool_name == "create_file":
            file_path = tool_args.get("file_path", "")
            content = tool_args.get("content", "")
            guidance = _get_write_guidance(file_path, content[:200] if content else None)

        elif tool_name == "replace_in_file":
            file_path = tool_args.get("file_path", "")
            guidance = _get_write_guidance(file_path, "replacement")

        elif tool_name == "agent_run_shell_command":
            command = tool_args.get("command", "")
            # Try to extract exit code from result
            exit_code = 0
            if isinstance(result, dict):
                exit_code = result.get("exit_code", 0)
            guidance = _get_shell_guidance(command, exit_code)

        elif tool_name == "invoke_agent":
            agent_name = tool_args.get("agent_name", "unknown")
            guidance = _get_agent_guidance(agent_name)

        if guidance:
            emit_info(f"\n{guidance}")
            _state["guidance_count"] += 1
            _state["last_tool"] = tool_name

    except Exception:
        # Never crash the app because of guidance
        pass


# ---------------------------------------------------------------------------
# Slash command UX: /guidance status | on | off | test
# ---------------------------------------------------------------------------


def _on_custom_help() -> list[tuple[str, str]]:
    return [
        ("/guidance", "Manage proactive guidance (status|on|off|test)"),
        ("/guidance verbosity minimal|normal|verbose", "Set guidance detail level"),
    ]


def _handle_custom_command(command: str, name: str) -> bool | str | None:
    if name != "guidance":
        return None  # Not ours — pass through.

    try:
        from code_puppy.messaging import emit_info
    except Exception:
        return True  # Can't emit — silently bail.

    parts = command.strip().split(maxsplit=2)
    sub = parts[1].strip().lower() if len(parts) >= 2 else "status"

    if sub == "status":
        config_enabled = _get_config_enabled()
        runtime_enabled = _state["enabled"]
        verbosity = _state["verbosity"]
        count = _state["guidance_count"]
        status_text = "enabled" if (config_enabled and runtime_enabled) else "disabled"

        msg = (
            f"🐾 Proactive Guidance: {status_text}\n"
            f"   Config enabled: {config_enabled}\n"
            f"   Runtime enabled: {runtime_enabled}\n"
            f"   Verbosity: {verbosity}\n"
            f"   Guidance shown: {count}\n"
            f"\nSet in puppy.cfg: proactive_guidance_enabled = true"
        )
        emit_info(msg)
        return True

    if sub in ("on", "enable"):
        _state["enabled"] = True
        emit_info("✅ Proactive guidance enabled for this session")
        return True

    if sub in ("off", "disable"):
        _state["enabled"] = False
        emit_info("⏸️ Proactive guidance disabled for this session")
        return True

    if sub == "verbosity" and len(parts) >= 3:
        new_verb = parts[2].strip().lower()
        if new_verb in _VALID_VERBOSITY:
            _state["verbosity"] = new_verb
            emit_info(f"📢 Guidance verbosity set to: {new_verb}")
        else:
            emit_info(f"❌ Invalid verbosity. Use: minimal, normal, or verbose")
        return True

    if sub == "test":
        # Show sample guidance
        emit_info("🧪 Sample guidance output:\n")
        emit_info(_get_write_guidance("test.py", "def hello(): pass") or "No guidance")
        emit_info("")
        emit_info(_get_shell_guidance("pytest test.py", 0) or "No guidance")
        return True

    if sub == "reset":
        _state["guidance_count"] = 0
        emit_info("🔄 Guidance counter reset")
        return True

    emit_info(f"Unknown /guidance subcommand: {sub!r} (try status|on|off|verbosity|test|reset)")
    return True


# ---------------------------------------------------------------------------
# Registration — module scope, as required by plugin loader
# ---------------------------------------------------------------------------

# Initialize state from config
_state["enabled"] = _get_config_enabled()
_state["verbosity"] = _get_config_verbosity()

register_callback("post_tool_call", _on_post_tool_call)
register_callback("custom_command_help", _on_custom_help)
register_callback("custom_command", _handle_custom_command)
