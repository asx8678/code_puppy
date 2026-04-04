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
from code_puppy.plugins.turbo_executor.history import get_history

# Import notifications for progress emission
try:
    from code_puppy.plugins.turbo_executor import notifications as _notifications

    _NOTIFICATIONS_AVAILABLE = True
except ImportError:
    _NOTIFICATIONS_AVAILABLE = False

# Try to import Rust turbo_ops for accelerated file operations
try:
    from turbo_ops import async_batch_execute_ops
    TURBO_OPS_ASYNC_AVAILABLE = True
except ImportError:
    TURBO_OPS_ASYNC_AVAILABLE = False
    async_batch_execute_ops = None  # type: ignore

try:
    from turbo_ops import batch_execute_ops
    from turbo_ops import list_files as turbo_list_files
    from turbo_ops import grep as turbo_grep
    from turbo_ops import read_file as turbo_read_file

    TURBO_OPS_SYNC_AVAILABLE = True
except ImportError:
    TURBO_OPS_SYNC_AVAILABLE = False
    batch_execute_ops = None  # type: ignore
    turbo_list_files = None  # type: ignore
    turbo_grep = None  # type: ignore
    turbo_read_file = None  # type: ignore

TURBO_OPS_AVAILABLE = TURBO_OPS_ASYNC_AVAILABLE or TURBO_OPS_SYNC_AVAILABLE


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
        self._turbo_ops_async_available = TURBO_OPS_ASYNC_AVAILABLE and not prefer_native_python
        self._turbo_ops_sync_available = TURBO_OPS_SYNC_AVAILABLE and not prefer_native_python

        self._operation_handlers: dict[OperationType, Callable] = {
            OperationType.LIST_FILES: self._execute_list_files,
            OperationType.GREP: self._execute_grep,
            OperationType.READ_FILES: self._execute_read_files,
            OperationType.RUN_TESTS: self._execute_run_tests,
            OperationType.DISCOVER_TESTS: self._execute_discover_tests,
        }

    @property
    def using_native_ops(self) -> bool:
        """Check if using native Python operations (fallback mode)."""
        return not (self._turbo_ops_async_available or self._turbo_ops_sync_available)

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

        result = PlanResult(
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

        # Record execution in history
        get_history().add_entry(
            plan_id=plan.id,
            num_ops=len(plan.operations),
            duration_ms=result.total_duration_ms,
            status=result.status.value,
        )

        return result

    async def _execute_sequential(self, plan: Plan) -> list[OperationResult]:
        """Execute operations sequentially in priority order with progress emission."""
        results: list[OperationResult] = []
        total = len(plan.operations)
        plan_start_time = time.perf_counter()  # Track overall plan start time

        for i, operation in enumerate(plan.operations):
            current = i + 1
            op_type = operation.type.value

            # Emit start progress
            if _NOTIFICATIONS_AVAILABLE:
                elapsed_ms = (time.perf_counter() - plan_start_time) * 1000
                _notifications.emit_operation_start(
                    current, total, op_type, operation.args, elapsed_ms
                )

            # Execute the operation
            result = await self._execute_operation(operation)
            results.append(result)

            # Emit completion or error progress
            if _NOTIFICATIONS_AVAILABLE:
                elapsed_ms = (time.perf_counter() - plan_start_time) * 1000
                if result.status == "error":
                    _notifications.emit_operation_error(
                        current, total, op_type, result.error or "Unknown error", elapsed_ms
                    )
                else:
                    _notifications.emit_operation_complete(
                        current,
                        total,
                        op_type,
                        operation.args,
                        result.duration_ms,
                        result.data,
                        elapsed_ms,
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

        if op_type == OperationType.RUN_TESTS:
            # run_tests reports errors in data["error"] or via the success flag
            if data.get("error"):
                return "error"
            # Consider it successful if the success flag is True or if there are no failed tests
            failed = data.get("failed", 0)
            errors = data.get("errors", 0)
            success = data.get("success", False)
            if failed == 0 and errors == 0 and (success or data.get("total", 0) > 0):
                return "success"
            return "error"

        if op_type == OperationType.DISCOVER_TESTS:
            # discover_tests reports errors in data["error"]
            if data.get("error"):
                return "error"
            # Consider it successful if we found test files or successfully determined no tests
            test_files = data.get("test_files", [])
            success = data.get("success", False)
            if success or test_files is not None:
                return "success"
            return "error"

        return "success"

    async def _execute_list_files(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute list_files operation with async/sync turbo_ops or native Python fallback."""
        directory = args.get("directory", ".")
        recursive = args.get("recursive", True)

        # Build operation for batch execution
        op = {
            "type": "list_files",
            "args": {"directory": directory, "recursive": recursive},
            "id": "list_files_op",
        }

        # Try async batch_execute_ops first (preferred - no to_thread needed)
        if self._turbo_ops_async_available and async_batch_execute_ops is not None:
            try:
                result = await async_batch_execute_ops([op])
                # Extract result from batch response
                if result and "results" in result and len(result["results"]) > 0:
                    op_result = result["results"][0]
                    if op_result.get("status") == "success":
                        data = op_result.get("data", {})
                        return {
                            "content": data.get("files", []),
                            "error": None,
                            "source": "turbo_ops_async",
                        }
            except Exception:
                # Fall through to next option
                pass

        # Try sync batch_execute_ops (needs to_thread)
        if self._turbo_ops_sync_available and batch_execute_ops is not None:
            try:
                result = await asyncio.to_thread(batch_execute_ops, [op], True)
                # Extract result from batch response
                if result and "results" in result and len(result["results"]) > 0:
                    op_result = result["results"][0]
                    if op_result.get("status") == "success":
                        data = op_result.get("data", {})
                        return {
                            "content": data.get("files", []),
                            "error": None,
                            "source": "turbo_ops_sync",
                        }
            except Exception:
                # Fall through to individual operations
                pass

        # Try individual sync turbo_ops functions (legacy fallback)
        if self._turbo_ops_sync_available and turbo_list_files is not None:
            try:
                result = await asyncio.to_thread(turbo_list_files, directory, recursive)
                return {
                    "content": result,
                    "error": None,
                    "source": "turbo_ops",
                }
            except Exception:
                # Fall through to native Python
                pass

        # Fallback to native Python implementation
        result = await asyncio.to_thread(_list_files, None, directory, recursive)

        return {
            "content": result.content,
            "error": result.error,
            "source": "native_python",
        }

    async def _execute_grep(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute grep operation with async/sync turbo_ops or native Python fallback."""
        search_string = args.get("search_string", "")
        directory = args.get("directory", ".")

        # Build operation for batch execution
        op = {
            "type": "grep",
            "args": {"search_string": search_string, "directory": directory},
            "id": "grep_op",
        }

        # Try async batch_execute_ops first (preferred - no to_thread needed)
        if self._turbo_ops_async_available and async_batch_execute_ops is not None:
            try:
                result = await async_batch_execute_ops([op])
                # Extract result from batch response
                if result and "results" in result and len(result["results"]) > 0:
                    op_result = result["results"][0]
                    if op_result.get("status") == "success":
                        data = op_result.get("data", {})
                        return {
                            "matches": [
                                {
                                    "file_path": m.get("file_path", ""),
                                    "line_number": m.get("line_number", 0),
                                    "line_content": m.get("line_content", ""),
                                }
                                for m in data.get("matches", [])
                            ],
                            "total_matches": data.get("total_matches", 0),
                            "error": None,
                            "source": "turbo_ops_async",
                        }
            except Exception:
                # Fall through to next option
                pass

        # Try sync batch_execute_ops (needs to_thread)
        if self._turbo_ops_sync_available and batch_execute_ops is not None:
            try:
                result = await asyncio.to_thread(batch_execute_ops, [op], True)
                # Extract result from batch response
                if result and "results" in result and len(result["results"]) > 0:
                    op_result = result["results"][0]
                    if op_result.get("status") == "success":
                        data = op_result.get("data", {})
                        return {
                            "matches": [
                                {
                                    "file_path": m.get("file_path", ""),
                                    "line_number": m.get("line_number", 0),
                                    "line_content": m.get("line_content", ""),
                                }
                                for m in data.get("matches", [])
                            ],
                            "total_matches": data.get("total_matches", 0),
                            "error": None,
                            "source": "turbo_ops_sync",
                        }
            except Exception:
                # Fall through to individual operations
                pass

        # Try individual sync turbo_ops functions (legacy fallback)
        if self._turbo_ops_sync_available and turbo_grep is not None:
            try:
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
                # Fall through to native Python
                pass

        # Fallback to native Python implementation
        result = await asyncio.to_thread(_grep, None, search_string, directory)

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
        """Execute read_files operation with async/sync turbo_ops or native Python fallback."""
        file_paths = args.get("file_paths", [])
        start_line = args.get("start_line")
        num_lines = args.get("num_lines")

        files_data: list[dict[str, Any]] = []

        # Build operation for batch execution
        op = {
            "type": "read_files",
            "args": {
                "file_paths": file_paths,
                "start_line": start_line,
                "num_lines": num_lines,
            },
            "id": "read_files_op",
        }

        # Try async batch_execute_ops first (preferred - no to_thread needed)
        if self._turbo_ops_async_available and async_batch_execute_ops is not None:
            try:
                result = await async_batch_execute_ops([op])
                # Extract result from batch response
                if result and "results" in result and len(result["results"]) > 0:
                    op_result = result["results"][0]
                    if op_result.get("status") == "success":
                        data = op_result.get("data", {})
                        files = data.get("files", [])
                        files_data = [
                            {
                                "file_path": f.get("file_path", ""),
                                "content": f.get("content"),
                                "num_tokens": f.get("num_tokens", 0),
                                "error": f.get("error"),
                                "success": f.get("success", False),
                            }
                            for f in files
                        ]
                        return {
                            "files": files_data,
                            "total_files": len(file_paths),
                            "successful_reads": sum(1 for f in files_data if f["success"]),
                            "source": "turbo_ops_async",
                        }
            except Exception:
                # Fall through to next option
                files_data = []

        # Try sync batch_execute_ops (needs to_thread)
        if self._turbo_ops_sync_available and batch_execute_ops is not None and not files_data:
            try:
                result = await asyncio.to_thread(batch_execute_ops, [op], True)
                # Extract result from batch response
                if result and "results" in result and len(result["results"]) > 0:
                    op_result = result["results"][0]
                    if op_result.get("status") == "success":
                        data = op_result.get("data", {})
                        files = data.get("files", [])
                        files_data = [
                            {
                                "file_path": f.get("file_path", ""),
                                "content": f.get("content"),
                                "num_tokens": f.get("num_tokens", 0),
                                "error": f.get("error"),
                                "success": f.get("success", False),
                            }
                            for f in files
                        ]
                        return {
                            "files": files_data,
                            "total_files": len(file_paths),
                            "successful_reads": sum(1 for f in files_data if f["success"]),
                            "source": "turbo_ops_sync",
                        }
            except Exception:
                # Fall through to individual operations
                files_data = []

        # Try individual sync turbo_ops functions (legacy fallback)
        if self._turbo_ops_sync_available and turbo_read_file is not None and not files_data:
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
                # Fall through to native Python
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

    async def _execute_run_tests(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute run_tests operation using pytest or other test runners."""
        test_path = args.get("test_path", ".")
        runner = args.get("runner", "pytest")
        verbose = args.get("verbose", False)
        extra_args = args.get("extra_args", "")

        # Build the command
        if runner == "pytest":
            # Use pytest with JSON output for structured results when possible
            cmd_parts = ["pytest", test_path, "-v" if verbose else "-q"]

            # Add extra args if provided
            if extra_args:
                cmd_parts.extend(extra_args.split())

            # Try to get structured output with pytest-json-report if available
            # Otherwise fall back to parsing text output
            cmd_parts.extend(["--tb=short"])

            cmd = " ".join(cmd_parts)
        else:
            # Generic test runner support
            cmd = f"{runner} {test_path}"
            if extra_args:
                cmd += f" {extra_args}"
        try:
            # Import here to avoid circular imports
            from code_puppy.tools.command_runner import run_shell_command

            # Run the tests
            result = await run_shell_command(
                context=None,
                command=cmd,
                cwd=None,
                timeout=300,  # 5 minute timeout for tests
            )

            # Parse the output for structured results
            # ShellCommandOutput is a Pydantic model with attributes, not a dict
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            exit_code = result.exit_code if result.exit_code is not None else 1
            full_output = stdout + (f"\n{stderr}" if stderr else "")

            # Parse pytest output for test counts
            test_results = self._parse_pytest_output(full_output, exit_code)

            return {
                "test_path": test_path,
                "runner": runner,
                "command": cmd,
                "exit_code": exit_code,
                "output": full_output,
                **test_results,
                "source": "native_python",
            }

        except Exception as e:
            return {
                "test_path": test_path,
                "runner": runner,
                "command": cmd,
                "exit_code": -1,
                "output": "",
                "error": str(e),
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "total": 0,
                "duration_seconds": 0.0,
                "success": False,
                "source": "native_python",
            }

    async def _execute_discover_tests(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute discover_tests operation to find available tests without running them."""
        test_path = args.get("test_path", ".")
        runner = args.get("runner", "pytest")
        pattern = args.get("pattern", "")

        if runner == "pytest":
            # Use pytest --collect-only to discover tests without running them
            cmd_parts = ["pytest", test_path, "--collect-only"]

            if pattern:
                cmd_parts.extend(["-k", pattern])

            cmd = " ".join(cmd_parts)
        elif runner == "unittest":
            # Use unittest discover to find tests
            cmd_parts = ["python", "-m", "unittest", "discover", "-s", test_path]

            if pattern:
                cmd_parts.extend(["-p", pattern])

            cmd = " ".join(cmd_parts)
        else:
            return {
                "test_path": test_path,
                "runner": runner,
                "pattern": pattern,
                "test_files": [],
                "test_count": 0,
                "error": f"Unsupported test runner: {runner}",
                "success": False,
                "source": "native_python",
            }

        try:
            # Import here to avoid circular imports
            from code_puppy.tools.command_runner import run_shell_command

            # Run the discovery
            result = await run_shell_command(
                context=None,
                command=cmd,
                cwd=None,
                timeout=60,  # 1 minute timeout for discovery
            )

            # Parse the output
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            exit_code = result.exit_code if result.exit_code is not None else 1
            full_output = stdout + (f"\n{stderr}" if stderr else "")

            # Parse discovery results
            discovery_results = self._parse_pytest_discovery(full_output, exit_code)

            return {
                "test_path": test_path,
                "runner": runner,
                "pattern": pattern,
                "command": cmd,
                "exit_code": exit_code,
                "output": full_output,
                **discovery_results,
                "success": discovery_results.get("test_count", 0) > 0 or exit_code == 0,
                "source": "native_python",
            }

        except Exception as e:
            return {
                "test_path": test_path,
                "runner": runner,
                "pattern": pattern,
                "command": cmd,
                "exit_code": -1,
                "output": "",
                "error": str(e),
                "test_files": [],
                "test_count": 0,
                "success": False,
                "source": "native_python",
            }

    def _parse_pytest_discovery(self, output: str, exit_code: int) -> dict[str, Any]:
        """Parse pytest --collect-only output to extract test discovery results.

        Returns:
            Dict with test_files, test_count, and test_modules.
        """
        import re

        result = {
            "test_files": [],
            "test_modules": [],
            "test_count": 0,
            "test_items": [],
        }

        if not output:
            return result

        # Parse test files from output
        # Pattern: <Module test_file.py> or <TestClass ClassName> or <Function test_name>
        test_file_pattern = r"<Module\s+([^>]+)>"
        test_module_matches = re.findall(test_file_pattern, output)

        # Parse test functions/classes
        test_item_pattern = r"<(Function|Test|UnitTestCase|TestCase)\s+([^>]+)>"
        test_items = re.findall(test_item_pattern, output)

        # Count collected tests
        collected_pattern = r"collected\s+(\d+)\s+items?"
        collected_match = re.search(collected_pattern, output, re.IGNORECASE)

        if collected_match:
            result["test_count"] = int(collected_match.group(1))
        else:
            # Fallback: count test items found
            result["test_count"] = len(test_items)

        # Extract unique test files/modules
        seen_files = set()
        for module in test_module_matches:
            if module not in seen_files:
                seen_files.add(module)
                result["test_files"].append(module)

        # Extract test items
        for item_type, item_name in test_items:
            result["test_items"].append({
                "type": item_type,
                "name": item_name,
            })

        # Extract test modules (directory names)
        dir_pattern = r"<Dir\s+([^>]+)>"
        dir_matches = re.findall(dir_pattern, output)
        result["test_modules"] = list(set(dir_matches))

        return result

    def _parse_pytest_output(self, output: str, exit_code: int) -> dict[str, Any]:
        """Parse pytest output to extract test results.

        Handles various pytest output formats including:
        - Standard pytest summary line (e.g., "5 passed, 2 failed, 1 skipped")
        - pytest-json-report output
        - Short traceback format

        Returns:
            Dict with passed, failed, skipped, error counts and success flag.
        """
        import re

        result = {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "total": 0,
            "duration_seconds": 0.0,
            "success": exit_code == 0,
        }

        if not output:
            return result

        # Look for the summary line pattern: "X passed, Y failed, Z skipped"
        # Also matches variations like "1 passed in 0.01s" or "2 failed, 1 passed"
        summary_patterns = [
            # Pattern: "X passed, Y failed, Z skipped in 1.23s"
            r"(\d+)\s+passed(?:,\s+(\d+)\s+failed)?(?:,\s+(\d+)\s+skipped)?(?:,\s+(\d+)\s+errors?)?\s+in\s+([\d.]+)s",
            # Pattern: "X failed, Y passed, Z skipped"
            r"(\d+)\s+failed(?:,\s+(\d+)\s+passed)?(?:,\s+(\d+)\s+skipped)?(?:,\s+(\d+)\s+errors?)?",
            # Pattern: "X passed, Y skipped"
            r"(\d+)\s+passed(?:,\s+(\d+)\s+skipped)?\s+in\s+([\d.]+)s",
            # Pattern for just "X passed in 0.01s"
            r"(\d+)\s+passed\s+in\s+([\d.]+)s",
        ]

        for pattern in summary_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                groups = match.groups()

                # Extract counts based on pattern match
                if "failed" in pattern and "passed" in pattern:
                    # Pattern with both failed and passed
                    failed_match = re.search(r"(\d+)\s+failed", output, re.IGNORECASE)
                    passed_match = re.search(r"(\d+)\s+passed", output, re.IGNORECASE)
                    skipped_match = re.search(r"(\d+)\s+skipped", output, re.IGNORECASE)
                    error_match = re.search(r"(\d+)\s+error", output, re.IGNORECASE)

                    result["failed"] = int(failed_match.group(1)) if failed_match else 0
                    result["passed"] = int(passed_match.group(1)) if passed_match else 0
                    result["skipped"] = int(skipped_match.group(1)) if skipped_match else 0
                    result["errors"] = int(error_match.group(1)) if error_match else 0

                    # Try to extract duration
                    duration_match = re.search(r"in\s+([\d.]+)s", output)
                    if duration_match:
                        result["duration_seconds"] = float(duration_match.group(1))

                elif "passed" in pattern:
                    passed_match = re.search(r"(\d+)\s+passed", output, re.IGNORECASE)
                    skipped_match = re.search(r"(\d+)\s+skipped", output, re.IGNORECASE)

                    result["passed"] = int(passed_match.group(1)) if passed_match else 0
                    result["skipped"] = int(skipped_match.group(1)) if skipped_match else 0

                    # Extract duration
                    if len(groups) >= 2 and groups[-1]:
                        try:
                            result["duration_seconds"] = float(groups[-1])
                        except ValueError:
                            pass

                break  # Found a match, stop searching

        # Calculate total
        result["total"] = result["passed"] + result["failed"] + result["skipped"] + result["errors"]

        # If we couldn't parse the summary but exit code is 0, assume all passed
        if result["total"] == 0 and exit_code == 0 and output:
            # Try to count test files or individual tests
            test_file_matches = re.findall(r"(test_.+\.py|.+_test\.py)::", output)
            if test_file_matches:
                result["passed"] = len(test_file_matches)
                result["total"] = len(test_file_matches)

        # Success means: no test failures/errors (even if exit code is non-zero due to coverage, etc.)
        # Exit code 0 = all good, 1 = tests failed or other issue, 2 = pytest error, 5 = no tests collected
        # We consider it successful if no actual tests failed, regardless of exit code
        result["success"] = result["failed"] == 0 and result["errors"] == 0 and result["total"] > 0

        return result

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

            if op.type == OperationType.RUN_TESTS:
                runner = op.args.get("runner", "pytest")
                if runner not in ("pytest", "unittest", "tox", "nox"):
                    errors.append(f"{prefix}: unsupported test runner '{runner}'")

            if op.type == OperationType.DISCOVER_TESTS:
                runner = op.args.get("runner", "pytest")
                if runner not in ("pytest", "unittest"):
                    errors.append(f"{prefix}: unsupported test runner '{runner}'")

        return errors
