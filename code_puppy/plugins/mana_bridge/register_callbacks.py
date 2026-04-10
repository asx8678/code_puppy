"""Callback registration for the Mana bridge plugin.

Forwards agent lifecycle and streaming events over a TCP connection to
Mana LiveView.  The bridge is only activated when the environment variable
``CODE_PUPPY_BRIDGE`` is set to ``"1"`` (or the ``--bridge-mode`` CLI
flag is used, which sets the env var).

If Mana is not running the plugin logs a warning and disables itself
without affecting the rest of Code Puppy.
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
import time
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

logger = logging.getLogger(__name__)

# Module-level singleton — created once on startup
_client: BridgeClient | None = None

# Thread-safe queue for prompts received from Mana (for REPL pickup)
_pending_prompts: queue.Queue[str] = queue.Queue(maxsize=100)

# Background executor thread that runs prompts through the agent
_executor_thread: threading.Thread | None = None
_current_prompt_task: asyncio.Task | None = None
_executor_lock: asyncio.Lock | None = None  # Prevent concurrent agent runs from bridge

# Shutdown flag for the bridge executor loop
_bridge_shutdown = False


# ------------------------------------------------------------------
# Activation check
# ------------------------------------------------------------------


def _is_enabled() -> bool:
    """Return whether the Mana bridge is enabled via environment variable."""
    return os.environ.get("CODE_PUPPY_BRIDGE", "") == "1"


# ------------------------------------------------------------------
# Startup / shutdown
# ------------------------------------------------------------------


def _on_startup() -> None:
    """Connect to Mana on startup (if bridge mode is enabled)."""
    global _client

    if not _is_enabled():
        logger.debug("Mana bridge disabled (CODE_PUPPY_BRIDGE not set)")
        return

    client = BridgeClient()
    _client = client

    if client.connect():
        # Register request handlers from Mana (before sending events)
        client.register_handler("prompt", _handle_prompt_request)
        client.register_handler("switch_agent", _handle_switch_agent_request)
        client.register_handler("switch_model", _handle_switch_model_request)
        client.register_handler("cancel", _handle_cancel_request)
        client.register_handler("load_session", _handle_load_session_request)
        client.register_handler("save_session", _handle_save_session_request)

        # Send hello handshake
        try:
            from code_puppy import __version__

            # Get current agent and model info for hello handshake
            agent_name = "code-puppy"
            model_name = "unknown"
            try:
                from code_puppy.agents.agent_manager import get_current_agent_name
                from code_puppy.config import get_value

                agent_name = get_current_agent_name()
                model_name = get_value("model") or "unknown"
            except Exception:
                pass

            client.send_event(
                "hello",
                {
                    "version": __version__,
                    "bridge_type": "code_puppy",
                    "agent_name": agent_name,
                    "model_name": model_name,
                },
            )
            # Send available models list
            model_data = _gather_model_list()
            client.send_event("model_list", model_data)
            logger.debug(
                "Bridge sent model_list: %d models", len(model_data.get("models", []))
            )
            # Send round-robin status if active
            rr_status = _gather_round_robin_status()
            if rr_status:
                client.send_event("model_rotation_status", rr_status)
                logger.debug("Bridge sent model_rotation_status")
        except Exception as exc:
            logger.warning("Failed to send bridge hello: %s", exc)

        # Send agent list so Mana can render the agent panel
        try:
            _send_agent_list(client)
        except Exception as exc:
            logger.warning("Failed to send agent_list event: %s", exc)

        # Send available sessions
        try:
            _send_session_list(client)
        except Exception as exc:
            logger.warning("Failed to send session_list event: %s", exc)

        # Start the prompt executor thread
        _start_prompt_executor()
    else:
        logger.warning(
            "Mana bridge could not connect to Mana at startup. "
            "Events will be buffered for reconnection."
        )


# ------------------------------------------------------------------
# Agent list event
# ------------------------------------------------------------------


def _send_agent_list(client: BridgeClient | None = None) -> None:
    """Send the list of available agents to Mana.

    Collects agent metadata from the agent registry and sends an
    ``agent_list`` event so the Mana UI can render the agent panel.
    """
    if client is None:
        client = _client
    if client is None:
        return

    agents: list[dict[str, str]] = []

    try:
        from code_puppy.agents import (
            get_available_agents,
            get_agent_descriptions,
        )

        available = get_available_agents()  # {name: display_name}
        descriptions = get_agent_descriptions()  # {name: description}

        for name, display_name in available.items():
            agents.append(
                {
                    "name": name,
                    "display_name": display_name,
                    "description": descriptions.get(name, ""),
                }
            )
    except Exception as exc:
        logger.debug("Could not load agents from registry: %s", exc)
        # Fall back to a minimal hardcoded list so the panel still works
        agents = [
            {
                "name": "code-puppy",
                "display_name": "Code Puppy \U0001f436",
                "description": "General-purpose coding assistant",
            },
        ]

    client.send_event("agent_list", {"agents": agents})
    logger.debug("Bridge sent agent_list with %d agents", len(agents))


# ------------------------------------------------------------------
# Incoming request handlers (Mana → Python)
# ------------------------------------------------------------------


def _handle_prompt_request(msg: dict) -> None:
    """Handle incoming prompt request from Mana.

    Stores the prompt in a thread-safe queue so the REPL can pick it up.
    Also sends an acknowledgment back to Mana.
    """
    data = msg.get("data", {})
    text = data.get("text", "")
    if not text:
        return

    try:
        _pending_prompts.put_nowait(text)
        logger.info("Bridge received prompt from Mana: %s", text[:80])
    except queue.Full:
        logger.warning("Bridge prompt queue full — dropping prompt from Mana")

    # Acknowledge receipt — reuse request id for correlation
    request_id = msg.get("id")
    if _client is not None and request_id:
        _client.send_response("prompt_ack", {"status": "queued"}, request_id=request_id)
    elif _client is not None:
        _client.send_event("prompt_ack", {"status": "queued"})


def _handle_switch_agent_request(msg: dict) -> None:
    """Handle switch_agent request from Mana."""
    data = msg.get("data", {})
    agent_name = data.get("agent_name", "")
    if not agent_name:
        return

    try:
        from code_puppy.agents import set_current_agent

        success = set_current_agent(agent_name)
        if success and _client:
            _client.send_event("agent_switched", {"agent_name": agent_name})
            logger.info("Bridge switched agent to: %s", agent_name)
        elif _client:
            _client.send_event(
                "error", {"message": f"Failed to switch to agent: {agent_name}"}
            )
    except Exception as exc:
        logger.error("Failed to switch agent via bridge: %s", exc)


def _handle_switch_model_request(msg: dict) -> None:
    """Handle switch_model request from Mana."""
    data = msg.get("data", {})
    model_name = data.get("model_name", "")
    if not model_name:
        return

    # Reuse the existing /model command handler
    result = _on_switch_model("model", model_name)
    if result and _client:
        logger.info("Bridge switched model to: %s (result: %s)", model_name, result)


def _handle_cancel_request(msg: dict) -> None:
    """Handle cancel request from Mana.

    Cancels the currently running prompt task if one is active.
    """
    global _current_prompt_task
    task = _current_prompt_task
    if task is not None and not task.done():
        task.cancel()
        logger.info("Bridge cancelled current prompt task")
        if _client is not None:
            _client.send_event("cancel_ack", {"status": "cancelled"})
    else:
        logger.debug("Bridge cancel requested but no active task")
        if _client is not None:
            _client.send_event("cancel_ack", {"status": "no_active_task"})


def _send_session_list(client: BridgeClient | None = None) -> None:
    """Send the list of available sessions to Mana."""
    if client is None:
        client = _client
    if client is None:
        return

    sessions: list[dict[str, Any]] = []
    try:
        from pathlib import Path
        from code_puppy.session_storage import list_sessions
        from code_puppy.config import AUTOSAVE_DIR
        import json

        base_dir = Path(AUTOSAVE_DIR)
        session_names = list_sessions(base_dir)

        for name in session_names:
            try:
                # Read metadata from .meta.json file
                meta_path = base_dir / f"{name}_meta.json"
                if meta_path.exists():
                    with meta_path.open("r", encoding="utf-8") as f:
                        meta = json.load(f)
                    sessions.append(
                        {
                            "id": name,
                            "agent_name": "unknown",  # Not stored in current metadata format
                            "model_name": "unknown",  # Not stored in current metadata format
                            "message_count": meta.get("message_count", 0),
                            "updated_at": meta.get("timestamp"),
                        }
                    )
                else:
                    # No metadata file - basic entry
                    sessions.append(
                        {
                            "id": name,
                            "agent_name": "unknown",
                            "model_name": "unknown",
                            "message_count": 0,
                            "updated_at": None,
                        }
                    )
            except Exception as exc:
                logger.debug("Failed to read metadata for session %s: %s", name, exc)
                sessions.append(
                    {
                        "id": name,
                        "agent_name": "unknown",
                        "model_name": "unknown",
                        "message_count": 0,
                        "updated_at": None,
                    }
                )
    except Exception as exc:
        logger.warning("Failed to list sessions: %s", exc)

    client.send_event("session_list", {"sessions": sessions})
    logger.debug("Bridge sent session_list with %d sessions", len(sessions))


def _handle_load_session_request(msg: dict) -> None:
    """Handle load_session request from Mana."""
    data = msg.get("data", {})
    session_id = data.get("session_id", "")
    if not session_id:
        return

    try:
        from pathlib import Path
        from code_puppy.session_storage import load_session_with_hashes
        from code_puppy.config import AUTOSAVE_DIR
        from code_puppy.agents.agent_manager import get_current_agent

        base_dir = Path(AUTOSAVE_DIR)
        messages, compacted_hashes = load_session_with_hashes(session_id, base_dir)

        if messages:
            # Apply to current agent
            agent = get_current_agent()
            if agent:
                agent.set_message_history(messages)
                if compacted_hashes:
                    agent.restore_compacted_hashes(compacted_hashes)

            if _client:
                _client.send_event(
                    "session_loaded",
                    {
                        "session_id": session_id,
                        "success": True,
                        "message_count": len(messages),
                    },
                )
            logger.info("Bridge loaded session: %s", session_id)
        else:
            if _client:
                _client.send_event(
                    "session_loaded",
                    {
                        "session_id": session_id,
                        "success": False,
                        "error": "Session empty or not found",
                    },
                )
    except FileNotFoundError:
        logger.warning("Session not found: %s", session_id)
        if _client:
            _client.send_event(
                "session_loaded",
                {
                    "session_id": session_id,
                    "success": False,
                    "error": "Session not found",
                },
            )
    except Exception as exc:
        logger.error("Failed to load session via bridge: %s", exc)
        if _client:
            _client.send_event(
                "session_loaded",
                {
                    "session_id": session_id,
                    "success": False,
                    "error": str(exc)[:200],
                },
            )


def _handle_save_session_request(msg: dict) -> None:
    """Handle save_session request from Mana."""
    try:
        from pathlib import Path
        from datetime import datetime, timezone
        from code_puppy.agents.agent_manager import get_current_agent
        from code_puppy.session_storage import save_session
        from code_puppy.config import AUTOSAVE_DIR

        agent = get_current_agent()
        if agent is None:
            if _client:
                _client.send_event(
                    "session_saved", {"success": False, "error": "No agent"}
                )
            return

        # Get current message history from agent
        history = (
            agent.get_message_history() if hasattr(agent, "get_message_history") else []
        )
        if not history:
            # Try to get from agent's message history attribute
            history = getattr(agent, "_message_history", []) or getattr(
                agent, "_history", []
            )

        # Generate session name with timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        session_id = f"mana_{timestamp}"

        base_dir = Path(AUTOSAVE_DIR)

        # Get token estimator from agent
        def token_estimator(msg):
            if hasattr(agent, "estimate_tokens_for_message"):
                return agent.estimate_tokens_for_message(msg)
            return 0

        # Save the session
        save_session(
            history=history,
            session_name=session_id,
            base_dir=base_dir,
            timestamp=datetime.now(timezone.utc).isoformat(),
            token_estimator=token_estimator,
            auto_saved=False,
        )

        if _client:
            _client.send_event(
                "session_saved",
                {
                    "success": True,
                    "session_id": session_id,
                },
            )
            # Refresh session list
            _send_session_list()
        logger.info("Bridge saved session: %s", session_id)
    except Exception as exc:
        logger.error("Failed to save session via bridge: %s", exc)
        if _client:
            _client.send_event(
                "session_saved", {"success": False, "error": str(exc)[:200]}
            )


def get_pending_bridge_prompts() -> list[str]:
    """Return all pending prompts received from Mana (non-blocking).

    The REPL can poll this to pick up prompts that were injected
    via the Mana bridge.  Returns an empty list if no prompts are
    pending.
    """
    prompts: list[str] = []
    while not _pending_prompts.empty():
        try:
            prompts.append(_pending_prompts.get_nowait())
        except queue.Empty:
            break
    return prompts


def _on_shutdown() -> None:
    """Close the Mana bridge connection on shutdown."""
    global _client, _executor_thread, _bridge_shutdown

    _bridge_shutdown = True

    # Join executor thread with timeout to allow in-flight prompts to complete
    thread = _executor_thread
    _executor_thread = None
    if thread is not None and thread.is_alive():
        thread.join(timeout=3.0)

    if _client is not None:
        try:
            _client.send_event("goodbye", {"reason": "shutdown"})
        except Exception:
            pass
        _client.close()
        _client = None


# ------------------------------------------------------------------
# Background prompt executor
# ------------------------------------------------------------------


def _start_prompt_executor() -> None:
    """Start the background thread that executes prompts from the Mana bridge."""
    global _executor_thread
    _executor_thread = threading.Thread(
        target=_prompt_executor_run,
        name="mana-bridge-executor",
        daemon=True,
    )
    _executor_thread.start()
    logger.info("Bridge prompt executor started")


def _prompt_executor_run() -> None:
    """Background thread: create event loop, poll prompts, run agent."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_prompt_executor_async())
    except Exception as exc:
        logger.error("Bridge prompt executor crashed: %s", exc)
    finally:
        loop.close()


