"""Turbo Executor Plugin — Callback Registration.

Registers the turbo execution system with code_puppy's callback hooks:
- register_tools: Add turbo_execute tool for agents
- custom_command: Add /turbo slash command
- startup: Initialize orchestrator
- load_prompt: Add delegation guidance for all agents
"""

import json
import logging
from typing import Any

from pydantic_ai import RunContext

from code_puppy.callbacks import register_callback
from code_puppy.messaging import emit_info, emit_warning
from code_puppy.plugins.turbo_executor.models import Plan
from code_puppy.plugins.turbo_executor.orchestrator import TurboOrchestrator
from code_puppy.plugins.turbo_executor.summarizer import summarize_plan_result
from code_puppy.plugins.turbo_executor.history import get_history
from code_puppy.plugins.turbo_executor.notifications import (
    register as register_notifications,
)

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)


class OrchestratorRegistry:
    """Registry for managing multiple TurboOrchestrator instances.

    Replaces the singleton pattern to support concurrent agent sessions.
    Each invoke_agent('turbo-executor', ...) call gets its own orchestrator instance.

    The registry maintains instances keyed by unique IDs (typically agent IDs).
    When an instance is requested:
    - If the ID exists in the registry, return the existing instance
    - If the ID doesn't exist, create a new instance and store it
    - If no ID is provided, return a shared default instance
    """

    def __init__(self):
        self._instances: dict[str, TurboOrchestrator] = {}
        self._default_instance: TurboOrchestrator | None = None

    def get_orchestrator(self, instance_id: str | None = None) -> TurboOrchestrator:
        """Get an orchestrator instance by ID.

        Args:
            instance_id: Unique identifier for the orchestrator instance.
                        If None, returns the shared default instance.

        Returns:
            TurboOrchestrator instance (created if needed)
        """
        if instance_id is None:
            # Return the shared default instance for backward compatibility
            if self._default_instance is None:
                self._default_instance = TurboOrchestrator()
                logger.debug("Created default orchestrator instance")
            return self._default_instance

        # Return or create the instance for this ID
        if instance_id not in self._instances:
            self._instances[instance_id] = TurboOrchestrator()
            logger.debug(f"Created new orchestrator instance for {instance_id}")

        return self._instances[instance_id]

    def remove_orchestrator(self, instance_id: str) -> bool:
        """Remove an orchestrator instance from the registry.

        Args:
            instance_id: Unique identifier of the instance to remove

        Returns:
            True if an instance was removed, False if not found
        """
        if instance_id in self._instances:
            del self._instances[instance_id]
            logger.debug(f"Removed orchestrator instance for {instance_id}")
            return True
        return False

    def get_instance_count(self) -> int:
        """Get the number of managed orchestrator instances (excluding default)."""
        return len(self._instances)

    def clear_all_instances(self) -> None:
        """Clear all managed instances and the default instance."""
        self._instances.clear()
        self._default_instance = None
        logger.debug("Cleared all orchestrator instances")


# Global registry instance
_orchestrator_registry = OrchestratorRegistry()


def _get_orchestrator(instance_id: str | None = None) -> TurboOrchestrator:
    """Get an orchestrator instance from the registry.

    Args:
        instance_id: Unique identifier for the orchestrator instance.
                    If None, returns the shared default instance.
                    Each unique ID gets its own isolated instance.

    Returns:
        TurboOrchestrator instance
    """
    return _orchestrator_registry.get_orchestrator(instance_id)


def _on_startup():
    """Initialize the orchestrator registry on startup."""
    # Pre-initialize the default instance so it's ready when needed
    default_orch = _orchestrator_registry.get_orchestrator(None)
    if default_orch._turbo_ops_async_available:
        ops_mode = "turbo_ops (async Rust)"
    elif default_orch._turbo_ops_sync_available:
        ops_mode = "turbo_ops (sync Rust)"
    else:
        ops_mode = "native Python"
    logger.info(f"Turbo Executor plugin initialized (using {ops_mode})")


def _custom_help():
    """Provide help for the /turbo command."""
    return [
        (
            "turbo",
            "Execute batch file operations via turbo executor (status/history/plan/help)",
        ),
    ]


