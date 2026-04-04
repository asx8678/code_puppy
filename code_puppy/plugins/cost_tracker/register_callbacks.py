"""Cost tracker plugin callbacks for Code Puppy CLI.

Tracks API costs per model and enforces configurable daily/per-session budgets.
Alerts at 75% threshold and hard-stops at 100% budget consumption.
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_puppy.callbacks import register_callback
from code_puppy.config import DATA_DIR, get_value
from code_puppy.messaging import emit_error, emit_info, emit_warning

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default pricing per 1K tokens (in USD) - industry standard rates
# These are approximate rates; users can override via config
DEFAULT_PRICING = {
    # OpenAI models
    "gpt-4o": {"input": 0.0025, "output": 0.010},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.010, "output": 0.030},
    "gpt-4": {"input": 0.030, "output": 0.060},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    # Anthropic models
    "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-5-haiku": {"input": 0.0008, "output": 0.004},
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    "claude-code": {"input": 0.003, "output": 0.015},
    # Google/Gemini models
    "gemini-2": {"input": 0.0007, "output": 0.0021},
    "gemini-1.5-pro": {"input": 0.0035, "output": 0.0105},
    "gemini-1.5-flash": {"input": 0.00035, "output": 0.00105},
    "gemini-1.0-pro": {"input": 0.0005, "output": 0.0015},
    # Antigravity models (uses Gemini rates)
    "antigravity": {"input": 0.0007, "output": 0.0021},
}

# Cost storage file (persistent daily tracking)
COST_STORAGE_FILE = Path(DATA_DIR) / "cost_tracker.json"

# Lock for thread-safe cost updates
_cost_lock = threading.Lock()

# Alert state to prevent repeated alerts
_alerted_75_percent = False
_alerted_100_percent = False

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
# Pricing
# ---------------------------------------------------------------------------


def _get_pricing_for_model(model_name: str) -> dict[str, float]:
    """Get pricing for a model, with fallback to defaults."""
    # Try exact match
    if model_name in DEFAULT_PRICING:
        return DEFAULT_PRICING[model_name]

    # Try prefix match (e.g., "gpt-4o-2024-08-06" matches "gpt-4o")
    for prefix, pricing in DEFAULT_PRICING.items():
        if model_name.startswith(prefix):
            return pricing

    # Default fallback pricing
    logger.debug(f"No pricing found for model: {model_name}, using defaults")
    return {"input": 0.001, "output": 0.003}  # Conservative defaults


def _calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for a model call."""
    pricing = _get_pricing_for_model(model_name)
    input_cost = (input_tokens / 1000) * pricing["input"]
    output_cost = (output_tokens / 1000) * pricing["output"]
    return round(input_cost + output_cost, 6)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _load_daily_cost() -> tuple[float, str]:
    """Load daily cost from persistent storage."""
    try:
        if COST_STORAGE_FILE.exists():
            with open(COST_STORAGE_FILE, "r") as f:
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
            json.dump({
                "daily_cost_usd": _cost_state.daily_cost_usd,
                "day": _cost_state.current_day,
                "last_updated": time.time(),
            }, f)
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
    global _alerted_75_percent, _alerted_100_percent

    with _cost_lock:
        # Calculate cost for this call
        call_cost = _calculate_cost(model_name, input_tokens, output_tokens)

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

        # Determine effective budget (use daily or session, whichever is more restrictive)
        if daily_budget is not None and session_budget is not None:
            # Track both separately - alert if either threshold crossed
            _check_budget_thresholds(
                _cost_state.daily_cost_usd,
                daily_budget,
                "daily",
            )
            _check_budget_thresholds(
                _cost_state.session_cost_usd,
                session_budget,
                "session",
            )
        elif daily_budget is not None:
            _check_budget_thresholds(
                _cost_state.daily_cost_usd,
                daily_budget,
                "daily",
            )
        elif session_budget is not None:
            _check_budget_thresholds(
                _cost_state.session_cost_usd,
                session_budget,
                "session",
            )

        # Save to persistent storage
        _save_daily_cost()

        return call_cost, _cost_state.session_cost_usd


