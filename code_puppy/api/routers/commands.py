"""Commands API endpoints for slash command execution and autocomplete.

This router provides REST endpoints for:
- Listing all available slash commands
- Getting info about specific commands
- Executing slash commands
- Autocomplete suggestions for partial commands
"""

import asyncio
import os
import sys
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from code_puppy.tools.command_runner import _kill_process_group

# Ensure commands are registered by importing command_handler
# This triggers the @register_command decorator side effects
import code_puppy.command_line.command_handler  # noqa: F401

# Timeout for command execution (seconds)
COMMAND_TIMEOUT = 30.0

router = APIRouter()


# =============================================================================
# Pydantic Models
# =============================================================================


class CommandInfo(BaseModel):
    """Information about a registered command."""

    name: str
    description: str
    usage: str
    aliases: list[str] = []
    category: str = "core"
    detailed_help: str | None = None


class CommandExecuteRequest(BaseModel):
    """Request to execute a slash command."""

    command: str  # Full command string, e.g., "/set model=gpt-4o"


class CommandExecuteResponse(BaseModel):
    """Response from executing a slash command."""

    success: bool
    result: Any = None
    error: str | None = None


class AutocompleteRequest(BaseModel):
    """Request for command autocomplete."""

    partial: str  # Partial command string, e.g., "/se" or "/set mo"


class AutocompleteResponse(BaseModel):
    """Response with autocomplete suggestions."""

    suggestions: list[str]


async def _execute_command_in_subprocess(
    command: str, timeout: float
) -> tuple[bool, Any, str | None]:
    """Execute a command in a separate subprocess with proper timeout and kill support.

    This runs the command handler in a subprocess using asyncio.create_subprocess_exec,
    which allows us to properly terminate the subprocess on timeout. This solves
    the issue where asyncio.wait_for with run_in_executor leaves threads running.

    Args:
        command: The command string to execute (e.g., "/help").
        timeout: Maximum time to wait in seconds.

    Returns:
        Tuple of (success, result, error).
    """
    # Create a Python script that runs the command and outputs JSON result
    script = f"""
import json
import sys
sys.path.insert(0, {repr(os.getcwd())})

from code_puppy.command_line.command_handler import handle_command

try:
    result = handle_command({repr(command)})
    print(json.dumps({{"status": "success", "result": result, "error": None}}))
except Exception as e:
    print(json.dumps({{"status": "error", "result": None, "error": str(e)}}))
"""

    # Run the script in a subprocess with its own process group
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,  # Create new process group for clean termination
    )

    try:
        # Wait for completion with timeout
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )

        if proc.returncode != 0:
            error_msg = (
                stderr.decode().strip() or f"Process exited with code {proc.returncode}"
            )
            return (False, None, error_msg)

        # Parse the JSON result
        import json

        try:
            output = stdout.decode().strip().split("\n")[-1]  # Last line has JSON
            data = json.loads(output)
            if data["status"] == "success":
                return (True, data["result"], None)
            else:
                return (False, None, data["error"])
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            return (False, None, f"Failed to parse command output: {e}")

    except asyncio.TimeoutError:
        # Kill the process tree on timeout
        _kill_process_group(proc)
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return (False, None, f"Command timed out after {timeout}s")

    except asyncio.CancelledError:
        # Parent task cancelled - also kill the process
        _kill_process_group(proc)
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/")
async def list_commands() -> list[CommandInfo]:
    """List all available slash commands.

    Returns a sorted list of all unique commands (no alias duplicates),
    with their metadata including name, description, usage, aliases,
    category, and detailed help. Also includes custom commands from plugins.

    Returns:
        list[CommandInfo]: Sorted list of command information.
    """
    from code_puppy.command_line.command_registry import get_unique_commands
    from code_puppy import callbacks

    commands = []
    seen_names = set()

    # Get registered commands
    for cmd in get_unique_commands():
        commands.append(
            CommandInfo(
                name=cmd.name,
                description=cmd.description,
                usage=cmd.usage,
                aliases=cmd.aliases,
                category=cmd.category,
                detailed_help=cmd.detailed_help,
            )
        )
        seen_names.add(cmd.name)

    # Also include custom commands from plugins (matches /help behavior)
    try:
        custom_help = callbacks.on_custom_command_help()
        for res in custom_help:
            if not res:
                continue
            # Format 1: Tuple with (command_name, description)
            if isinstance(res, tuple) and len(res) == 2:
                cmd_name = str(res[0])
                if cmd_name not in seen_names:
                    commands.append(
                        CommandInfo(
                            name=cmd_name,
                            description=str(res[1]),
                            usage=f"/{cmd_name}",
                            aliases=[],
                            category="custom",
                            detailed_help=None,
                        )
                    )
                    seen_names.add(cmd_name)
            # Format 2: List of tuples or strings
            elif isinstance(res, list):
                # Check if it's a list of tuples (preferred format)
                if res and isinstance(res[0], tuple) and len(res[0]) == 2:
                    for item in res:
                        if isinstance(item, tuple) and len(item) == 2:
                            cmd_name = str(item[0])
                            if cmd_name not in seen_names:
                                commands.append(
                                    CommandInfo(
                                        name=cmd_name,
                                        description=str(item[1]),
                                        usage=f"/{cmd_name}",
                                        aliases=[],
                                        category="custom",
                                        detailed_help=None,
                                    )
                                )
                                seen_names.add(cmd_name)
                # Format 3: List of strings (legacy format)
                # Extract command from first line like "/command_name - Description"
                elif res and isinstance(res[0], str) and res[0].startswith("/"):
                    first_line = res[0]
                    if " - " in first_line:
                        parts = first_line.split(" - ", 1)
                        cmd_name = parts[0].lstrip("/").strip()
                        if cmd_name not in seen_names:
                            description = parts[1].strip()
                            commands.append(
                                CommandInfo(
                                    name=cmd_name,
                                    description=description,
                                    usage=f"/{cmd_name}",
                                    aliases=[],
                                    category="custom",
                                    detailed_help=None,
                                )
                            )
                            seen_names.add(cmd_name)
    except Exception:
        # Silently skip custom commands if callback fails
        pass

    return sorted(commands, key=lambda c: c.name)