def _handle_turbo_command(command: str, name: str) -> Any:
    """Handle the /turbo slash command.

    Usage:
        /turbo status     → Show turbo executor status
        /turbo history    → Show execution history
        /turbo plan <json>→ Execute a plan from JSON string
        /turbo help       → Show usage instructions
    """
    if name != "turbo":
        return None

    parts = command.strip().split(maxsplit=2)
    subcommand = parts[1] if len(parts) > 1 else "status"

    if subcommand == "status":
        orch = _get_orchestrator()
        emit_info("🚀 Turbo Executor Status:")
        emit_info(f"   Orchestrator ready: {orch is not None}")
        emit_info(f"   Parallel mode: {orch.enable_parallel}")
        if orch._turbo_ops_async_available:
            ops_source = "Rust turbo_ops (async - preferred)"
        elif orch._turbo_ops_sync_available:
            ops_source = "Rust turbo_ops (sync - fallback)"
        else:
            ops_source = "native Python"
        emit_info(f"   Operations source: {ops_source}")
        emit_info("   Supported operations: list_files, grep, read_files, run_tests")
        # Show registry info
        instance_count = _orchestrator_registry.get_instance_count()
        emit_info(f"   Active instances: {instance_count}")
        history_len = len(get_history())
        emit_info(f"   History entries: {history_len}")
        return True

    if subcommand == "history":
        history = get_history()
        if len(history) == 0:
            emit_info("📜 Turbo Execution History: (no executions yet)")
            emit_info("")
            emit_info("Run a plan with '/turbo plan <json>' to see it in history.")
        else:
            history.display_history()
        return True

    if subcommand == "help":
        orch = _get_orchestrator()
        if orch._turbo_ops_async_available:
            ops_source = "Rust turbo_ops (async - preferred)"
        elif orch._turbo_ops_sync_available:
            ops_source = "Rust turbo_ops (sync - fallback)"
        else:
            ops_source = "native Python"
        emit_info("🚀 Turbo Executor — Batch File Operations")
        emit_info("")
        emit_info("Usage:")
        emit_info("  /turbo status           → Show orchestrator status")
        emit_info("  /turbo history          → Show execution history")
        emit_info("  /turbo plan <json>      → Execute a plan from JSON")
        emit_info("")
        emit_info("Plan JSON format:")
        emit_info('  {"id": "my-plan", "operations": [')
        emit_info(
            '    {"type": "list_files", "args": {"directory": "."}, "priority": 1},'
        )
        emit_info(
            '    {"type": "grep", "args": {"search_string": "def "}, "priority": 2}'
        )
        emit_info("  ]}")
        emit_info("")
        emit_info("Operations: list_files, grep, read_files, run_tests")
        emit_info("Priority: lower numbers execute first (default 100)")
        emit_info("")
        emit_info(f"Backend: {ops_source}")
        return True

    if subcommand == "plan":
        if len(parts) < 3:
            emit_warning('Usage: /turbo plan \'{"id": "test", "operations": [...]}\'')
            return True

        plan_json = parts[2]
        try:
            plan_data = json.loads(plan_json)
            plan = Plan.model_validate(plan_data)

            orch = _get_orchestrator()

            # Validate before executing
            errors = orch.validate_plan(plan)
            if errors:
                emit_warning("Plan validation errors:")
                for error in errors:
                    emit_warning(f"  - {error}")
                return True

            emit_info(
                f"🚀 Executing turbo plan '{plan.id}' with {len(plan.operations)} operations..."
            )

            # Execute in a dedicated thread to avoid nested event loops
            import concurrent.futures

            def _run_plan():
                import asyncio

                return asyncio.run(orch.execute(plan))

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(_run_plan)
                result = future.result()
                emit_info(f"✅ Plan completed: {result.status}")
                emit_info(
                    f"   Operations: {result.success_count} success, {result.error_count} errors"
                )
                if result.error_count > 0:
                    for err in result.get_errors():
                        emit_warning(
                            f"   Error in {err.operation_id or err.type}: {err.error}"
                        )
                return True

        except json.JSONDecodeError as e:
            emit_warning(f"Invalid JSON: {e}")
            return True
        except Exception as e:
            emit_warning(f"Plan execution failed: {e}")
            return True

    # Unknown subcommand
    emit_warning(f"Unknown turbo command: {subcommand}")
    emit_warning("Try: /turbo status, /turbo history, /turbo help, /turbo plan <json>")
    return True