async def _prompt_executor_async() -> None:
    """Async loop that polls the pending prompts queue and executes them."""
    global _executor_lock
    _executor_lock = asyncio.Lock()
    while not _bridge_shutdown:
        try:
            text = _pending_prompts.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.3)
            continue

        logger.info("Bridge executing prompt: %s", text[:80])
        await _execute_bridge_prompt(text)


async def _execute_bridge_prompt(text: str) -> None:
    """Execute a single prompt received from the Mana bridge.

    Gets the current agent, runs it with the prompt, and sends
    a prompt_complete event back to Mana. Agent lifecycle callbacks
    (stream_event, agent_run_start/end, tool calls) fire automatically
    and are forwarded to Mana by the existing bridge plumbing.
    """
    global _executor_lock
    # Lazily initialize lock if not already created (e.g., in tests)
    if _executor_lock is None:
        _executor_lock = asyncio.Lock()
    async with _executor_lock:
        try:
            from code_puppy.agents.agent_manager import get_current_agent

            agent = get_current_agent()
            if agent is None:
                logger.error("No agent available for bridge prompt")
                if _client:
                    _client.send_event(
                        "prompt_complete",
                        {
                            "success": False,
                            "error": "No agent available",
                        },
                    )
                return

            # Run the agent — callbacks fire during this call
            global _current_prompt_task
            task = asyncio.ensure_future(agent.run_with_mcp(text))
            _current_prompt_task = task
            try:
                result = await task
            finally:
                _current_prompt_task = None

            if result is not None:
                response_text = result.output or ""

                # Update agent message history
                if hasattr(result, "all_messages"):
                    agent.set_message_history(list(result.all_messages()))

                # Send completion to Mana
                if _client:
                    _client.send_event(
                        "prompt_complete",
                        {
                            "success": True,
                            "response_preview": response_text[:500],
                        },
                    )
                logger.info("Bridge prompt completed successfully")
            else:
                if _client:
                    _client.send_event(
                        "prompt_complete",
                        {
                            "success": True,
                            "response_preview": "",
                        },
                    )

        except Exception as exc:
            logger.error("Bridge prompt execution failed: %s", exc)
            if _client:
                _client.send_event(
                    "prompt_complete",
                    {
                        "success": False,
                        "error": str(exc)[:200],
                    },
                )


