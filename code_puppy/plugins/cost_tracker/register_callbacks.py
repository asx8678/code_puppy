"""Cost tracker plugin callbacks for Code Puppy CLI.

Tracks API costs per model and enforces configurable daily/per-session budgets.
Alerts at 75% threshold and hard-stops at 100% budget consumption.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.config import DATA_DIR, get_value
from code_puppy.messaging import emit_error, emit_info

from .commands import (
    check_budget_thresholds,
    cost_help,
    handle_cost_command,
    reset_alert_state,
)
from .extraction import extract_tokens_from_result
from .pricing import calculate_cost

logger = logging.getLogger(__name__)

# Cost storage file (persistent daily tracking)
COST_STORAGE_FILE = Path(DATA_DIR) / "cost_tracker.json"

# Lock for thread-safe cost updates
_cost_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class ModelCost:
    """Cost tracking for a single model."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class CostState:
    """Complete cost tracking state."""

    # Per-model costs
    model_costs: dict[str, ModelCost] = field(default_factory=dict)
    # Session total
    session_cost_usd: float = 0.0
    # Daily total (loaded from/saved to persistent storage)
    daily_cost_usd: float = 0.0
    # Last updated timestamp (for daily reset)
    last_updated: float = field(default_factory=time.time)
    # Current day string (YYYY-MM-DD format)
    current_day: str = field(default_factory=lambda: time.strftime("%Y-%m-%d"))


# Global cost state
_cost_state = CostState()

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _load_daily_cost() -> tuple[float, str]:
    """Load daily cost from persistent storage."""
    try:
        if COST_STORAGE_FILE.exists():
            with open(COST_STORAGE_FILE) as f:
                data = json.load(f)
                saved_day = data.get("day", "")
                current_day = time.strftime("%Y-%m-%d")

                # Reset if it's a new day
                if saved_day != current_day:
                    return 0.0, current_day

                return data.get("daily_cost_usd", 0.0), saved_day
    except (json.JSONDecodeError, OSError, KeyError) as e:
        logger.debug(f"Failed to load daily cost: {e}")

    return 0.0, time.strftime("%Y-%m-%d")


def _save_daily_cost() -> None:
    """Save daily cost to persistent storage."""
    try:
        COST_STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(COST_STORAGE_FILE, "w") as f:
            json.dump(
                {
                    "daily_cost_usd": _cost_state.daily_cost_usd,
                    "day": _cost_state.current_day,
                    "last_updated": time.time(),
                },
                f,
            )
    except OSError as e:
        logger.warning(f"Failed to save daily cost: {e}")


# Load initial daily cost on module load
try:
    daily_cost, current_day = _load_daily_cost()
    _cost_state.daily_cost_usd = daily_cost
    _cost_state.current_day = current_day
except Exception:
    pass  # Fail silently on load


# ---------------------------------------------------------------------------
# Budget Configuration
# ---------------------------------------------------------------------------


def _get_daily_budget() -> float | None:
    """Get daily budget limit in USD from config."""
    value = get_value("budget_daily_limit_usd")
    if value:
        try:
            return float(value)
        except (ValueError, TypeError):
            pass
    return None


def _get_session_budget() -> float | None:
    """Get session budget limit in USD from config."""
    value = get_value("budget_session_limit_usd")
    if value:
        try:
            return float(value)
        except (ValueError, TypeError):
            pass
    return None


# ---------------------------------------------------------------------------
# Cost Tracking
# ---------------------------------------------------------------------------


def _update_cost(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
) -> tuple[float, float]:
    """Update cost tracking for a model call.

    Returns:
        Tuple of (call_cost_usd, total_session_cost_usd)
    """
    with _cost_lock:
        # Calculate cost for this call
        call_cost = calculate_cost(model_name, input_tokens, output_tokens)

        # Update per-model costs
        if model_name not in _cost_state.model_costs:
            _cost_state.model_costs[model_name] = ModelCost()

        model_cost = _cost_state.model_costs[model_name]
        model_cost.input_tokens += input_tokens
        model_cost.output_tokens += output_tokens
        model_cost.cost_usd += call_cost

        # Update totals
        _cost_state.session_cost_usd += call_cost
        _cost_state.daily_cost_usd += call_cost
        _cost_state.last_updated = time.time()

        # Check budget thresholds
        daily_budget = _get_daily_budget()
        session_budget = _get_session_budget()

        # Track both separately - alert if either threshold crossed
        if daily_budget is not None:
            check_budget_thresholds(_cost_state.daily_cost_usd, daily_budget, "daily")
        if session_budget is not None:
            check_budget_thresholds(
                _cost_state.session_cost_usd, session_budget, "session"
            )

        # Save to persistent storage
        _save_daily_cost()

        return call_cost, _cost_state.session_cost_usd


# ---------------------------------------------------------------------------
# Callback Handlers
# ---------------------------------------------------------------------------