@router.get("/{name}")
async def get_command_info(name: str) -> CommandInfo:
    """Get detailed info about a specific command.

    Looks up a command by name or alias (case-insensitive).

    Args:
        name: Command name or alias (without leading /).

    Returns:
        CommandInfo: Full command information.

    Raises:
        HTTPException: 404 if command not found.
    """
    from code_puppy.command_line.command_registry import get_command

    cmd = get_command(name)
    if not cmd:
        raise HTTPException(404, f"Command '/{name}' not found")

    return CommandInfo(
        name=cmd.name,
        description=cmd.description,
        usage=cmd.usage,
        aliases=cmd.aliases,
        category=cmd.category,
        detailed_help=cmd.detailed_help,
    )


@router.post("/execute")
async def execute_command(request: CommandExecuteRequest) -> CommandExecuteResponse:
    """Execute a slash command.

    Takes a command string (with or without leading /) and executes it
    using the command handler. Runs in a subprocess (not thread) to enable
    proper cancellation on timeout - the process is killed if it exceeds
    the timeout.

    Args:
        request: CommandExecuteRequest with the command to execute.

    Returns:
        CommandExecuteResponse: Result of command execution.
    """
    command = request.command
    if not command.startswith("/"):
        command = "/" + command

    success, result, error = await _execute_command_in_subprocess(
        command, COMMAND_TIMEOUT
    )
    return CommandExecuteResponse(success=success, result=result, error=error)


@router.post("/autocomplete")
async def autocomplete_command(request: AutocompleteRequest) -> AutocompleteResponse:
    """Get autocomplete suggestions for a partial command.

    Provides intelligent autocomplete based on partial input:
    - Empty input: returns all command names
    - Partial command name: returns matching commands and aliases
    - Complete command with args: returns usage hint

    Args:
        request: AutocompleteRequest with partial command string.

    Returns:
        AutocompleteResponse: List of autocomplete suggestions.
    """
    from code_puppy.command_line.command_registry import (
        get_command,
        get_unique_commands,
    )

    partial = request.partial.lstrip("/")

    # If empty, return all command names
    if not partial:
        suggestions = [f"/{cmd.name}" for cmd in get_unique_commands()]
        return AutocompleteResponse(suggestions=sorted(suggestions))

    # Split into command name and args
    parts = partial.split(maxsplit=1)
    cmd_partial = parts[0].lower()

    # If just the command name (no space yet), suggest matching commands
    if len(parts) == 1:
        suggestions = []
        for cmd in get_unique_commands():
            if cmd.name.startswith(cmd_partial):
                suggestions.append(f"/{cmd.name}")
            for alias in cmd.aliases:
                if alias.startswith(cmd_partial):
                    suggestions.append(f"/{alias}")
        return AutocompleteResponse(suggestions=sorted(set(suggestions)))

    # Command name complete, suggest based on command type
    # (For now, just return the command usage as a hint)
    cmd = get_command(cmd_partial)
    if cmd:
        return AutocompleteResponse(suggestions=[cmd.usage])

    return AutocompleteResponse(suggestions=[])