def _check_budget_thresholds(cost: float, budget: float, budget_type: str) -> None:
    """Check and alert on budget thresholds."""
    global _alerted_75_percent, _alerted_100_percent

    if budget <= 0:
        return

    percentage = (cost / budget) * 100

    # Alert at 75% (once) - only if between 75% and 100%
    if 75 <= percentage < 100 and not _alerted_75_percent:
        _alerted_75_percent = True
        remaining = budget - cost
        emit_warning(
            f"💰 Budget Alert: {budget_type} budget at {percentage:.1f}% "
            f"(${cost:.4f} / ${budget:.2f}). Remaining: ${remaining:.4f}"
        )

    # Hard stop at 100% (once)
    if percentage >= 100 and not _alerted_100_percent:
        _alerted_100_percent = True
        emit_error(
            f"🚫 Budget Exceeded: {budget_type} budget depleted! "
            f"(${cost:.4f} / ${budget:.2f}). Further API calls will be blocked."
        )


# ---------------------------------------------------------------------------
# Token Extraction
# ---------------------------------------------------------------------------


def _extract_tokens_from_result(result: Any) -> dict[str, int] | None:
    """Extract token counts from an API result.

    Handles various response formats from different providers.
    """
    try:
        # Handle dict results (common for API responses)
        if isinstance(result, dict):
            # Anthropic format first (input_tokens/output_tokens)
            if "usage" in result and isinstance(result["usage"], dict):
                usage = result["usage"]
                # Check for Anthropic-style field names first
                if "input_tokens" in usage or "output_tokens" in usage:
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    # Only return if at least one token count is present
                    if input_tokens > 0 or output_tokens > 0 or "input_tokens" in usage or "output_tokens" in usage:
                        return {
                            "input": input_tokens,
                            "output": output_tokens,
                        }
                # Then check for OpenAI-style field names
                if "prompt_tokens" in usage or "completion_tokens" in usage:
                    return {
                        "input": usage.get("prompt_tokens", 0),
                        "output": usage.get("completion_tokens", 0),
                    }

            # Direct fields - check for Anthropic style first
            if "input_tokens" in result or "output_tokens" in result:
                return {
                    "input": result.get("input_tokens", 0),
                    "output": result.get("output_tokens", 0),
                }
            # Then OpenAI style
            if "prompt_tokens" in result or "completion_tokens" in result:
                return {
                    "input": result.get("prompt_tokens", 0),
                    "output": result.get("completion_tokens", 0),
                }

            # If we have a usage dict but couldn't extract tokens, return None
            if "usage" in result:
                return None

        # Handle objects with attributes
        if hasattr(result, "usage") and result.usage:
            usage = result.usage
            if isinstance(usage, dict):
                # Check for Anthropic-style field names first
                if "input_tokens" in usage or "output_tokens" in usage:
                    return {
                        "input": usage.get("input_tokens", 0),
                        "output": usage.get("output_tokens", 0),
                    }
                # Then OpenAI-style field names
                return {
                    "input": usage.get("prompt_tokens", 0),
                    "output": usage.get("completion_tokens", 0),
                }
            # Handle object-style usage - check for Anthropic style first
            if hasattr(usage, "input_tokens") or hasattr(usage, "output_tokens"):
                return {
                    "input": getattr(usage, "input_tokens", 0),
                    "output": getattr(usage, "output_tokens", 0),
                }
            # Then OpenAI style
            return {
                "input": getattr(usage, "prompt_tokens", 0),
                "output": getattr(usage, "completion_tokens", 0),
            }

    except (AttributeError, TypeError, KeyError) as e:
        logger.debug(f"Failed to extract tokens from result: {e}")

    return None


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
        tokens = _extract_tokens_from_result(result)
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
        output_tokens = metadata.get("output_tokens", metadata.get("completion_tokens", 0))

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
    if tool_name in ("create_file", "read_file", "replace_in_file", "delete_file"):
        return None  # Don't block file operations

    daily_budget = _get_daily_budget()
    session_budget = _get_session_budget()

    # Check if budget exceeded
    daily_exceeded = daily_budget is not None and _cost_state.daily_cost_usd >= daily_budget
    session_exceeded = (
        session_budget is not None and _cost_state.session_cost_usd >= session_budget
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


# ---------------------------------------------------------------------------
# Slash Command
# ---------------------------------------------------------------------------


def _handle_cost_command(command: str, name: str) -> bool | None:
    """Handle /cost slash command."""
    if name not in ("cost", "costs"):
        return None

    parts = command.strip().split()
    sub = parts[1] if len(parts) > 1 else "status"

    if sub == "status":
        _show_cost_status()
        return True

    if sub == "reset":
        _reset_session_costs()
        return True

    if sub == "help":
        emit_info("Usage: /cost [status|reset|help]")
        emit_info("  status - Show current cost breakdown")
        emit_info("  reset  - Reset session costs (daily costs persist)")
        emit_info("  help   - Show this help message")
        return True

    # Default to status
    _show_cost_status()
    return True


def _show_cost_status() -> None:
    """Display current cost status."""
    emit_info("💰 Cost Tracker Status")
    emit_info("═" * 50)

    # Budget info
    daily_budget = _get_daily_budget()
    session_budget = _get_session_budget()

    if daily_budget:
        pct = (_cost_state.daily_cost_usd / daily_budget) * 100
        emit_info(f"Daily Budget:  ${_cost_state.daily_cost_usd:.4f} / ${daily_budget:.2f} ({pct:.1f}%)")
    else:
        emit_info(f"Daily Cost:    ${_cost_state.daily_cost_usd:.4f} (no budget set)")

    if session_budget:
        pct = (_cost_state.session_cost_usd / session_budget) * 100
        emit_info(f"Session Budget: ${_cost_state.session_cost_usd:.4f} / ${session_budget:.2f} ({pct:.1f}%)")
    else:
        emit_info(f"Session Cost:   ${_cost_state.session_cost_usd:.4f} (no budget set)")

    # Per-model breakdown
    if _cost_state.model_costs:
        emit_info("\nPer-Model Breakdown:")
        emit_info("-" * 50)
        for model_name, cost in sorted(
            _cost_state.model_costs.items(),
            key=lambda x: x[1].cost_usd,
            reverse=True,
        ):
            emit_info(
                f"  {model_name:20s} ${cost.cost_usd:.4f} "
                f"({cost.input_tokens:,} in / {cost.output_tokens:,} out)"
            )

    emit_info("═" * 50)


def _reset_session_costs() -> None:
    """Reset session costs (daily costs persist)."""
    global _alerted_75_percent, _alerted_100_percent

    with _cost_lock:
        old_session_cost = _cost_state.session_cost_usd
        _cost_state.session_cost_usd = 0.0
        _cost_state.model_costs.clear()
        _alerted_75_percent = False
        _alerted_100_percent = False

    emit_info(f"✅ Session costs reset (was ${old_session_cost:.4f})")
    emit_info(f"   Daily costs still tracked: ${_cost_state.daily_cost_usd:.4f}")


def _cost_help() -> list[tuple[str, str]]:
    """Return help entries for cost commands."""
    return [
        ("cost", "View cost tracking status and budget information"),
        ("cost reset", "Reset session costs (daily costs persist)"),
    ]


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


def reset_alert_state() -> None:
    """Reset alert state for testing."""
    global _alerted_75_percent, _alerted_100_percent
    _alerted_75_percent = False
    _alerted_100_percent = False


def reset_all_costs_for_testing() -> None:
    """Reset all costs for testing purposes."""
    global _cost_state, _alerted_75_percent, _alerted_100_percent
    with _cost_lock:
        _cost_state = CostState()
        _alerted_75_percent = False
        _alerted_100_percent = False


# ---------------------------------------------------------------------------
# Register Callbacks
# ---------------------------------------------------------------------------

register_callback("post_tool_call", _on_post_tool_call)
register_callback("agent_run_end", _on_agent_run_end)
register_callback("pre_tool_call", _on_pre_tool_call)
register_callback("custom_command", _handle_cost_command)
register_callback("custom_command_help", _cost_help)
