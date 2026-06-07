"""
Command execution engine for hooks.

Handles async command execution with timeout, variable substitution,
and comprehensive error handling.

Claude Code Hook Compatibility:
  - Input is passed via STDIN as JSON (primary method, Claude Code standard)
  - Input is also available via CLAUDE_TOOL_INPUT env var (legacy/convenience)
  - Exit code 0  => success, stdout shown in transcript
  - Exit code 1  => block the operation (stderr used as reason)
  - Exit code 2  => error feedback to Claude (stderr fed back as tool error)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import time
from typing import Any

from .matcher import _extract_file_path
from .models import EventData, ExecutionResult, HookConfig

logger = logging.getLogger(__name__)


def _build_stdin_payload(event_data: EventData) -> bytes:
    """
    Build the JSON payload sent to hook scripts via stdin.

    Matches the Claude Code hook input format:
    {
        "session_id": "...",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": { ... },
        "cwd": "/path/to/project",
        "permission_mode": "default"
    }
    """

    def _make_serializable(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_make_serializable(v) for v in obj]
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        try:
            return str(obj)
        except Exception:
            return "<unserializable>"

    payload = {
        "session_id": event_data.context.get("session_id", "codepuppy-session"),
        "hook_event_name": event_data.event_type,
        "tool_name": event_data.tool_name,
        "tool_input": _make_serializable(event_data.tool_args),
        "cwd": os.getcwd(),
        "permission_mode": "default",
    }
    if "result" in event_data.context:
        payload["tool_result"] = _make_serializable(event_data.context["result"])
    if "duration_ms" in event_data.context:
        payload["tool_duration_ms"] = event_data.context["duration_ms"]

    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


async def execute_hook(
    hook: HookConfig,
    event_data: EventData,
    env_vars: dict[str, str] | None = None,
) -> ExecutionResult:
    """
    Execute a hook command with timeout and variable substitution.

    Input to the hook script:
      - stdin: JSON object (Claude Code compatible format)
      - env CLAUDE_TOOL_INPUT: JSON string of tool_args (legacy)
      - env CLAUDE_PROJECT_DIR: current working directory

    Exit code semantics:
      - 0: success (stdout shown in transcript)
      - 1: block operation (stderr becomes block reason)
      - 2: error feedback to Claude without blocking
    """
    if hook.type == "prompt":
        return ExecutionResult(
            blocked=False,
            hook_command=hook.command,
            stdout=hook.command,
            exit_code=0,
            duration_ms=0.0,
            hook_id=hook.id,
        )

    command = _substitute_variables(hook.command, event_data, env_vars or {})
    stdin_payload = _build_stdin_payload(event_data)
    start_time = time.perf_counter()

    try:
        env = _build_environment(event_data, env_vars)

        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd(),
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_payload),
                timeout=hook.timeout / 1000.0,
            )
        except TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass

            duration_ms = (time.perf_counter() - start_time) * 1000
            return ExecutionResult(
                blocked=True,
                hook_command=command,
                stdout="",
                stderr=f"Command timed out after {hook.timeout}ms",
                exit_code=-1,
                duration_ms=duration_ms,
                error=f"Hook execution timed out after {hook.timeout}ms",
                hook_id=hook.id,
            )

        duration_ms = (time.perf_counter() - start_time) * 1000
        stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""
        exit_code = proc.returncode or 0

        blocked = exit_code == 1
        error = stderr_str if exit_code != 0 and stderr_str else None

        return ExecutionResult(
            blocked=blocked,
            hook_command=command,
            stdout=stdout_str,
            stderr=stderr_str,
            exit_code=exit_code,
            duration_ms=duration_ms,
            error=error,
            hook_id=hook.id,
        )

    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.error(f"Hook execution failed: {e}", exc_info=True)
        return ExecutionResult(
            blocked=False,
            hook_command=command,
            stdout="",
            stderr=str(e),
            exit_code=-1,
            duration_ms=duration_ms,
            error=f"Hook execution error: {e}",
            hook_id=hook.id,
        )


def _substitute_variables(
    command: str,
    event_data: EventData,
    env_vars: dict[str, str],
) -> str:
    # Model/tool-derived values are shell-quoted to prevent command injection:
    # a filename or tool result containing `; rm -rf ~` or `$(...)` must not
    # break out of the substituted argument.
    untrusted = {
        "CLAUDE_PROJECT_DIR": os.getcwd(),
        "tool_name": event_data.tool_name,
        "event_type": event_data.event_type,
        "file": _extract_file_path(event_data.tool_args) or "",
        "CLAUDE_TOOL_INPUT": json.dumps(event_data.tool_args),
    }
    if event_data.context:
        if "result" in event_data.context:
            untrusted["result"] = str(event_data.context["result"])
        if "duration_ms" in event_data.context:
            untrusted["duration_ms"] = str(event_data.context["duration_ms"])

    substitutions: dict[str, str] = {
        var: shlex.quote(str(value)) for var, value in untrusted.items()
    }
    # NOTE: User-configured env vars are deliberately NOT substituted into the
    # command string here. They are already exported into the subprocess
    # environment by _build_environment(), so a command can reference them as
    # ``$VAR``/``${VAR}`` and let the shell expand them. Relying on shell
    # expansion preserves intentional multi-token (word-split) expansion while
    # closing a command-injection hole: splicing an env value verbatim into the
    # command string would let a value containing ``$(...)``/backticks/``;``
    # execute, whereas shell *variable* expansion does not run command
    # substitution on the variable's contents.

    # Single pass over the trusted (quoted) substitutions. Longer names first so
    # that, e.g., "$result_x" can never be partially matched as "$result".
    keys = "|".join(
        re.escape(k) for k in sorted(substitutions, key=len, reverse=True)
    )
    pattern = re.compile(rf"\$\{{({keys})\}}|\$({keys})(?=\W|$)")

    def _replace(match: "re.Match[str]") -> str:
        return substitutions[match.group(1) or match.group(2)]

    return pattern.sub(_replace, command)


def _build_environment(
    event_data: EventData,
    env_vars: dict[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = os.getcwd()
    env["CLAUDE_TOOL_INPUT"] = json.dumps(event_data.tool_args)
    env["CLAUDE_TOOL_NAME"] = event_data.tool_name
    env["CLAUDE_HOOK_EVENT"] = event_data.event_type
    env["CLAUDE_CODE_HOOK"] = "1"

    file_path = _extract_file_path(event_data.tool_args)
    if file_path:
        env["CLAUDE_FILE_PATH"] = file_path

    if env_vars:
        env.update(env_vars)
    return env


async def execute_hooks_parallel(
    hooks: list[HookConfig],
    event_data: EventData,
    env_vars: dict[str, str] | None = None,
) -> list[ExecutionResult]:
    if not hooks:
        return []
    tasks = [execute_hook(hook, event_data, env_vars) for hook in hooks]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    final_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            final_results.append(
                ExecutionResult(
                    blocked=False,
                    hook_command=hooks[i].command,
                    stdout="",
                    stderr=str(result),
                    exit_code=-1,
                    duration_ms=0.0,
                    error=f"Hook execution failed: {result}",
                    hook_id=hooks[i].id,
                )
            )
        else:
            final_results.append(result)
    return final_results


async def execute_hooks_sequential(
    hooks: list[HookConfig],
    event_data: EventData,
    env_vars: dict[str, str] | None = None,
    stop_on_block: bool = True,
) -> list[ExecutionResult]:
    results = []
    for hook in hooks:
        result = await execute_hook(hook, event_data, env_vars)
        results.append(result)
        if stop_on_block and result.blocked:
            logger.debug(f"Hook blocked operation, stopping: {hook.command}")
            break
    return results


def get_blocking_result(results: list[ExecutionResult]) -> ExecutionResult | None:
    for result in results:
        if result.blocked:
            return result
    return None


def get_failed_results(results: list[ExecutionResult]) -> list[ExecutionResult]:
    return [result for result in results if not result.success]


def format_execution_summary(results: list[ExecutionResult]) -> str:
    if not results:
        return "No hooks executed"
    total = len(results)
    successful = sum(1 for r in results if r.success)
    blocked = sum(1 for r in results if r.blocked)
    total_duration = sum(r.duration_ms for r in results)
    summary = [
        f"Executed {total} hook(s)",
        f"Successful: {successful}",
        f"Blocked: {blocked}",
        f"Total duration: {total_duration:.2f}ms",
    ]
    if blocked > 0:
        blocking_hooks = [r for r in results if r.blocked]
        summary.append("\nBlocking hooks:")
        for result in blocking_hooks:
            summary.append(f"  - {result.hook_command}")
            if result.error:
                summary.append(f"    Error: {result.error}")
    return "\n".join(summary)
