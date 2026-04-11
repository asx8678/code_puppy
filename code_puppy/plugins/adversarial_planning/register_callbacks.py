"""Adversarial Planning Plugin - Evidence-first, execution-ready planning.

This plugin implements a multi-agent adversarial planning system that:
1. Gathers evidence from the workspace (Phase 0A)
2. Frames the problem with scope and constraints (Phase 0B)
3. Produces two materially different plans (Phase 1A, 1B)
4. Reviews both plans adversarially (Phase 2A, 2B)
5. Synthesizes the best elements (Phase 4)
6. Stress-tests with red team (Phase 5 - deep mode only)
7. Makes go/no-go decision (Phase 6)
8. Produces execution-ready change sets (Phase 7)

The plugin registers hooks for startup, tools, agents, and commands.
"""

import logging
from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)


def _on_startup() -> None:
    """Called when the plugin is loaded.
    
    Logs plugin initialization and performs any setup needed.
    """
    logger.info("⚔️ Adversarial Planning plugin loaded")
    logger.debug("Plugin: adversarial_planning v0.1.0")


def _register_tools() -> list[dict]:
    """Register adversarial planning specific tools.
    
    Returns:
        List of tool registration dictionaries
    """
    from .tools import get_adversarial_tools
    return get_adversarial_tools()


def _register_agents() -> list[dict]:
    """Register adversarial planning specific agents.
    
    Returns:
        List of agent registration dictionaries
    """
    from .agents import get_adversarial_agents
    
    agents = get_adversarial_agents()
    logger.debug(f"Registering {len(agents)} adversarial planning agents")
    return agents


def _custom_help() -> list[tuple[str, str]]:
    """Provide custom command help entries.
    
    Returns:
        List of (command, description) tuples
    """
    return [
        ("/ap <task>", "Start adversarial planning (auto mode)"),
        ("/ap-standard <task>", "Start adversarial planning (standard mode)"),
        ("/ap-deep <task>", "Start adversarial planning (deep mode)"),
        ("/ap-status", "Show current adversarial plan status"),
        ("/ap-abort", "Abort running adversarial plan"),
    ]


def _handle_command(command: str, name: str) -> str | bool | None:
    """Handle adversarial planning slash commands.
    
    Args:
        command: The full command string
        name: The command name
        
    Returns:
        Response string, True if handled, or None if not recognized
    """
    from .commands import handle_command
    return handle_command(command, name)


def _load_prompt() -> str:
    """Load plugin-specific instructions into system prompt.
    
    Returns:
        Prompt text to append to system prompt
    """
    return '''
## ⚔️ Adversarial Planning Available

Use `/ap <task>` for evidence-first, multi-agent adversarial planning.

### How it works:
1. **Researcher** surveys workspace and classifies evidence
2. **Two isolated planners** propose materially different solutions:
   - Planner A: Conservative, proven patterns
   - Planner B: Contrarian, challenges assumptions
3. **Adversarial review** falsifies weak claims
4. **Arbiter** synthesizes the best of both plans
5. **Red team** stress-tests (deep mode)
6. **Decision** produces go/no-go with evidence

### Modes:
- **Auto** (`/ap`): Detects task complexity, selects mode
- **Standard** (`/ap-standard`): 0A → 0B → 1 → 2 → (3 if needed) → 4 → 6 (faster)
- **Deep** (`/ap-deep`): Adds Phase 5 (Red Team) and Phase 7 (Change-Sets, go only)

Phase 3 (Rebuttal) runs when reviews strongly disagree (any mode).
Phase 7 (Change-Sets) only runs in deep mode with 'go' verdict.

### Best for:
- Migrations and replatforming
- Architecture changes
- Security-critical work
- Production-risky launches
- Cross-team dependencies

### Commands:
| Command | Description |
|---------|-------------|
| `/ap <task>` | Auto mode planning |
| `/ap-standard <task>` | Standard mode |
| `/ap-deep <task>` | Deep mode with stress testing |
| `/ap-status` | Check session status |
| `/ap-abort` | Stop current session |

**Evidence classification:**
- VERIFIED (90-100%): Directly observed, supports irreversible work
- INFERENCE (70-89%): Reasonable conclusion, reversible probes only
- ASSUMPTION (50-69%): Must become task/gate/blocker
- UNKNOWN (<50%): Must be blocker/gate/out-of-scope
'''


# =============================================================================
# Register all callbacks
# =============================================================================

# Register plugin lifecycle hooks
register_callback("startup", _on_startup)

# Register tool and agent hooks
register_callback("register_tools", _register_tools)
register_callback("register_agents", _register_agents)

# Register custom command hooks
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_command)

# Register prompt hook
register_callback("load_prompt", _load_prompt)

logger.debug("Adversarial Planning callbacks registered")
