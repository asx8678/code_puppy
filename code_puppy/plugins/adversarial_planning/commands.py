"""Adversarial Planning Slash Commands."""

import asyncio
import logging
from typing import Literal

from code_puppy.plugins.customizable_commands.register_callbacks import MarkdownCommandResult

logger = logging.getLogger(__name__)

_COMMAND_NAMES = {"ap", "ap-standard", "ap-deep", "ap-status", "ap-abort"}

# Global state for tracking active sessions
_active_sessions: dict[str, "AdversarialPlanningOrchestrator"] = {}


def handle_command(command: str, name: str) -> Literal[True] | str | None:
    """Handle adversarial planning slash commands.
    
    Returns:
        True: Command was handled (no further processing)
        str: Input to pass to the agent
        None: Not our command
    """
    if name not in _COMMAND_NAMES:
        return None
    
    parts = command.strip().split(maxsplit=1)
    
    if name == "ap":
        return _handle_ap(parts, mode="auto")
    elif name == "ap-standard":
        return _handle_ap(parts, mode="standard")
    elif name == "ap-deep":
        return _handle_ap(parts, mode="deep")
    elif name == "ap-status":
        return _handle_status()
    elif name == "ap-abort":
        return _handle_abort()
    
    return None


def _handle_ap(parts: list[str], mode: Literal["auto", "standard", "deep"]) -> MarkdownCommandResult | Literal[True]:
    """Handle /ap, /ap-standard, /ap-deep commands."""
    from code_puppy.messaging import emit_info, emit_error
    
    if len(parts) < 2:
        emit_info("""
⚔️ **Adversarial Planning**

Usage: /ap <task description>
       /ap-standard <task>  (force standard mode)
       /ap-deep <task>      (force deep mode)

Examples:
  /ap Migrate user database from PostgreSQL to MySQL
  /ap-deep Implement OAuth2 authentication flow
  /ap-standard Add dark mode toggle to settings page

**Modes:**
- auto: Automatically selects based on risk triggers
- standard: Phases 0A, 0B, 1, 2, 4, 6 (faster)
- deep: Adds Phase 3 Rebuttal, Phase 5 Red Team (thorough)
""")
        return True
    
    task = parts[1]
    mode_emoji = {"auto": "🤖", "standard": "🟢", "deep": "🔴"}[mode]
    
    emit_info(f"""
{mode_emoji} **Starting Adversarial Planning** ({mode.upper()} mode)

**Task:** {task}

This will:
1. Discover environment evidence (Phase 0A)
2. Lock scope without solution bias (Phase 0B)
3. Generate two isolated, materially different plans
4. Adversarially review both plans
5. Synthesize the best surviving elements
6. Determine go/conditional-go/no-go verdict

Please wait...
""")
    
    # Return prompt for the planning agent to execute
    return MarkdownCommandResult(f"""Run adversarial planning for this task:

{task}

Use the `adversarial_plan` tool with mode="{mode}".

After completion, display:
1. Final verdict (go/conditional_go/no_go)
2. Adjusted score with penalties
3. Execution order (if go/conditional_go)
4. Quick wins
5. Monday morning actions
6. Any blockers or conditions
""")


def _handle_status() -> Literal[True]:
    """Handle /ap-status command."""
    from code_puppy.messaging import emit_info
    
    if not _active_sessions:
        emit_info("📊 No active adversarial planning sessions.")
        return True
    
    lines = ["📊 **Active Adversarial Planning Sessions**\n"]
    
    for session_id, orchestrator in _active_sessions.items():
        session = orchestrator.session
        mode = session.mode_selected or "pending"
        phase = session.current_phase
        
        # Calculate progress
        phase_order = ["init", "0a_discovery", "0b_scope_lock", "1_planning", "2_review", 
                       "3_rebuttal", "4_synthesis", "5_red_team", "6_decision", "7_changeset", "complete"]
        try:
            progress = phase_order.index(phase) / (len(phase_order) - 1) * 100
        except ValueError:
            progress = 0
        
        # Build progress bar
        filled = int(progress / 10)
        bar = "█" * filled + "░" * (10 - filled)
        
        lines.append(f"**{session_id}**")
        lines.append(f"  Mode: {mode.upper()}")
        lines.append(f"  Phase: {phase}")
        lines.append(f"  Progress: [{bar}] {progress:.0f}%")
        
        if session.global_stop_reason:
            lines.append(f"  ⚠️ Stopped: {session.global_stop_reason}")
        
        lines.append("")
    
    emit_info("\n".join(lines))
    return True


def _handle_abort() -> Literal[True]:
    """Handle /ap-abort command."""
    from code_puppy.messaging import emit_info, emit_warning
    
    if not _active_sessions:
        emit_info("No active sessions to abort.")
        return True
    
    # Abort all sessions
    count = len(_active_sessions)
    for session_id in list(_active_sessions.keys()):
        orchestrator = _active_sessions.pop(session_id)
        orchestrator.session.global_stop_reason = "User aborted"
    
    emit_warning(f"🛑 Aborted {count} adversarial planning session(s).")
    return True


def register_session(orchestrator: "AdversarialPlanningOrchestrator") -> None:
    """Register an active orchestrator session."""
    _active_sessions[orchestrator.session_id] = orchestrator


def unregister_session(session_id: str) -> None:
    """Unregister a completed/aborted session."""
    _active_sessions.pop(session_id, None)
