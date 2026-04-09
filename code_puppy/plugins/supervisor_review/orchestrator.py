"""Core supervisor-review iteration loop (bd code_puppy-79p).

Ports Orion's multi-agent supervisor-review pattern from
orion-multistep-analysis/src/research_agent/supervisor/orchestrator.py:582-742
with the following improvements:

1. Agent-agnostic: worker/supervisor agents are parameters, not hardcoded.
2. Structured errors: per-iteration try/except so one agent failure doesn't
   crash the whole loop; returns a partial result.
3. Dependency injection: invoke_agent_fn is injectable for testing.
4. Pluggable satisfaction: three checker strategies (see satisfaction.py).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

# Regex for safe filename components: rejects path traversal and separators
# Allows alphanumeric, underscore, hyphen, dot (but not leading/trailing dots)
_SAFE_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")

from code_puppy.plugins.supervisor_review.models import (
    FeedbackEntry,
    IterationResult,
    ReviewLoopConfig,
    SupervisorReviewResult,
)
from code_puppy.plugins.supervisor_review.satisfaction import (
    get_satisfaction_checker,
)

logger = logging.getLogger(__name__)

__all__ = [
    "InvokeAgentFn",
    "run_supervisor_review_loop",
    "format_feedback_history",
    "build_iteration_prompt",
    "build_supervisor_prompt",
]


# Type alias for the injectable invoke_agent function
# Signature: invoke_agent_fn(agent_name, prompt, session_id=None) -> str
InvokeAgentFn = Callable[..., Awaitable[str]]


# ---------------------------------------------------------------------------
# Prompt construction helpers
# ---------------------------------------------------------------------------


def format_feedback_history(feedback: list[FeedbackEntry]) -> str:
    """Format accumulated feedback into an injectable prompt block.

    Port of Orion's _format_feedback_history (orchestrator.py:167-176).
    """
    if not feedback:
        return ""
    lines: list[str] = []
    for entry in feedback:
        lines.append(f"### Iteration {entry.iteration} feedback:")
        lines.append(entry.supervisor_output.strip())
        lines.append("")
    return "\n".join(lines).strip()


def build_iteration_prompt(
    task_prompt: str,
    feedback: list[FeedbackEntry],
    iteration: int,
) -> str:
    """Construct the prompt for a worker agent on iteration N.

    On iteration 1, returns task_prompt unchanged. On later iterations, appends
    a "Previous supervisor feedback to address" block with all accumulated
    feedback, matching Orion's pattern at orchestrator.py:220-226.
    """
    if iteration == 1 or not feedback:
        return task_prompt

    feedback_block = format_feedback_history(feedback)
    return (
        f"{task_prompt}\n\n"
        f"## Previous supervisor feedback to address (iteration {iteration}):\n\n"
        f"{feedback_block}\n\n"
        f"Address each item above, updating or regenerating artifacts as needed. "
        f"Do not simply repeat your previous answer."
    )


def build_supervisor_prompt(
    task_prompt: str,
    worker_outputs: dict[str, str],
    iteration: int,
    satisfaction_mode: str,
) -> str:
    """Construct the prompt for the supervisor agent.

    Includes the original task, all worker outputs labeled by agent name, and
    instructions matching the configured satisfaction_mode.
    """
    parts: list[str] = [
        f"You are supervising iteration {iteration} of a multi-agent review loop.",
        "",
        "## Original task",
        task_prompt.strip(),
        "",
        "## Worker agent outputs",
    ]
    for agent_name, output in worker_outputs.items():
        parts.append(f"### {agent_name}")
        parts.append(output.strip() if output else "(no output)")
        parts.append("")

    parts.append("## Your job")
    if satisfaction_mode == "structured":
        parts.append(
            "Review all worker outputs against the original task. Respond with a JSON "
            'object: {"verdict": "approved" or "rejected", "confidence": 0.0-1.0, '
            '"reason": "...", "issues": ["..."], "next_steps": ["..."]}. '
            'Use "approved" ONLY when every requirement is fully met.'
        )
    elif satisfaction_mode == "keyword":
        parts.append(
            "Review all worker outputs against the original task. "
            "End your response with EXACTLY one of these phrases: "
            '"fully met" (if all requirements are satisfied) or '
            '"needs work" (if more iteration is required). '
            "Before that final phrase, list the specific issues or confirmations."
        )
    else:  # llm_judge
        parts.append(
            "Review all worker outputs against the original task. Explain your "
            "assessment in detail. A separate LLM will judge whether you consider "
            "the work complete, so be explicit about approval or rejection."
        )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# The main loop
# ---------------------------------------------------------------------------


async def _default_invoke_agent(
    agent_name: str, prompt: str, session_id: str | None = None
) -> str:
    """Default invoke_agent adapter. Imports lazily to avoid circular deps.

    In Round A, this function may not be fully wired — Round B will complete
    the integration with code_puppy.tools.agent_tools.invoke_agent.
    """
    try:
        from code_puppy.tools.agent_tools import invoke_agent as real_invoke
    except ImportError as exc:
        raise RuntimeError(
            "invoke_agent is unavailable — supervisor_review plugin requires "
            "code_puppy.tools.agent_tools (Round B integration pending)"
        ) from exc

    # The real invoke_agent may be sync or async; adapt accordingly.
    result = real_invoke(agent_name=agent_name, prompt=prompt, session_id=session_id)
    if asyncio.iscoroutine(result):
        result = await result
    # real_invoke may return a dict or an object — extract text
    if isinstance(result, dict):
        return str(result.get("response") or result.get("output") or result)
    if hasattr(result, "response"):
        return str(getattr(result, "response"))
    return str(result)


async def run_supervisor_review_loop(
    config: ReviewLoopConfig,
    *,
    invoke_agent_fn: InvokeAgentFn | None = None,
    artifacts_root: Path | None = None,
) -> SupervisorReviewResult:
    """Run a multi-agent supervisor-review iteration loop.

    Sequence per iteration:
        1. For each worker agent in config.worker_agents, invoke with the
           augmented prompt (task + feedback history).
        2. Invoke the supervisor with all worker outputs.
        3. Check satisfaction via the configured checker.
        4. If satisfied -> break. Otherwise -> accumulate feedback and loop.

    Returns a SupervisorReviewResult with per-iteration snapshots. Never raises
    on agent failures — records errors in the result instead.
    """
    invoke = invoke_agent_fn or _default_invoke_agent
    checker = get_satisfaction_checker(config.satisfaction_mode)

    feedback_history: list[FeedbackEntry] = []
    iterations: list[IterationResult] = []
    final_worker_outputs: dict[str, str] = {}
    final_supervisor_output: str = ""
    satisfied = False
    last_error: str | None = None

    for iteration in range(1, config.max_iterations + 1):
        iter_start = time.time()
        iter_result = IterationResult(iteration=iteration)
        worker_outputs: dict[str, str] = {}

        # 1. Run each worker agent sequentially
        iteration_prompt = build_iteration_prompt(
            config.task_prompt, feedback_history, iteration
        )

        agents_failed = False
        for agent_name in config.worker_agents:
            session_id = _build_session_id(config.session_prefix, agent_name, iteration)
            try:
                output = await invoke(
                    agent_name=agent_name,
                    prompt=iteration_prompt,
                    session_id=session_id,
                )
                worker_outputs[agent_name] = str(output) if output is not None else ""
            except Exception as exc:
                err_msg = f"worker agent {agent_name!r} failed: {exc}"
                logger.exception("supervisor_review: %s", err_msg)
                iter_result.error = err_msg
                worker_outputs[agent_name] = f"[ERROR: {exc}]"
                agents_failed = True
                last_error = err_msg
                break  # don't call supervisor if a worker failed catastrophically

        iter_result.worker_outputs = worker_outputs

        if agents_failed:
            iter_result.duration_seconds = time.time() - iter_start
            iterations.append(iter_result)
            break  # abort the loop; return partial result

        # 2. Run supervisor
        supervisor_prompt = build_supervisor_prompt(
            config.task_prompt, worker_outputs, iteration, config.satisfaction_mode
        )
        supervisor_session = _build_session_id(
            config.session_prefix, config.supervisor_agent, iteration
        )
        try:
            supervisor_output = await invoke(
                agent_name=config.supervisor_agent,
                prompt=supervisor_prompt,
                session_id=supervisor_session,
            )
            supervisor_output = (
                str(supervisor_output) if supervisor_output is not None else ""
            )
        except Exception as exc:
            err_msg = f"supervisor agent {config.supervisor_agent!r} failed: {exc}"
            logger.exception("supervisor_review: %s", err_msg)
            iter_result.error = err_msg
            iter_result.duration_seconds = time.time() - iter_start
            iterations.append(iter_result)
            last_error = err_msg
            break

        iter_result.supervisor_output = supervisor_output

        # 3. Check satisfaction
        try:
            satisfaction = checker.is_satisfied(supervisor_output)
        except Exception as exc:
            logger.exception("supervisor_review: satisfaction checker failed: %s", exc)
            satisfaction = None
            iter_result.error = f"satisfaction checker failed: {exc}"

        iter_result.satisfaction = satisfaction
        iter_result.duration_seconds = time.time() - iter_start
        iterations.append(iter_result)

        final_worker_outputs = dict(worker_outputs)
        final_supervisor_output = supervisor_output

        if satisfaction is not None and satisfaction.satisfied:
            satisfied = True
            logger.info(
                "supervisor_review: satisfied at iteration %d (confidence=%.2f, reason=%s)",
                iteration,
                satisfaction.confidence,
                satisfaction.reason,
            )
            break

        # 4. Accumulate feedback for next iteration
        feedback_history.append(
            FeedbackEntry(iteration=iteration, supervisor_output=supervisor_output)
        )

    # Build and return the final result
    artifacts_dir_str: str | None = None
    if artifacts_root is not None:
        try:
            artifacts_dir_str = str(
                _write_artifacts(artifacts_root, config, iterations, feedback_history)
            )
        except Exception as exc:
            logger.warning("supervisor_review: failed to write artifacts: %s", exc)

    return SupervisorReviewResult(
        success=satisfied and last_error is None,
        iterations_run=len(iterations),
        max_iterations=config.max_iterations,
        iterations=iterations,
        final_worker_outputs=final_worker_outputs,
        final_supervisor_output=final_supervisor_output,
        feedback_history=feedback_history,
        error=last_error if not satisfied else None,
        artifacts_dir=artifacts_dir_str,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_agent_name(agent_name: str) -> str:
    """Sanitize agent name for use in file paths and session IDs.

    Rejects names containing path traversal or separator characters.
    Only allows alphanumeric, underscore, and hyphen.

    Raises:
        ValueError: If the agent name contains unsafe characters.
    """
    if not agent_name:
        raise ValueError("agent_name must not be empty")
    # Check for forbidden characters: path separators, backslashes, dots, NUL
    if any(c in agent_name for c in ("/", "\\", ":", "\x00", ".")):
        raise ValueError(
            f"agent_name contains forbidden characters; "
            f"only alphanumeric, underscore, and hyphen are allowed: {agent_name!r}"
        )
    # Validate against allowlist regex
    if not _SAFE_NAME_REGEX.match(agent_name):
        raise ValueError(
            f"agent_name must match pattern '^[a-zA-Z0-9_-]+$'; got {agent_name!r}"
        )
    return agent_name


def _build_session_id(
    prefix: str | None, agent_name: str, iteration: int
) -> str | None:
    """Build a per-iteration session ID for agent invocation.

    Returns None when no prefix is supplied so the caller can use whatever
    default session the underlying invoke_agent picks.

    Raises:
        ValueError: If the agent_name contains unsafe characters.
    """
    if not prefix:
        return None
    safe_agent = _sanitize_agent_name(agent_name)
    return f"{prefix}_{safe_agent}_iter{iteration}"


def _write_artifacts(
    root: Path,
    config: ReviewLoopConfig,
    iterations: list[IterationResult],
    feedback_history: list[FeedbackEntry],
) -> Path:
    """Write per-iteration transcripts to disk. Returns the artifacts directory.

    Raises:
        ValueError: If the resolved artifacts path escapes the root directory,
            or if session_prefix contains unsafe characters.
    """
    import json

    session_name = config.session_prefix or f"review_{int(time.time())}"

    # Defense-in-depth: validate session_prefix even though ReviewLoopConfig
    # should have already validated it. This catches bypass attempts.
    if config.session_prefix is not None:
        # Reject any session_prefix with path separators or traversal patterns
        if any(c in session_name for c in ("/", "\\", "\x00", ".")):
            raise ValueError(
                f"session_prefix contains unsafe characters; "
                f"possible path traversal attempt: {session_name!r}"
            )
        if not _SAFE_NAME_REGEX.match(session_name):
            raise ValueError(
                f"session_prefix must match pattern '^[a-zA-Z0-9_-]+$'; "
                f"got {session_name!r}"
            )

    artifacts_dir = root / "supervisor_review" / session_name

    # Path traversal defense: ensure resolved path is within root
    try:
        resolved_artifacts = artifacts_dir.resolve()
        resolved_root = root.resolve()
        # relative_to raises ValueError if not a subpath
        resolved_artifacts.relative_to(resolved_root)
    except (ValueError, OSError) as exc:
        raise ValueError(
            f"artifacts_dir resolves outside root; possible path traversal: "
            f"{artifacts_dir!r} not under {root!r}"
        ) from exc

    artifacts_dir.mkdir(parents=True, exist_ok=True)

    for iter_result in iterations:
        for agent_name, output in iter_result.worker_outputs.items():
            safe_agent = _sanitize_agent_name(agent_name)
            path = artifacts_dir / f"iter{iter_result.iteration}_{safe_agent}.log"
            # Double-check file path is still within artifacts_dir (paranoid)
            try:
                path.resolve().relative_to(artifacts_dir.resolve())
            except (ValueError, OSError) as exc:
                raise ValueError(
                    f"file path escapes artifacts_dir; possible path traversal: "
                    f"{path!r}"
                ) from exc
            path.write_text(output, encoding="utf-8")

        if iter_result.supervisor_output:
            supervisor_path = (
                artifacts_dir / f"iter{iter_result.iteration}_supervisor.log"
            )
            supervisor_path.write_text(iter_result.supervisor_output, encoding="utf-8")

    summary_path = artifacts_dir / "summary.json"
    summary: dict[str, Any] = {
        "config": {
            "worker_agents": list(config.worker_agents),
            "supervisor_agent": config.supervisor_agent,
            "max_iterations": config.max_iterations,
            "satisfaction_mode": config.satisfaction_mode,
        },
        "iterations_run": len(iterations),
        "feedback_history": [
            {"iteration": fe.iteration, "supervisor_output": fe.supervisor_output}
            for fe in feedback_history
        ],
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return artifacts_dir
