"""Runtime manager for running Code Puppy prompts from the web dashboard."""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from code_puppy.api.approvals import get_approval_manager
from code_puppy.api.redactor import (
    redact,
    redact_event_data,
    redact_run_dict,
    sanitize_traceback,
)
from code_puppy.plugins.frontend_emitter.emitter import emit_event


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview(text: Any, max_length: int = 300) -> str:
    value = "" if text is None else str(text)
    return value if len(value) <= max_length else value[: max_length - 1] + "…"


class RuntimeManager:
    """Coordinates prompt runs, cancellation, and UI responses.

    The agent run executes in a worker thread with its own event loop.  That keeps
    the FastAPI event loop free to serve WebSocket events and approval responses
    while synchronous tool approval hooks wait for the browser.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._current_run: Optional[Dict[str, Any]] = None
        self._current_worker_task: Optional[asyncio.Task[None]] = None
        self._current_worker_loop: Optional[asyncio.AbstractEventLoop] = None
        self._current_agent_task: Optional[asyncio.Task[Any]] = None
        self._recent_runs: List[Dict[str, Any]] = []

    async def submit_prompt(
        self,
        prompt: str,
        *,
        agent: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit a prompt to the current/selected agent."""
        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("Prompt cannot be empty")

        with self._lock:
            if self._current_worker_task and not self._current_worker_task.done():
                raise RuntimeError("A prompt is already running")

            run = {
                "run_id": str(uuid4()),
                "status": "queued",
                "prompt_preview": _preview(prompt, 240),
                "agent_name": agent,
                "model_name": model,
                "created_at": _now(),
                "started_at": None,
                "ended_at": None,
                "output_preview": None,
                "error": None,
                "cancel_requested": False,
            }
            self._current_run = run
            self._current_worker_loop = None
            self._current_agent_task = None
            self._current_worker_task = asyncio.create_task(
                self._run_worker(run, prompt, agent, model)
            )

        emit_event(
            "prompt_submitted",
            redact_event_data(
                {
                    "run_id": run["run_id"],
                    "prompt_preview": redact(run["prompt_preview"], max_length=300),
                    "agent_name": agent,
                    "model_name": model,
                }
            ),
        )
        return redact_run_dict(dict(run))

    async def cancel_current_run(self, reason: Optional[str] = None) -> Dict[str, Any]:
        """Request cancellation for the active run."""
        reason = reason or "Cancelled from dashboard"
        with self._lock:
            run = self._current_run
            worker_task = self._current_worker_task
            worker_loop = self._current_worker_loop
            agent_task = self._current_agent_task
            if not run or not worker_task or worker_task.done():
                return {"cancelled": False, "reason": "No prompt is running"}
            run["cancel_requested"] = True
            run["status"] = "cancelling"

        get_approval_manager().cancel_all(reason)

        if worker_loop and agent_task and not agent_task.done():
            try:
                worker_loop.call_soon_threadsafe(agent_task.cancel)
            except RuntimeError:
                pass
        # If the agent task has not been created yet, leave the worker alive;
        # on_task_created() will notice cancel_requested and cancel it as soon
        # as the inner task exists.  Cancelling asyncio.to_thread would not stop
        # the already-started worker thread anyway.

        emit_event(
            "prompt_cancel_requested",
            redact_event_data({"run_id": run["run_id"], "reason": reason}),
        )
        return {"cancelled": True, "run_id": run["run_id"], "reason": reason}

    def get_status(self) -> Dict[str, Any]:
        """Return runtime status for the dashboard (unredacted internally).

        Callers at the HTTP/WS boundary should apply
        :func:`code_puppy.api.redactor.redact_status_payload`.
        """
        with self._lock:
            run = dict(self._current_run) if self._current_run else None
            running = bool(
                self._current_worker_task and not self._current_worker_task.done()
            )
            recent = [dict(item) for item in self._recent_runs[:10]]

        try:
            from code_puppy.messaging import get_message_bus

            bus = get_message_bus()
            pending_bus_requests = bus.pending_requests_count
            outgoing_qsize = bus.outgoing_qsize
            incoming_qsize = bus.incoming_qsize
        except Exception:
            pending_bus_requests = 0
            outgoing_qsize = 0
            incoming_qsize = 0

        return {
            "running": running,
            "current_run": run,
            "recent_runs": recent,
            "pending_approvals": get_approval_manager().list_pending(),
            "pending_bus_requests": pending_bus_requests,
            "outgoing_qsize": outgoing_qsize,
            "incoming_qsize": incoming_qsize,
        }

    def respond_to_bus_request(
        self,
        *,
        prompt_id: str,
        response_type: str,
        value: Optional[str] = None,
        confirmed: Optional[bool] = None,
        feedback: Optional[str] = None,
        selected_index: Optional[int] = None,
        selected_value: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Provide a response to a structured MessageBus request."""
        from code_puppy.messaging import get_message_bus
        from code_puppy.messaging.commands import (
            ConfirmationResponse,
            SelectionResponse,
            UserInputResponse,
        )

        bus = get_message_bus()
        if response_type == "input":
            bus.provide_response(
                UserInputResponse(prompt_id=prompt_id, value=value or "")
            )
        elif response_type == "confirmation":
            bus.provide_response(
                ConfirmationResponse(
                    prompt_id=prompt_id,
                    confirmed=bool(confirmed),
                    feedback=feedback,
                )
            )
        elif response_type == "selection":
            index = -1 if selected_index is None else int(selected_index)
            bus.provide_response(
                SelectionResponse(
                    prompt_id=prompt_id,
                    selected_index=index,
                    selected_value=selected_value or "",
                )
            )
        else:
            raise ValueError(f"Unsupported response type: {response_type}")

        emit_event(
            "ui_response",
            {"prompt_id": prompt_id, "response_type": response_type},
        )
        return {"ok": True, "prompt_id": prompt_id}

    def respond_to_approval(
        self,
        approval_id: str,
        approved: bool,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve a browser approval request."""
        ok = get_approval_manager().respond(approval_id, approved, feedback)
        if not ok:
            raise ValueError("Approval request not found or already resolved")
        return {"ok": True, "approval_id": approval_id, "approved": approved}

    async def _run_worker(
        self,
        run: Dict[str, Any],
        prompt: str,
        agent_name: Optional[str],
        model_name: Optional[str],
    ) -> None:
        """Run the prompt in a worker thread and finalize status."""
        try:
            await asyncio.to_thread(
                self._run_prompt_in_thread, run, prompt, agent_name, model_name
            )
        except asyncio.CancelledError:
            self._mark_run_cancelled(run, "Dashboard cancellation requested")
            raise
        except Exception as exc:
            self._mark_run_failed(run, exc)
        finally:
            with self._lock:
                finished = dict(run)
                if finished.get("ended_at") is None:
                    finished["ended_at"] = _now()
                self._recent_runs.insert(0, finished)
                self._recent_runs = self._recent_runs[:25]
                if (
                    self._current_run
                    and self._current_run.get("run_id") == run["run_id"]
                ):
                    self._current_run = None
                    self._current_worker_task = None
                    self._current_worker_loop = None
                    self._current_agent_task = None

    def _run_prompt_in_thread(
        self,
        run: Dict[str, Any],
        prompt: str,
        agent_name: Optional[str],
        model_name: Optional[str],
    ) -> None:
        previous_web_approvals = os.environ.get("CODE_PUPPY_WEB_APPROVALS")
        os.environ["CODE_PUPPY_WEB_APPROVALS"] = "1"
        try:
            asyncio.run(self._run_prompt_async(run, prompt, agent_name, model_name))
        finally:
            if previous_web_approvals is None:
                os.environ.pop("CODE_PUPPY_WEB_APPROVALS", None)
            else:
                os.environ["CODE_PUPPY_WEB_APPROVALS"] = previous_web_approvals

    async def _run_prompt_async(
        self,
        run: Dict[str, Any],
        prompt: str,
        agent_name: Optional[str],
        model_name: Optional[str],
    ) -> None:
        from code_puppy.agents import get_current_agent
        from code_puppy.agents.agent_manager import set_current_agent
        from code_puppy.cli_runner import run_prompt_with_attachments
        from code_puppy.config import (
            auto_save_session_if_enabled,
            save_command_to_history,
        )
        from code_puppy.messaging import get_message_bus
        from code_puppy.messaging.messages import AgentResponseMessage

        loop = asyncio.get_running_loop()
        bus = get_message_bus()
        previous_bus_loop = getattr(bus, "_event_loop", None)
        bus._event_loop = loop  # Browser responses must complete futures in this loop.

        with self._lock:
            self._current_worker_loop = loop
            run["status"] = "running"
            run["started_at"] = _now()

        try:
            if model_name:
                from code_puppy.config import set_model_name

                set_model_name(model_name)
            if agent_name:
                set_current_agent(agent_name)

            agent = get_current_agent()
            run["agent_name"] = getattr(agent, "name", agent_name)
            run["model_name"] = agent.get_model_name()
            save_command_to_history(prompt)

            emit_event(
                "prompt_started",
                redact_event_data(
                    {
                        "run_id": run["run_id"],
                        "agent_name": run["agent_name"],
                        "model_name": run["model_name"],
                        "prompt_preview": redact(run["prompt_preview"], max_length=300),
                    }
                ),
            )

            def on_task_created(task: asyncio.Task[Any]) -> None:
                should_cancel = False
                with self._lock:
                    if (
                        self._current_run
                        and self._current_run.get("run_id") == run["run_id"]
                    ):
                        self._current_agent_task = task
                        should_cancel = bool(run.get("cancel_requested"))
                if should_cancel and not task.done():
                    task.cancel()

            result, _agent_task = await run_prompt_with_attachments(
                agent,
                prompt,
                spinner_console=None,
                use_spinner=False,
                on_task_created=on_task_created,
            )

            if result is None:
                self._mark_run_cancelled(run, "Agent task cancelled")
                return

            output = getattr(result, "output", None)
            if output is None:
                output = getattr(result, "data", None)
            if output is None:
                output = str(result)

            get_message_bus().emit(
                AgentResponseMessage(content=str(output), is_markdown=True)
            )
            if hasattr(result, "all_messages"):
                agent.set_message_history(list(result.all_messages()))
            auto_save_session_if_enabled()

            with self._lock:
                run["status"] = "completed"
                run["ended_at"] = _now()
                run["output_preview"] = _preview(output, 700)
                run["error"] = None

            emit_event(
                "prompt_completed",
                redact_event_data(
                    {
                        "run_id": run["run_id"],
                        "agent_name": run.get("agent_name"),
                        "model_name": run.get("model_name"),
                        "output_preview": redact(run["output_preview"], max_length=500),
                    }
                ),
            )
        except asyncio.CancelledError:
            self._mark_run_cancelled(run, "Agent task cancelled")
            raise
        finally:
            bus._event_loop = previous_bus_loop

    def _mark_run_cancelled(self, run: Dict[str, Any], reason: str) -> None:
        with self._lock:
            run["status"] = "cancelled"
            run["ended_at"] = _now()
            run["error"] = reason
        emit_event("prompt_cancelled", {"run_id": run["run_id"], "reason": reason})

    def _mark_run_failed(self, run: Dict[str, Any], exc: BaseException) -> None:
        import traceback as _tb

        error = str(exc) or exc.__class__.__name__
        with self._lock:
            run["status"] = "failed"
            run["ended_at"] = _now()
            run["error"] = redact(error, max_length=500)
        emit_event(
            "prompt_failed",
            redact_event_data(
                {
                    "run_id": run["run_id"],
                    "error": redact(error, max_length=500),
                    "traceback": sanitize_traceback(_tb.format_exc()),
                }
            ),
        )


_runtime_manager = RuntimeManager()


def get_runtime_manager() -> RuntimeManager:
    """Return the global dashboard runtime manager."""
    return _runtime_manager