def _on_post_tool_call(
    tool_name: str,
    tool_args: dict,
    result: Any,
    duration_ms: float,
    context: Any = None,
) -> None:
    """Track costs after API calls complete.

    Hooks into post_tool_call to extract token counts from API responses
    and calculate costs.
    """
    # Only track API-related tool calls
    if tool_name not in ("invoke_agent", "agent_run_start", "agent_run_end"):
        # Try to extract model info from context or args
        model_name = "unknown"

        # Extract from context if available
        if context and isinstance(context, dict):
            model_name = context.get("model_name", "unknown")
        elif hasattr(context, "model_name"):
            model_name = context.model_name

        # Extract from tool args if available
        if "model_name" in tool_args:
            model_name = tool_args["model_name"]
        elif "model" in tool_args:
            model_name = tool_args["model"]

        # Try to extract tokens from result
        tokens = extract_tokens_from_result(result)
        if tokens:
            call_cost, session_total = _update_cost(
                model_name,
                tokens["input"],
                tokens["output"],
            )
            logger.debug(
                f"Cost tracker: {model_name} call cost ${call_cost:.6f}, "
                f"session total ${session_total:.6f}"
            )


def _on_agent_run_end(
    agent_name: str,
    model_name: str,
    session_id: str | None = None,
    success: bool = True,
    error: Exception | None = None,
    response_text: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Track costs from agent run metadata.

    This catches token counts that are passed in the metadata from the agent.
    """
    if metadata and isinstance(metadata, dict):
        # Extract token counts from metadata
        input_tokens = metadata.get("input_tokens", metadata.get("prompt_tokens", 0))
        output_tokens = metadata.get(
            "output_tokens", metadata.get("completion_tokens", 0)
        )

        if input_tokens > 0 or output_tokens > 0:
            call_cost, session_total = _update_cost(
                model_name,
                input_tokens,
                output_tokens,
            )
            logger.debug(
                f"Cost tracker: {agent_name}/{model_name} run cost ${call_cost:.6f}, "
                f"session total ${session_total:.6f}"
            )


def _on_pre_tool_call(
    tool_name: str,
    tool_args: dict,
    context: Any = None,
) -> dict | None:
    """Block API calls when budget is exceeded.

    Hooks into pre_tool_call to enforce hard stop at 100% budget.
    """
    # Only block API-related calls
    if tool_name in (
        "create_file",
        "read_file",
        "replace_in_file",
        "delete_file",
    ):
        return None  # Don't block file operations

    with _cost_lock:
        daily_budget = _get_daily_budget()
        session_budget = _get_session_budget()

        # Check if budget exceeded
        daily_exceeded = (
            daily_budget is not None and _cost_state.daily_cost_usd >= daily_budget
        )
        session_exceeded = (
            session_budget is not None
            and _cost_state.session_cost_usd >= session_budget
        )

        if daily_exceeded or session_exceeded:
            budget_type = "daily" if daily_exceeded else "session"
            budget = daily_budget if daily_exceeded else session_budget
            emit_error(
                f"🚫 Budget Hard Stop: {budget_type} budget exceeded (${budget:.2f}). "
                f"Blocking API call: {tool_name}"
            )
            return {"blocked": True, "reason": f"{budget_type}_budget_exceeded"}

    return None


def _handle_cost_command_wrapper(command: str, name: str) -> bool | None:
    """Wrapper for cost command handler."""
    return handle_cost_command(
        command,
        name,
        lambda: _cost_state,
        _get_daily_budget,
        _get_session_budget,
        _reset_session_costs,
    )


def _reset_session_costs() -> None:
    """Reset session costs (daily costs persist)."""
    with _cost_lock:
        old_session_cost = _cost_state.session_cost_usd
        _cost_state.session_cost_usd = 0.0
        _cost_state.model_costs.clear()
        reset_alert_state()

    emit_info(f"✅ Session costs reset (was ${old_session_cost:.4f})")
    emit_info(f"   Daily costs still tracked: ${_cost_state.daily_cost_usd:.4f}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_cost_summary() -> dict[str, Any]:
    """Get current cost summary for external use."""
    with _cost_lock:
        return {
            "daily_cost_usd": _cost_state.daily_cost_usd,
            "session_cost_usd": _cost_state.session_cost_usd,
            "model_costs": {
                name: {
                    "input_tokens": cost.input_tokens,
                    "output_tokens": cost.output_tokens,
                    "cost_usd": cost.cost_usd,
                }
                for name, cost in _cost_state.model_costs.items()
            },
            "daily_budget": _get_daily_budget(),
            "session_budget": _get_session_budget(),
        }


def add_cost_for_testing(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Add cost for testing purposes.

    Returns the cost that was added.
    """
    call_cost, _ = _update_cost(model_name, input_tokens, output_tokens)
    return call_cost


def reset_all_costs_for_testing() -> None:
    """Reset all costs for testing purposes (thread-safe)."""
    global _cost_state
    with _cost_lock:
        _cost_state = CostState()
        reset_alert_state()


# ---------------------------------------------------------------------------
# Register Callbacks
# ---------------------------------------------------------------------------

register_callback("post_tool_call", _on_post_tool_call)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("pre_tool_call", _on_pre_tool_call)
register_callback("custom_command", _handle_cost_command_wrapper)
register_callback("custom_command_help", cost_help)
