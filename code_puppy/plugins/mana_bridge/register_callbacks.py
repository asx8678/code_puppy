"""Callback registration for the Mana bridge plugin.

Forwards agent lifecycle and streaming events over a TCP connection to
Mana LiveView.  The bridge is only activated when the environment variable
``CODE_PUPPY_BRIDGE`` is set to ``"1"`` (or the ``--bridge-mode`` CLI
flag is used, which sets the env var).

If Mana is not running the plugin logs a warning and disables itself
without affecting the rest of Code Puppy.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.plugins.mana_bridge.tcp_client import BridgeClient

logger = logging.getLogger(__name__)

# Module-level singleton — created once on startup
_client: BridgeClient | None = None


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
        # Send hello handshake
        try:
            from code_puppy import __version__

            client.send_event(
                "hello",
                {
                    "version": __version__,
                    "bridge_type": "code_puppy",
                },
            )
            # Send available models list
            model_data = _gather_model_list()
            client.send_event("model_list", model_data)
            logger.debug(
                "Bridge sent model_list: %d models", len(model_data.get("models", []))
            )
        except Exception as exc:
            logger.warning("Failed to send bridge hello: %s", exc)
    else:
        logger.warning(
            "Mana bridge could not connect to Mana at startup. "
            "Events will be buffered for reconnection."
        )


def _on_shutdown() -> None:
    """Close the Mana bridge connection on shutdown."""
    global _client

    if _client is not None:
        try:
            _client.send_event("goodbye", {"reason": "shutdown"})
        except Exception:
            pass
        _client.close()
        _client = None


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
