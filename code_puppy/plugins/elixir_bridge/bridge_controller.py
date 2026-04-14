"""Bridge Controller - Dispatches JSON-RPC commands to Python functionality.

This module implements the command dispatcher for the Elixir bridge.
It translates JSON-RPC method calls into Python tool/agent invocations
and returns results in JSON-RPC format.

Implements BRIDGE_PROTOCOL_V1 with canonical method names:
- run.start, run.cancel, initialize, exit
- invoke_agent, run_shell, file_list, file_read, file_write, grep_search

Architecture:
    ┌─────────────┐     JSON-RPC      ┌──────────────────┐
    │   stdin     │ ────────────────▶ │  BridgeController │
    └─────────────┘                   │  .dispatch()      │
                                      └────────┬─────────┘
                                               │
                          ┌────────────────────┼────────────────────┐
                          ▼                    ▼                    ▼
                  ┌──────────────┐    ┌─────────────┐    ┌────────────┐
                  │  Agent Tools │    │  Shell Cmds │    │  File Ops  │
                  └──────────────┘    └─────────────┘    └────────────┘

See: docs/protocol/BRIDGE_PROTOCOL_V1.md for full specification.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .wire_protocol import from_wire_params, WireMethodError


class BridgeController:
    """Dispatches JSON-RPC commands to Python functionality.

    This controller is instantiated in bridge mode and handles the
    translation between Elixir JSON-RPC commands and Python tools.
    Uses BRIDGE_PROTOCOL_V1 canonical method names.

    Example:
        controller = BridgeController()
        response = await controller.dispatch({
            "jsonrpc": "2.0",
            "id": "1",
            "method": "run.start",
            "params": {"agent_name": "turbo-executor", "prompt": "Analyze code"}
        })
        # response: {"status": "started", "run_id": "..."}
    """

    def __init__(self) -> None:
        """Initialize the bridge controller."""
        self._running = True
        self._command_count = 0
        self._active_runs: dict[str, Any] = {}  # Track active runs for cancel support

    async def shutdown(self) -> None:
        """Shutdown the controller and cleanup resources."""
        self._running = False
        # Cancel any active runs
        for _run_id, run_info in list(self._active_runs.items()):
            if hasattr(run_info, "cancel"):
                await run_info.cancel()
        self._active_runs.clear()

    async def dispatch(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatch a JSON-RPC request to the appropriate handler.

        Args:
            request: JSON-RPC request dict with "method" and "params"

        Returns:
            Result dict for successful execution, None for notifications

        Raises:
            WireMethodError: If method is unknown or params invalid

        Supported V1 methods:
            - run.start: Start a new agent run
            - run.cancel: Cancel an active run
            - initialize: Initialize the bridge
            - exit: Shutdown the bridge
            - invoke_agent: Run an agent (legacy)
            - run_shell: Execute shell command
            - file_list: List directory
            - file_read: Read file
            - file_write: Write file
            - grep_search: Search files
            - get_status: Bridge status
            - ping: Health check
        """
        method = request.get("method", "")
        params = request.get("params", {})

        self._command_count += 1

        # Map method names to handlers (V1 canonical + legacy)
        handlers: dict[str, Any] = {
            "run.start": self._handle_run_start,
            "run.cancel": self._handle_run_cancel,
            "initialize": self._handle_initialize,
            "exit": self._handle_exit,
            "invoke_agent": self._handle_invoke_agent,
            "run_shell": self._handle_run_shell,
            "file_list": self._handle_file_list,
            "file_read": self._handle_file_read,
            "file_write": self._handle_file_write,
            "grep_search": self._handle_grep_search,
            "get_status": self._handle_get_status,
            "ping": self._handle_ping,
        }

        handler = handlers.get(method)
        if handler is None:
            raise WireMethodError(f"Unknown method: {method}", code=-32601)

        # Validate and convert params from wire format
        try:
            validated_params = from_wire_params(method, params)
        except (TypeError, ValueError) as e:
            raise WireMethodError(f"Invalid params: {e}", code=-32602)

        # Execute handler
        return await handler(validated_params)

    async def _handle_run_start(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle run.start method (V1 canonical).

        Args:
            params: {"agent_name": str, "prompt": str, "session_id": str | None,
                     "run_id": str | None, "context": dict}

        Returns:
            {"status": "started", "run_id": str, "session_id": str | None}
        """
        agent_name = params["agent_name"]
        prompt = params["prompt"]
        session_id = params.get("session_id")
        run_id = params.get("run_id", f"run-{asyncio.get_event_loop().time()}")

        # Check for duplicate run_id
        if run_id in self._active_runs:
            raise WireMethodError(
                f"Run already active: {run_id}",
                code=-32002  # Run already active
            )

        try:
            # Store run info for cancellation support
            self._active_runs[run_id] = {
                "agent_name": agent_name,
                "status": "starting",
            }

            # Start the agent (non-blocking - runs in background)
            # In full implementation, this would spawn a task and return immediately
            asyncio.create_task(
                self._execute_agent_run(run_id, agent_name, prompt, session_id)
            )

            return {
                "status": "started",
                "run_id": run_id,
                "session_id": session_id,
                "agent_name": agent_name,
            }
        except Exception as e:
            self._active_runs.pop(run_id, None)
            raise WireMethodError(f"Failed to start run: {e}", code=-32000)

    async def _execute_agent_run(
        self,
        run_id: str,
        agent_name: str,
        prompt: str,
        session_id: str | None,
    ) -> None:
        """Execute an agent run and emit lifecycle events.

        This runs in a background task and emits run.status, run.text,
        run.completed or run.failed notifications.
        """
        from code_puppy.tools.agent_tools import invoke_agent_headless

        try:
            self._active_runs[run_id]["status"] = "running"

            # Execute agent
            await invoke_agent_headless(
                agent_name=agent_name,
                prompt=prompt,
                session_id=session_id,
            )

            # Mark as completed
            self._active_runs[run_id]["status"] = "completed"
            self._active_runs.pop(run_id, None)

        except asyncio.CancelledError:
            self._active_runs.pop(run_id, None)
            raise
        except Exception:
            self._active_runs.pop(run_id, None)
            # Exception will be handled by the agent system

    async def _handle_run_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle run.cancel method (V1 canonical).

        Args:
            params: {"run_id": str, "reason": str}

        Returns:
            {"status": "cancelled", "run_id": str}
        """
        run_id = params["run_id"]
        reason = params.get("reason", "user_requested")

        if run_id not in self._active_runs:
            raise WireMethodError(f"Run not found: {run_id}", code=-32001)

        try:
            # Remove from active runs (actual cancellation TODO)
            # TODO(code-puppy-XXX): Implement actual cancellation of the running task
            # This requires storing the task reference in _active_runs
            self._active_runs.pop(run_id, None)

            return {
                "status": "cancelled",
                "run_id": run_id,
                "reason": reason,
            }
        except Exception as e:
            raise WireMethodError(f"Failed to cancel run: {e}", code=-32003)

    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle initialize method (V1 canonical).

        Args:
            params: {"capabilities": list, "config": dict}

        Returns:
            {"status": "initialized", "capabilities": list}
        """
        # Store configuration if needed
        # Future: validate requested capabilities against params.get("capabilities", [])
        # and store config from params.get("config", {})

        return {
            "status": "initialized",
            "capabilities": ["shell", "file_ops", "agents", "event_stream"],
            "version": "1.0.0",
        }

    async def _handle_exit(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle exit method (V1 canonical).

        Args:
            params: {"reason": str, "timeout_ms": int}

        Returns:
            {"status": "exiting", "reason": str}
        """
        reason = params.get("reason", "shutdown")

        # Initiate graceful shutdown
        self._running = False

        return {
            "status": "exiting",
            "reason": reason,
            "timeout_ms": params.get("timeout_ms", 5000),
        }

    async def _handle_invoke_agent(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle invoke_agent method.

        Args:
            params: {"agent_name": str, "prompt": str, "session_id": str | None}

        Returns:
            {"response": str, "success": bool}
        """
        from code_puppy.tools.agent_tools import invoke_agent_headless

        agent_name = params["agent_name"]
        prompt = params["prompt"]
        session_id = params.get("session_id")

        try:
            # invoke_agent_headless returns string directly
            response = await invoke_agent_headless(
                agent_name=agent_name,
                prompt=prompt,
                session_id=session_id,
            )
            return {
                "success": True,
                "response": response,
                "agent_name": agent_name,
                "session_id": session_id,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "agent_name": agent_name,
            }

    async def _handle_run_shell(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle run_shell method.

        Args:
            params: {"command": str, "cwd": str | None, "timeout": int}

        Returns:
            {"stdout": str, "stderr": str, "exit_code": int, "success": bool}
        """
        from code_puppy.tools.command_runner import run_shell_command

        command = params["command"]
        cwd = params.get("cwd")
        timeout = params.get("timeout", 60)

        # Create a minimal RunContext
        # In bridge mode, we don't have the full agent context
        class MinimalContext:
            pass

        context = MinimalContext()

        try:
            result = await run_shell_command(
                context=context,
                command=command,
                cwd=cwd,
                timeout=timeout,
            )

            return {
                "success": result.success,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "execution_time": result.execution_time,
                "command": command,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "command": command,
            }

    async def _handle_file_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle file_list method.

        Args:
            params: {"directory": str, "recursive": bool}

        Returns:
            {"files": [...], "total_size": int, "file_count": int}
        """
        import os

        directory = params["directory"]
        recursive = params.get("recursive", False)

        try:
            files = []
            total_size = 0
            file_count = 0
            dir_count = 0

            if recursive:
                for root, dirs, filenames in os.walk(directory):
                    depth = root.replace(directory, "").count(os.sep)
                    dir_count += len(dirs)

                    for filename in filenames:
                        filepath = os.path.join(root, filename)
                        try:
                            size = os.path.getsize(filepath)
                            total_size += size
                            file_count += 1
                            files.append({
                                "path": filepath,
                                "type": "file",
                                "size": size,
                                "depth": depth,
                            })
                        except OSError:
                            pass
            else:
                entries = os.listdir(directory)
                for entry in entries:
                    path = os.path.join(directory, entry)
                    try:
                        stat = os.stat(path)
                        is_dir = os.path.isdir(path)
                        files.append({
                            "path": path,
                            "type": "dir" if is_dir else "file",
                            "size": 0 if is_dir else stat.st_size,
                            "depth": 0,
                        })
                        if is_dir:
                            dir_count += 1
                        else:
                            file_count += 1
                            total_size += stat.st_size
                    except OSError:
                        pass

            return {
                "success": True,
                "directory": directory,
                "files": files,
                "total_size": total_size,
                "file_count": file_count,
                "dir_count": dir_count,
                "recursive": recursive,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "directory": directory,
            }

    async def _handle_file_read(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle file_read method.

        Args:
            params: {"path": str, "start_line": int | None, "num_lines": int | None}

        Returns:
            {"content": str, "total_lines": int, "success": bool}
        """
        path = params["path"]
        start_line = params.get("start_line")
        num_lines = params.get("num_lines")

        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                total_lines = len(lines)

                if start_line is not None:
                    start_idx = start_line - 1  # Convert to 0-indexed
                    end_idx = start_idx + (num_lines or len(lines))
                    selected = lines[start_idx:end_idx]
                    content = "".join(selected)
                else:
                    content = "".join(lines)

                return {
                    "success": True,
                    "path": path,
                    "content": content,
                    "total_lines": total_lines,
                    "start_line": start_line,
                    "num_lines_read": num_lines if start_line else total_lines,
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "path": path,
            }

    async def _handle_file_write(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle file_write method.

        Args:
            params: {"path": str, "content": str}

        Returns:
            {"success": bool, "bytes_written": int}
        """
        path = params["path"]
        content = params["content"]

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
                bytes_written = len(content.encode("utf-8"))

                return {
                    "success": True,
                    "path": path,
                    "bytes_written": bytes_written,
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "path": path,
            }

    async def _handle_grep_search(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle grep_search method.

        Args:
            params: {"search_string": str, "directory": str}

        Returns:
            {"matches": [...], "total_matches": int}
        """
        import os
        import re

        search_string = params["search_string"]
        directory = params.get("directory", ".")

        try:
            # Compile regex pattern
            pattern = re.compile(search_string)

            matches = []
            files_searched = 0

            for root, _, filenames in os.walk(directory):
                for filename in filenames:
                    if filename.endswith(".pyc") or "__pycache__" in root:
                        continue

                    filepath = os.path.join(root, filename)
                    files_searched += 1

                    try:
                        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                            for line_num, line in enumerate(f, 1):
                                if pattern.search(line):
                                    matches.append({
                                        "file_path": filepath,
                                        "line_number": line_num,
                                        "line_content": line.rstrip("\\n"),
                                    })
                    except (OSError, UnicodeDecodeError):
                        pass

            return {
                "success": True,
                "search_term": search_string,
                "directory": directory,
                "matches": matches,
                "total_matches": len(matches),
                "files_searched": files_searched,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "search_term": search_string,
            }

    async def _handle_get_status(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle get_status method.

        Returns:
            Bridge status and health information
        """
        import sys

        return {
            "success": True,
            "bridge_version": "1.0.0",
            "commands_processed": self._command_count,
            "running": self._running,
            "python_version": sys.version,
            "platform": sys.platform,
        }

    async def _handle_ping(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle ping method - simple health check."""
        return {
            "success": True,
            "pong": True,
            "timestamp": asyncio.get_event_loop().time(),
        }
