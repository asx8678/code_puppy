"""Turbo Orchestrator — Execute batch file operations.

Provides sequential (and future parallel) execution of file operations
with structured result collection.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from collections.abc import Callable

from code_puppy.concurrency_limits import FileOpsLimiter
from code_puppy.plugins.turbo_executor.models import (
    Operation,
    OperationResult,
    OperationType,
    Plan,
    PlanResult,
    PlanStatus,
)

# Import notifications for progress emission
try:
    from code_puppy.plugins.turbo_executor import notifications as _notifications

    _NOTIFICATIONS_AVAILABLE = True
except ImportError:
    _NOTIFICATIONS_AVAILABLE = False

# Try to import Rust turbo_ops for accelerated file operations
try:
    from turbo_ops import list_files as turbo_list_files
    from turbo_ops import grep as turbo_grep
    from turbo_ops import read_file as turbo_read_file

    TURBO_OPS_AVAILABLE = True
except ImportError:
    TURBO_OPS_AVAILABLE = False
    turbo_list_files = None  # type: ignore
    turbo_grep = None  # type: ignore
    turbo_read_file = None  # type: ignore


# Fallback: Import Python-native file operations when turbo_ops unavailable
from code_puppy.tools.file_operations import (
    _grep,
    _list_files,
    _read_file_sync,
)


class TurboOrchestrator:
    """Orchestrates batch execution of file operations.

    Currently executes operations sequentially. Future versions will
    support parallel execution based on operation priorities and dependencies.

    Falls back to native Python file operations when Rust turbo_ops is unavailable.

    Example:
        plan = Plan(
            id="my-plan",
            operations=[
                Operation(type=OperationType.LIST_FILES, args={"directory": "."}),
                Operation(type=OperationType.GREP, args={"search_string": "def "}),
            ]
        )
        orchestrator = TurboOrchestrator()
        result = await orchestrator.execute(plan)
    """

    def __init__(
        self, enable_parallel: bool = False, prefer_native_python: bool = False
    ):
        """Initialize the orchestrator.

        Args:
            enable_parallel: Whether to enable parallel execution (future feature)
            prefer_native_python: Force use of native Python operations even if turbo_ops available
        """
        self.enable_parallel = enable_parallel
        self.prefer_native_python = prefer_native_python
        self._turbo_ops_available = TURBO_OPS_AVAILABLE and not prefer_native_python

        self._operation_handlers: dict[OperationType, Callable] = {
            OperationType.LIST_FILES: self._execute_list_files,
            OperationType.GREP: self._execute_grep,
            OperationType.READ_FILES: self._execute_read_files,
        }

    @property
    def using_native_ops(self) -> bool:
        """Check if using native Python operations (fallback mode)."""
        return not self._turbo_ops_available

    async def execute(self, plan: Plan) -> PlanResult:
        """Execute a plan and return results.

        Args:
            plan: The plan to execute

        Returns:
            PlanResult containing all operation results and metadata
        """
        started_at = datetime.now(timezone.utc).isoformat()
        start_time = time.perf_counter()

        results: list[OperationResult] = []
        status = PlanStatus.RUNNING

        try:
            if self.enable_parallel and plan.max_parallel > 1:
                # Future: parallel execution based on priorities
                results = await self._execute_parallel(plan)
            else:
                # Sequential execution (current default)
                results = await self._execute_sequential(plan)

            # Determine overall status
            error_count = sum(1 for r in results if r.status == "error")
            if error_count == 0:
                status = PlanStatus.COMPLETED
            elif error_count < len(results):
                status = PlanStatus.PARTIAL
            else:
                status = PlanStatus.FAILED

        except Exception as e:
            status = PlanStatus.FAILED
            # Add a synthetic result for the orchestration failure
            results.append(
                OperationResult(
                    operation_id="orchestrator",
                    type=OperationType.LIST_FILES,  # Generic fallback
                    status="error",
                    error=f"Orchestration failed: {str(e)}",
                )
            )

        completed_at = datetime.now(timezone.utc).isoformat()
        total_duration_ms = (time.perf_counter() - start_time) * 1000

        return PlanResult(
            plan_id=plan.id,
            status=status,
            operation_results=results,
            started_at=started_at,
            completed_at=completed_at,
            total_duration_ms=total_duration_ms,
            metadata={
                "total_operations": len(plan.operations),
                "successful_operations": sum(
                    1 for r in results if r.status == "success"
                ),
                "failed_operations": sum(1 for r in results if r.status == "error"),
            },
        )

    async def _execute_sequential(self, plan: Plan) -> list[OperationResult]:
        """Execute operations sequentially in priority order with progress emission."""
        results: list[OperationResult] = []
        total = len(plan.operations)

        for i, operation in enumerate(plan.operations):
            current = i + 1
            op_type = operation.type.value

            # Emit start progress
            if _NOTIFICATIONS_AVAILABLE:
                _notifications.emit_operation_start(
                    current, total, op_type, operation.args
                )

            # Execute the operation
            result = await self._execute_operation(operation)
            results.append(result)

            # Emit completion or error progress
            if _NOTIFICATIONS_AVAILABLE:
                if result.status == "error":
                    _notifications.emit_operation_error(
                        current, total, op_type, result.error or "Unknown error"
                    )
                else:
                    _notifications.emit_operation_complete(
                        current,
                        total,
                        op_type,
                        operation.args,
                        result.duration_ms,
                        result.data,
                    )

        return results

    async def _execute_parallel(self, plan: Plan) -> list[OperationResult]:
        """Execute operations in parallel with concurrency limits.

        This is a placeholder for future parallel execution.
        Currently falls back to sequential.
        """
        # TODO: Implement true parallel execution with dependency tracking
        # For now, execute sequentially to maintain consistency
        return await self._execute_sequential(plan)

    async def _execute_operation(self, operation: Operation) -> OperationResult:
        """Execute a single operation with timing and error handling."""
        start_time = time.perf_counter()

        try:
            handler = self._operation_handlers.get(operation.type)
            if not handler:
                return OperationResult(
                    operation_id=operation.id,
                    type=operation.type,
                    status="error",
                    error=f"Unknown operation type: {operation.type}",
                    duration_ms=0.0,
                )

            # Execute with file ops limiting for safety
            async with FileOpsLimiter():
                data = await handler(operation.args)

            duration_ms = (time.perf_counter() - start_time) * 1000

            # Check if operation data indicates an error (e.g., read_files with failed files)
            op_status = self._determine_operation_status(operation.type, data)

            return OperationResult(
                operation_id=operation.id,
                type=operation.type,
                status=op_status,
                data=data,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return OperationResult(
                operation_id=operation.id,
                type=operation.type,
                status="error",
                error=str(e),
                duration_ms=duration_ms,
            )

    def _determine_operation_status(self, op_type: OperationType, data: dict) -> str:
        """Determine if an operation succeeded based on its result data.

        Some operations (like read_files) can have partial failures where
        individual files fail but the operation technically completes.
        We treat these as errors if nothing succeeded.
        """
        if op_type == OperationType.READ_FILES:
            files = data.get("files", [])
            if not files:
                return "error"
            successful = sum(1 for f in files if f.get("success", False))
            if successful == 0:
                return "error"
            # If some files failed but some succeeded, we still mark as success
            # but the data contains the per-file errors
            return "success"

        if op_type == OperationType.LIST_FILES:
            # list_files reports errors in data["error"]
            if data.get("error"):
                return "error"
            return "success"

        if op_type == OperationType.GREP:
            # grep reports errors in data["error"]
            if data.get("error"):
                return "error"
            return "success"

        return "success"

    async def _execute_list_files(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute list_files operation with fallback to native Python."""
        directory = args.get("directory", ".")
        recursive = args.get("recursive", True)

        # Try turbo_ops first if available
        if self._turbo_ops_available and turbo_list_files is not None:
            try:
                # Run in thread pool since turbo_ops is likely sync
                result = await asyncio.to_thread(turbo_list_files, directory, recursive)
                return {
                    "content": result,
                    "error": None,
                    "source": "turbo_ops",
                }
            except Exception:
                # Fall through to native Python on failure
                pass

        # Fallback to native Python implementation (now async)
        result = await _list_files(None, directory, recursive)

        return {
            "content": result.content,
            "error": result.error,
            "source": "native_python",
        }

    async def _execute_grep(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute grep operation with fallback to native Python."""
        search_string = args.get("search_string", "")
        directory = args.get("directory", ".")

        # Try turbo_ops first if available
        if self._turbo_ops_available and turbo_grep is not None:
            try:
                # Run in thread pool since turbo_ops is likely sync
                result = await asyncio.to_thread(turbo_grep, search_string, directory)
                return {
                    "matches": [
                        {
                            "file_path": m.get("file_path", ""),
                            "line_number": m.get("line_number", 0),
                            "line_content": m.get("line_content", ""),
                        }
                        for m in result.get("matches", [])
                    ],
                    "total_matches": result.get("total_matches", 0),
                    "error": None,
                    "source": "turbo_ops",
                }
            except Exception:
                # Fall through to native Python on failure
                pass

        # Fallback to native Python implementation (now async)
        result = await _grep(None, search_string, directory)

        return {
            "matches": [
                {
                    "file_path": m.file_path,
                    "line_number": m.line_number,
                    "line_content": m.line_content,
                }
                for m in result.matches
            ],
            "total_matches": len(result.matches),
            "error": result.error,
            "source": "native_python",
        }

    async def _execute_read_files(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute read_files operation with fallback to native Python."""
        file_paths = args.get("file_paths", [])
        start_line = args.get("start_line")
        num_lines = args.get("num_lines")

        files_data: list[dict[str, Any]] = []

        # Try turbo_ops first if available
        if self._turbo_ops_available and turbo_read_file is not None:
            try:
                for file_path in file_paths:
                    try:
                        result = await asyncio.to_thread(
                            turbo_read_file, file_path, start_line or 0, num_lines or 0
                        )
                        files_data.append(
                            {
                                "file_path": file_path,
                                "content": result.get("content"),
                                "num_tokens": result.get("num_tokens", 0),
                                "error": None,
                                "success": True,
                            }
                        )
                    except Exception as e:
                        files_data.append(
                            {
                                "file_path": file_path,
                                "content": None,
                                "num_tokens": 0,
                                "error": str(e),
                                "success": False,
                            }
                        )

                return {
                    "files": files_data,
                    "total_files": len(file_paths),
                    "successful_reads": sum(1 for f in files_data if f["success"]),
                    "source": "turbo_ops",
                }
            except Exception:
                # Fall through to native Python on failure
                files_data = []

        # Fallback to native Python implementation
        for file_path in file_paths:
            try:
                content, num_tokens, error = await asyncio.to_thread(
                    _read_file_sync, file_path, start_line, num_lines
                )

                files_data.append(
                    {
                        "file_path": file_path,
                        "content": content,
                        "num_tokens": num_tokens,
                        "error": error,
                        "success": error is None,
                    }
                )
            except Exception as e:
                files_data.append(
                    {
                        "file_path": file_path,
                        "content": None,
                        "num_tokens": 0,
                        "error": str(e),
                        "success": False,
                    }
                )

        return {
            "files": files_data,
            "total_files": len(file_paths),
            "successful_reads": sum(1 for f in files_data if f["success"]),
            "source": "native_python",
        }

    def validate_plan(self, plan: Plan) -> list[str]:
        """Validate a plan and return list of validation errors.

        Args:
            plan: Plan to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        errors: list[str] = []

        if not plan.id:
            errors.append("Plan must have an id")

        if not plan.operations:
            errors.append("Plan must have at least one operation")

        for i, op in enumerate(plan.operations):
            prefix = f"Operation {i}"
            if op.id:
                prefix = f"Operation '{op.id}'"

            if op.type not in self._operation_handlers:
                errors.append(f"{prefix}: Unknown type '{op.type}'")

            # Validate required args
            if op.type == OperationType.GREP and "search_string" not in op.args:
                errors.append(f"{prefix}: grep requires 'search_string'")

            if op.type == OperationType.READ_FILES:
                if "file_paths" not in op.args:
                    errors.append(f"{prefix}: read_files requires 'file_paths'")
                elif not isinstance(op.args.get("file_paths"), list):
                    errors.append(f"{prefix}: read_files 'file_paths' must be a list")

        return errors