# ------------------------------------------------------------------
# Stream events  →  bridge messages
# ------------------------------------------------------------------


async def _on_stream_event(
    event_type: str,
    event_data: Any,
    agent_session_id: str | None = None,
) -> None:
    """Forward streaming events to Mana.

    Maps Code Puppy event types to bridge event names:
    - token        → token
    - part_start   → part_start
    - part_delta   → part_delta
    - part_end     → part_end
    - everything else → stream_event (passthrough)
    """
    if _client is None:
        return

    try:
        bridge_name = event_type  # default: pass through as-is

        payload: dict[str, Any] = {
            "event_type": event_type,
            "agent_session_id": agent_session_id,
        }

        # Include the raw event data if it's simple enough
        if isinstance(event_data, (str, int, float, bool)) or event_data is None:
            payload["data"] = event_data
        elif isinstance(event_data, dict):
            # Keep only safe scalar values to stay within msgpack bounds
            safe: dict[str, Any] = {}
            for k, v in event_data.items():
                if isinstance(v, (str, int, float, bool, type(None))):
                    s = str(v) if isinstance(v, str) else v
                    if isinstance(s, str) and len(s) > 500:
                        s = s[:497] + "..."
                    safe[str(k)] = s
            payload["data"] = safe

        _client.send_event(bridge_name, payload)
        logger.debug("Bridge forwarded stream_event: %s", bridge_name)
    except Exception as exc:
        logger.error("Failed to forward stream_event to Mana: %s", exc)