def _register_turbo_tools():
    """Register turbo execution tools.

    Returns a list of tool definitions for the register_tools callback.
    """
    return [
        {
            "name": "turbo_execute",
            "register_func": _register_turbo_execute_tool,
        }
    ]


def _register_turbo_execute_tool(agent):
    """Register the turbo_execute tool with an agent.

    Tool JSON Schema:
    {
        "name": "turbo_execute",
        "description": "Execute a batch of file operations via the turbo executor...",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_json": {
                    "type": "string",
                    "description": "JSON string containing the plan with operations to execute"
                },
                "summarize": {
                    "type": "boolean",
                    "description": "Whether to return a human-readable summary instead of raw data"
                }
            },
            "required": ["plan_json"]
        }
    }
    """

    @agent.tool
    async def turbo_execute(
        context: RunContext,
        plan_json: str,
        summarize: bool = True,
    ) -> dict:
        """Execute a batch of file operations via the turbo executor.

        Use this tool when you need to perform multiple file operations
        (list_files, grep, read_files, run_tests) efficiently in a single call.

        Args:
            plan_json: JSON string containing the plan. Format:
                {
                    "id": "unique-plan-id",
                    "operations": [
                        {
                            "type": "list_files",
                            "args": {"directory": ".", "recursive": true},
                            "priority": 1,
                            "id": "op-1"
                        },
                        {
                            "type": "grep",
                            "args": {"search_string": "pattern", "directory": "."},
                            "priority": 2,
                            "id": "op-2"
                        },
                        {
                            "type": "read_files",
                            "args": {"file_paths": ["file1.py", "file2.py"]},
                            "priority": 3,
                            "id": "op-3"
                        },
                        {
                            "type": "run_tests",
                            "args": {"test_path": "tests/", "runner": "pytest"},
                            "priority": 4,
                            "id": "op-4"
                        }
                    ],
                    "metadata": {"description": "Optional"}
                }
            summarize: If True (default), returns a human-readable markdown summary.
                      If False, returns raw result data structure.

        Returns:
            Dict with plan execution results. When summarize=True, includes 'summary'
            field with human-readable markdown. Always includes 'status', 'plan_id',
            'success_count', 'error_count', and 'operation_results'.
        """
        try:
            plan_data = json.loads(plan_json)
            plan = Plan.model_validate(plan_data)
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "error": f"Invalid JSON: {str(e)}",
                "plan_id": None,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Invalid plan: {str(e)}",
                "plan_id": None,
            }

        orch = _get_orchestrator(instance_id=context.agent_id)

        # Validate plan
        validation_errors = orch.validate_plan(plan)
        if validation_errors:
            return {
                "status": "validation_error",
                "plan_id": plan.id,
                "errors": validation_errors,
            }

        # Execute plan
        try:
            result = await orch.execute(plan)

            # Build response
            response = {
                "status": result.status.value,
                "plan_id": result.plan_id,
                "success_count": result.success_count,
                "error_count": result.error_count,
                "total_duration_ms": result.total_duration_ms,
                "started_at": result.started_at,
                "completed_at": result.completed_at,
                "operation_results": [
                    {
                        "operation_id": r.operation_id,
                        "type": r.type.value,
                        "status": r.status,
                        "data": r.data,
                        "error": r.error,
                        "duration_ms": r.duration_ms,
                    }
                    for r in result.operation_results
                ],
            }

            # Add errors if any
            errors = result.get_errors()
            if errors:
                response["errors"] = [
                    {
                        "operation_id": e.operation_id,
                        "type": e.type.value,
                        "error": e.error,
                    }
                    for e in errors
                ]

            # Add human-readable summary if requested
            if summarize:
                response["summary"] = summarize_plan_result(result)
                response["quick_summary"] = (
                    f"{result.success_count} success, {result.error_count} errors in {result.total_duration_ms:.0f}ms"
                )

            return response

        except Exception as e:
            logger.exception("Turbo execution failed")
            return {
                "status": "error",
                "plan_id": plan.id,
                "error": str(e),
            }


