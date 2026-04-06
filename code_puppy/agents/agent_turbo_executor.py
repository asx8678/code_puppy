"""Turbo Executor Agent — Batch file operations specialist.

A specialized agent for high-performance batch file operations using
the turbo executor plugin. Works with any model — model pinning is config-driven.
"""

from typing import Any

from code_puppy.agents.base_agent import BaseAgent
from code_puppy.plugins.turbo_executor import (
    Operation,
    OperationType,
    Plan,
    PlanResult,
    summarize_plan_result,
    quick_summary,
)


class TurboExecutorAgent(BaseAgent):
    """Turbo Executor — Batch file operations specialist.

    Executes batch file operations (list_files, grep, read_files) with
    high performance using the turbo orchestrator. Designed for large-scale
    codebase exploration and analysis tasks.

    Model-agnostic: works with any model. For best results with large batches,
    configure this agent to use a model with a large context window via
    agent_model_turbo-executor in puppy.cfg.
    """

    # Model pinning: Xiaomi V2 Pro with 1M context window

    @property
    def name(self) -> str:
        return "turbo-executor"

    @property
    def display_name(self) -> str:
        return "Turbo Executor 🚀"

    @property
    def description(self) -> str:
        return (
            "High-performance batch file operations specialist — works with any model"
        )

    def get_available_tools(self) -> list[str]:
        """Get tools available to Turbo Executor.

        Includes the primary turbo_execute batch tool and individual file tools
        as fallback for simple operations.
        """
        return [
            "turbo_execute",  # Primary tool — use for all batch operations
            "agent_share_your_reasoning",  # For explaining plans
            "agent_run_shell_command",  # Fallback for shell operations
            # Individual file tools — only for single operations
            "list_files",
            "read_file",
            "grep",
            "create_file",
            "replace_in_file",
        ]

    def get_system_prompt(self) -> str:
        """Get Turbo Executor's system prompt.

        Focuses on batch file operations and efficient codebase exploration.
        """
        return """\
You are Turbo Executor 🚀, a high-performance batch file operations specialist.

You MUST use exact tool names and valid JSON-object arguments.

Primary tool:
- turbo_execute: Execute a full batch plan in one call (preferred)

Fallback tools (only for simple/single operations):
- list_files
- read_file
- grep
- create_file
- replace_in_file
- agent_run_shell_command
- agent_share_your_reasoning

Critical tool-calling rules:
- Use EXACT tool names only; never invent or combine names like "greplist_files"
- Tool call arguments MUST always be JSON objects (e.g. {"directory": "."})
- Never send positional arrays/lists as tool arguments
- For turbo_execute, pass a JSON object with plan_json (string) and optional summarize

When given a task:
1. Use agent_share_your_reasoning to briefly explain your plan
2. Prefer turbo_execute for multi-step file operations
3. Use fallback tools only when a single operation is enough
4. Summarize results concisely

You work at turbo speed! ⚡
"""

    async def execute_plan(self, plan: Plan) -> PlanResult:
        """Execute a turbo plan and return results.

        Args:
            plan: The plan containing operations to execute

        Returns:
            PlanResult with all operation results
        """
        from code_puppy.plugins.turbo_executor.register_callbacks import (
            _get_orchestrator,
        )

        orchestrator = _get_orchestrator()
        return await orchestrator.execute(plan)

    def summarize_result(
        self,
        plan_result: PlanResult,
        include_details: bool = True,
    ) -> str:
        """Generate a markdown summary of plan execution results.

        Args:
            plan_result: The result to summarize
            include_details: Whether to include detailed operation results

        Returns:
            Markdown-formatted summary
        """
        return summarize_plan_result(
            plan_result, include_operation_details=include_details
        )

    def quick_status(self, plan_result: PlanResult) -> str:
        """Generate a one-line summary of plan execution.

        Args:
            plan_result: The result to summarize

        Returns:
            Short summary string
        """
        return quick_summary(plan_result)

    def create_plan(
        self,
        plan_id: str,
        operations: list[dict[str, Any]],
        max_parallel: int = 1,
    ) -> Plan:
        """Create a turbo execution plan from operation specifications.

        Args:
            plan_id: Unique identifier for the plan
            operations: List of operation dicts with 'type', 'args', 'priority', 'id'
            max_parallel: Maximum parallel operations (future use)

        Returns:
            Configured Plan ready for execution
        """
        ops = []
        for op_spec in operations:
            op = Operation(
                type=OperationType(op_spec["type"]),
                args=op_spec.get("args", {}),
                priority=op_spec.get("priority", 100),
                id=op_spec.get("id"),
            )
            ops.append(op)

        return Plan(
            id=plan_id,
            operations=ops,
            max_parallel=max_parallel,
        )