# ------------------------------------------------------------------
# Agent lifecycle  →  bridge messages
# ------------------------------------------------------------------


async def _on_agent_run_start(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
) -> None:
    """Forward agent run start to Mana."""
    if _client is None:
        return
    try:
        _client.send_event(
            "agent_run_start",
            {
                "agent_name": agent_name,
                "model_name": model_name,
                "session_id": session_id,
                "timestamp": time.time(),
            },
        )
        logger.debug("Bridge forwarded agent_run_start: %s", agent_name)
    except Exception as exc:
        logger.error("Failed to forward agent_run_start: %s", exc)


async def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Forward agent run end to Mana."""
    if _client is None:
        return
    try:
        payload: dict[str, Any] = {
            "agent_name": agent_name,
            "model_name": model_name,
            "session_id": session_id,
            "success": success,
            "timestamp": time.time(),
        }
        if error is not None:
            payload["error"] = str(error)
        if response_text is not None:
            preview = response_text[:200] + ("..." if len(response_text) > 200 else "")
            payload["response_preview"] = preview
        if metadata is not None:
            payload["metadata"] = metadata

        _client.send_event("agent_run_end", payload)
        logger.debug("Bridge forwarded agent_run_end: %s", agent_name)
    except Exception as exc:
        logger.error("Failed to forward agent_run_end: %s", exc)


# ------------------------------------------------------------------
# Tool calls  →  bridge messages
# ------------------------------------------------------------------


async def _on_pre_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    context: Any = None,
) -> None:
    """Forward tool call start to Mana."""
    if _client is None:
        return
    try:
        _client.send_event(
            "tool_call_start",
            {
                "tool_name": tool_name,
                "tool_args": _sanitize_args(tool_args),
                "start_time": time.time(),
            },
        )
        logger.debug("Bridge forwarded tool_call_start: %s", tool_name)
    except Exception as exc:
        logger.error("Failed to forward pre_tool_call: %s", exc)


async def _on_post_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> None:
    """Forward tool call end to Mana."""
    if _client is None:
        return
    try:
        _client.send_event(
            "tool_call_end",
            {
                "tool_name": tool_name,
                "tool_args": _sanitize_args(tool_args),
                "duration_ms": duration_ms,
                "success": _is_successful(result),
                "result_summary": _summarize_result(result),
            },
        )
        logger.debug(
            "Bridge forwarded tool_call_end: %s (%.2fms)",
            tool_name,
            duration_ms,
        )
    except Exception as exc:
        logger.error("Failed to forward post_tool_call: %s", exc)


# ------------------------------------------------------------------
# Model list helper
# ------------------------------------------------------------------


def _gather_model_list() -> dict[str, Any]:
    """Build a model_list payload from ModelFactory.load_config().

    Returns a dict with ``models`` (list of model info dicts) and
    ``current_model`` (the currently configured model name).
    """
    models: list[dict[str, Any]] = []
    current_model: str | None = None

    try:
        from code_puppy.model_factory import ModelFactory

        models_config = ModelFactory.load_config()
        for name, cfg in models_config.items():
            model_type = cfg.get("type", "unknown")
            models.append({"name": name, "type": model_type})
    except Exception as exc:
        logger.warning("Failed to load model list for bridge: %s", exc)

    # Sort by name for stable ordering
    models.sort(key=lambda m: m["name"])

    # Get current model from config
    try:
        from code_puppy.config import get_value

        current_model = get_value("model")
    except Exception as exc:
        logger.warning("Failed to get current model for bridge: %s", exc)

    return {"models": models, "current_model": current_model}


# ------------------------------------------------------------------
# Round-robin status helper
# ------------------------------------------------------------------


def _gather_round_robin_status() -> dict[str, Any] | None:
    """Build a model_rotation_status payload if round-robin is active.

    Returns None if round-robin is not configured.
    """
    try:
        from code_puppy.config import get_value

        model_name = get_value("model") or ""

        # Check if current model is a round-robin model
        from code_puppy.model_factory import ModelFactory

        models_config = ModelFactory.load_config()
        model_cfg = models_config.get(model_name, {})

        if model_cfg.get("type") != "round_robin":
            return None

        candidates = model_cfg.get("candidates", [])
        rotate_every = model_cfg.get("rotate_every", 1)

        # Try to get current index from the running model instance
        current_index = 0
        requests_until_rotation = rotate_every
        try:
            from code_puppy.agents.agent_manager import get_current_agent

            agent = get_current_agent()
            if agent and hasattr(agent, "_pydantic_agent"):
                model = agent._pydantic_agent.model
                if hasattr(model, "_current_index"):
                    current_index = model._current_index
                if hasattr(model, "_request_count"):
                    requests_until_rotation = rotate_every - (
                        model._request_count % rotate_every
                    )
        except Exception:
            pass

        return {
            "active": True,
            "model_name": model_name,
            "candidates": candidates,
            "rotate_every": rotate_every,
            "current_index": current_index,
            "requests_until_rotation": requests_until_rotation,
        }
    except Exception as exc:
        logger.debug("Failed to gather round-robin status: %s", exc)
        return None


# ------------------------------------------------------------------
# Custom command: switch_model
# ------------------------------------------------------------------


def _on_switch_model(command: str, name: str) -> bool | str | None:
    """Handle /model <name> slash command — switch active model.

    This is registered as a ``custom_command`` callback so that the
    CLI and the Mana bridge can both trigger model switches.
    """
    if command != "model":
        return None  # not our command

    if not name:
        return "Usage: /model <model_name>"

    try:
        from code_puppy.model_switching import set_model_and_reload_agent
        from code_puppy.model_factory import ModelFactory

        models_config = ModelFactory.load_config()
        if name not in models_config:
            available = ", ".join(sorted(models_config.keys())[:10])
            return f"Unknown model '{name}'. Available: {available}"

        set_model_and_reload_agent(name)

        # Notify Mana of the model change
        if _client is not None:
            _client.send_event("model_changed", {"model_name": name})
            # Update round-robin status after model change
            rr_status = _gather_round_robin_status()
            if rr_status and _client is not None:
                _client.send_event("model_rotation_status", rr_status)

        return f"Switched to model: {name}"
    except Exception as exc:
        logger.error("Failed to switch model: %s", exc)
        return f"Failed to switch model: {exc}"


def _on_switch_model_help() -> list[tuple[str, str]]:
    """Provide help text for the /model command."""
    return [("/model <name>", "Switch to a different AI model")]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Trim tool arguments to keep payloads small and msgpack-safe."""
    if not isinstance(args, dict):
        return {}
    safe: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str):
            safe[k] = v if len(v) <= 500 else v[:497] + "..."
        elif isinstance(v, (int, float, bool, type(None))):
            safe[k] = v
        elif isinstance(v, (list, dict)):
            safe[k] = f"<{type(v).__name__}[{len(v)}]>"
        else:
            safe[k] = f"<{type(v).__name__}>"
    return safe


