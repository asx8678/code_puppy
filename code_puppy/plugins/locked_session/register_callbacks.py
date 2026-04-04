"""Locked session mode plugin - adds /lock and /unlock commands.

This plugin provides a locked session mode that blocks dangerous shell commands
to prevent accidental data loss or system damage.
"""

import os
import re
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info

# Global locked state
_locked_state: bool = False

# Dangerous command patterns to block when locked
DANGEROUS_PATTERNS = [
    # Destructive file operations
    (r"\brm\s+-rf\b", "recursive force delete"),
    (r"\brm\s+-r\b", "recursive delete"),
    (r"\brm\s+.*\*", "wildcard delete"),

    # Privilege escalation
    (r"\bsudo\b", "sudo privilege escalation"),

    # Remote code execution via pipes
    (r"\bcurl\s+.*\|\s*(ba)?sh\b", "remote code execution via curl"),
    (r"\bwget\s+.*\|\s*(ba)?sh\b", "remote code execution via wget"),
    (r"\bcurl\s+.*\|\s*source\b", "remote code execution via curl"),

    # Permission changes
    (r"\bchmod\s+777\b", "world-writable permissions"),
    (r"\bchmod\s+-R\s+777\b", "recursive world-writable permissions"),

    # Disk operations
    (r"\bdd\s+if=", "disk write with dd"),
    (r"\bmkfs\b", "filesystem format"),
    (r"\bfdisk\b", "partition table modification"),

    # Direct device writes
    (r">\s*/dev/sd[a-z]", "direct disk write"),
    (r">\s*/dev/nvme", "direct NVMe write"),
    (r">\s*/dev/hd[a-z]", "direct disk write"),
    (r">\s*/dev/xvd[a-z]", "direct virtual disk write"),
    (r">\s*/dev/vd[a-z]", "direct virtual disk write"),
    (r">\s*/dev/disk", "direct disk write"),
    (r">\s*/dev/mapper", "direct LVM write"),
    (r">\s*/dev/null", "null device write (often suspicious)"),
    (r"\bcat\s+.*\s*>.\s*/dev/[sh]d", "disk overwrite via cat"),

    # System-level operations
    (r"\breboot\b", "system reboot"),
    (r"\bshutdown\b", "system shutdown"),
    (r"\bpoweroff\b", "system poweroff"),
    (r"\binit\s+0\b", "system halt"),
    (r"\binit\s+6\b", "system reboot"),

    # Package managers (can break system)
    (r"\bapt\s+remove\s+.*systemd\b", "removing core system packages"),
    (r"\bapt\s+purge\s+.*systemd\b", "purging core system packages"),
    (r"\byum\s+remove\s+.*kernel\b", "removing kernel packages"),
    (r"\bdpkg\s+--purge\b", "force package removal"),
    (r"\brpm\s+-e\s+.*kernel\b", "removing kernel packages"),

    # Git destructive operations
    (r"\bgit\s+reset\s+--hard\b", "hard git reset"),
    (r"\bgit\s+clean\s+-fd\b", "force git clean"),
    (r"\bgit\s+push\s+.*--force\b", "force git push"),
    (r"\bgit\s+push\s+.*-f\b", "force git push"),

    # Database operations
    (r"\bdrop\s+database\b", "drop database"),
    (r"\bdrop\s+table\b", "drop table"),

    # SSH and network operations
    (r"\bssh-keygen\s+-f.*-R\b", "removing SSH host keys"),
]


def is_locked() -> bool:
    """Check if the session is currently locked."""
    return _locked_state


def set_locked(locked: bool) -> None:
    """Set the locked state of the session."""
    global _locked_state
    _locked_state = locked


def _check_command_safety(command: str) -> tuple[bool, str | None]:
    """Check if a command is dangerous when locked.

    Args:
        command: The shell command to check.

    Returns:
        A tuple of (is_safe, reason). is_safe is False if the command
        matches a dangerous pattern. reason is the explanation if unsafe.
    """
    # Normalize command for checking
    normalized = command.lower().strip()

    # Check against all dangerous patterns
    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return False, reason

    return True, None


def _handle_custom_command(command: str, name: str) -> bool | str | None:
    """Handle /lock and /unlock custom commands.

    Args:
        command: The full command string (e.g., "/lock").
        name: The command name without leading slash (e.g., "lock").

    Returns:
        True if the command was handled, None if not handled.
    """
    global _locked_state

    if not name:
        return None

    if name == "lock":
        if _locked_state:
            emit_info("🔒 Session is already locked.")
        else:
            _locked_state = True
            emit_info("🔒 Session locked. Dangerous shell commands are now blocked.")
            emit_info("   Use /unlock to restore normal operation.")
        return True

    if name == "unlock":
        if not _locked_state:
            emit_info("🔓 Session is already unlocked.")
        else:
            _locked_state = False
            emit_info("🔓 Session unlocked. Shell commands are now allowed.")
        return True

    return None


def _custom_help() -> list[tuple[str, str]]:
    """Return help entries for /lock and /unlock commands."""
    return [
        ("lock", "Lock session - block dangerous shell commands"),
        ("unlock", "Unlock session - allow all shell commands"),
    ]


async def _run_shell_command_callback(
    context: Any,
    command: str,
    cwd: str | None = None,
    timeout: int = 60,
) -> dict[str, Any] | None:
    """Intercept shell commands and block dangerous ones when locked.

    Args:
        context: The execution context.
        command: The shell command to execute.
        cwd: Optional working directory.
        timeout: Command timeout (unused here).

    Returns:
        None if the command is safe or session is unlocked.
        A dict with {"blocked": True} if the command should be blocked.
    """
    # Only block when locked
    if not _locked_state:
        return None

    # Check if the command is dangerous
    is_safe, reason = _check_command_safety(command)

    if not is_safe:
        error_msg = (
            f"🛑 Command blocked - session is locked.\n"
            f"   Reason: {reason}\n"
            f"   Command: {command[:100]}{'...' if len(command) > 100 else ''}\n"
            f"   Use /unlock to enable this command."
        )
        emit_info(error_msg)
        return {
            "blocked": True,
            "reason": f"Session locked: {reason}",
            "error_message": error_msg,
        }

    # Command is safe, allow it to proceed
    return None


def _startup() -> None:
    """Check for CODE_PUPPY_LOCKED_SESSION env var on startup.

    If the environment variable is set to a truthy value,
    lock the session immediately on startup.
    """
    global _locked_state

    env_value = os.environ.get("CODE_PUPPY_LOCKED_SESSION", "").lower().strip()

    if env_value in ("1", "true", "yes", "on", "enabled"):
        _locked_state = True
        emit_info("🔒 Session started in locked mode (CODE_PUPPY_LOCKED_SESSION set).")
        emit_info("   Use /unlock to enable dangerous commands.")


# Register all callbacks
register_callback("startup", _startup)
register_callback("custom_command", _handle_custom_command)
register_callback("custom_command_help", _custom_help)
register_callback("run_shell_command", _run_shell_command_callback)