def _load_turbo_prompt() -> str:
    """Add delegation guidance for turbo-executor.

    This is called via the 'load_prompt' callback to add instructions
    to all agent system prompts about when and how to delegate to
    the turbo-executor agent for batch file operations.

    Returns:
        Prompt section with delegation guidance.
    """
    return """\

## 🚀 Turbo Executor Delegation

**For batch file operations, delegate to the turbo-executor agent!**

The `turbo-executor` agent is a specialized agent with a 1M context window,
designed for high-performance batch file operations. Use it when you need to:

### When to Delegate

1. **Exploring large codebases**: Multiple list_files + grep operations
2. **Reading many files**: More than 5-10 files to read at once
3. **Complex search patterns**: Multiple grep operations across directories
4. **Batch analysis**: Operations that would benefit from parallel execution

### How to Delegate

Use `invoke_agent` with the turbo-executor:

```python
# Example: Batch exploration of a codebase
invoke_agent(
    "turbo-executor",
    "Explore the codebase structure and find all test files:\n"
    "\n"
    "1. List the src/ directory structure\n"
    "2. Search for files containing 'def test_'\n"
    "3. Read the first 5 test files found\n"
    "\n"
    "Return a summary of the test file organization.",
    session_id="explore-tests"
)
```

### Two Options for Batch Operations

**Option 1: Use turbo_execute tool directly** (if available)
- Best for: Programmatic batch operations within your current agent
- Use `turbo_execute` with a plan JSON containing list_files, grep, read_files, run_tests operations

**Option 2: Invoke turbo-executor agent** (always available)
- Best for: Complex analysis tasks, large-scale exploration
- Use `invoke_agent("turbo-executor", prompt)` with natural language instructions
- The turbo-executor will plan and execute efficient batch operations

### Example Delegation Scenarios

**Scenario 1: Understanding a new codebase**
```python
# Instead of:
list_files(".")
grep("class ", ".")
grep("def ", ".")
read_file("src/main.py")
read_file("src/utils.py")
# ... many more operations

# Delegate to turbo-executor:
invoke_agent("turbo-executor", "Explore this codebase and give me an overview of the main classes and their relationships")
```

**Scenario 2: Batch refactoring analysis**
```python
# Instead of:
for file in all_files:
    read_file(file)
    # analyze each file individually

# Delegate to turbo-executor:
invoke_agent("turbo-executor", "Find all files using the deprecated 'old_function' and report their locations and usage patterns")
```

### Remember

- **Small tasks** (< 5 file operations): Do them directly
- **Medium tasks** (5-10 operations): Consider turbo_execute tool
- **Large tasks** (> 10 operations or complex exploration): Delegate to turbo-executor agent
- The turbo-executor has a 1M context window - it can process entire codebases at once!
"""


def _register_turbo_agents():
    """Register the turbo-executor agent for discovery (optional).

    The turbo executor works as a tool with ANY agent — this registration
    just adds a dedicated agent as a bonus. If the agent class isn't
    available (e.g., missing dependency), we silently skip it.

    Returns a list of agent definitions, or empty list if agent unavailable.
    """
    try:
        from code_puppy.agents.agent_turbo_executor import TurboExecutorAgent

        return [
            {
                "name": "turbo-executor",
                "class": TurboExecutorAgent,
            }
        ]
    except ImportError:
        logger.debug(
            "TurboExecutorAgent not available — turbo_execute tool still works with any agent"
        )
        return []


# Register all callbacks
register_callback("startup", _on_startup)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_turbo_command)
register_callback("register_tools", _register_turbo_tools)
register_callback("load_prompt", _load_turbo_prompt)
register_callback("register_agents", _register_turbo_agents)

# Register visual notifications for turbo_execute tool calls

register_notifications()

logger.info("Turbo Executor plugin callbacks registered")