def _is_successful(result: Any) -> bool:
    """Heuristic: does *result* look like a success?"""
    if result is None:
        return True
    if isinstance(result, dict):
        if result.get("error"):
            return False
        if result.get("success") is False:
            return False
        return True
    if isinstance(result, bool):
        return result
    return True


def _summarize_result(result: Any) -> str:
    """One-line summary of a tool result."""
    if result is None:
        return "<no result>"
    if isinstance(result, str):
        return result if len(result) <= 200 else result[:197] + "..."
    if isinstance(result, dict):
        if "error" in result:
            return f"Error: {str(result['error'])[:100]}"
        if "message" in result:
            return str(result["message"])[:200]
        return f"<dict with {len(result)} keys>"
    if isinstance(result, (list, tuple)):
        return f"<{type(result).__name__}[{len(result)}]>"
    return str(result)[:200]


# ------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------


def register() -> None:
    """Register all Mana bridge callbacks."""
    register_callback("startup", _on_startup)
    register_callback("shutdown", _on_shutdown)
    register_callback("stream_event", _on_stream_event)
    register_callback("agent_run_start", _on_agent_run_start)
    register_callback("agent_run_end", _on_agent_run_end)
    register_callback("pre_tool_call", _on_pre_tool_call)
    register_callback("post_tool_call", _on_post_tool_call)
    register_callback("custom_command", _on_switch_model)
    register_callback("custom_command_help", _on_switch_model_help)
    logger.debug("Mana bridge callbacks registered")


# Auto-register callbacks when this module is imported
register()
