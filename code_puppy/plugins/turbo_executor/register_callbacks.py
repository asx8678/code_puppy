"""Turbo Executor Plugin — Callback Registration.

Registers the turbo execution system with code_puppy's callback hooks:
- register_tools: Add turbo_execute tool for agents
- custom_command: Add /turbo slash command
- startup: Initialize orchestrator
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

logger = logging.getLogger(__name__)

# Global orchestrator instance (initialized on startup)
_orchestrator: TurboOrchestrator | None = None


def _get_orchestrator() -> TurboOrchestrator:
    """Get or create the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = TurboOrchestrator()
    return _orchestrator


def _on_startup():
    """Initialize the orchestrator on startup."""
    global _orchestrator
    _orchestrator = TurboOrchestrator()
    ops_mode = (
        "turbo_ops (Rust)" if _orchestrator._turbo_ops_available else "native Python"
    )
    logger.info(f"Turbo Executor plugin initialized (using {ops_mode})")


def _custom_help():
    """Provide help for the /turbo command."""
    return [
        (
            "turbo",
            "Execute batch file operations via turbo executor (status/plan/help)",
        ),
    ]


def _handle_turbo_command(command: str, name: str) -> Any:
    """Handle the /turbo slash command.

    Usage:
        /turbo status     → Show turbo executor status
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
        ops_source = "Rust turbo_ops" if orch._turbo_ops_available else "native Python"
        emit_info(f"   Operations source: {ops_source}")
        emit_info("   Supported operations: list_files, grep, read_files")
        return True

    if subcommand == "help":
        orch = _get_orchestrator()
        ops_source = "Rust turbo_ops" if orch._turbo_ops_available else "native Python"
        emit_info("🚀 Turbo Executor — Batch File Operations")
        emit_info("")
        emit_info("Usage:")
        emit_info("  /turbo status           → Show orchestrator status")
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
        emit_info("Operations: list_files, grep, read_files")
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
    emit_warning("Try: /turbo status, /turbo help, /turbo plan <json>")
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
        (list_files, grep, read_files) efficiently in a single call.

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

        orch = _get_orchestrator()

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


# Register all callbacks
register_callback("startup", _on_startup)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_turbo_command)
register_callback("register_tools", _register_turbo_tools)

logger.info("Turbo Executor plugin callbacks registered")
