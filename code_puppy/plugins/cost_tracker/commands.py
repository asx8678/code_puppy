"""Slash command handlers for the cost tracker plugin.

Provides /cost command for viewing and managing cost tracking.
"""

from code_puppy.messaging import emit_info, emit_warning


# Alert state to prevent repeated alerts - per budget type
_alerted_75_daily = False
_alerted_75_session = False
_alerted_100_daily = False
_alerted_100_session = False


def get_alert_state() -> dict[str, bool]:
    """Get current alert state."""
    return {
        "_alerted_75_daily": _alerted_75_daily,
        "_alerted_75_session": _alerted_75_session,
        "_alerted_100_daily": _alerted_100_daily,
        "_alerted_100_session": _alerted_100_session,
    }


def set_alert_state(
    alerted_75_daily: bool | None = None,
    alerted_75_session: bool | None = None,
    alerted_100_daily: bool | None = None,
    alerted_100_session: bool | None = None,
) -> None:
    """Set alert state (used for testing and reset)."""
    global \
        _alerted_75_daily, \
        _alerted_75_session, \
        _alerted_100_daily, \
        _alerted_100_session

    if alerted_75_daily is not None:
        _alerted_75_daily = alerted_75_daily
    if alerted_75_session is not None:
        _alerted_75_session = alerted_75_session
    if alerted_100_daily is not None:
        _alerted_100_daily = alerted_100_daily
    if alerted_100_session is not None:
        _alerted_100_session = alerted_100_session


def reset_alert_state() -> None:
    """Reset all alert states to False."""
    global \
        _alerted_75_daily, \
        _alerted_75_session, \
        _alerted_100_daily, \
        _alerted_100_session
    _alerted_75_daily = False
    _alerted_75_session = False
    _alerted_100_daily = False
    _alerted_100_session = False


def check_budget_thresholds(cost: float, budget: float, budget_type: str) -> None:
    """Check and alert on budget thresholds.

    Args:
        cost: Current cost amount
        budget: Budget limit
        budget_type: Either "daily" or "session"
    """
    global \
        _alerted_75_daily, \
        _alerted_75_session, \
        _alerted_100_daily, \
        _alerted_100_session

    if budget <= 0:
        return

    percentage = (cost / budget) * 100

    # Alert at 75% (once) - only if between 75% and 100%
    if budget_type == "daily":
        if 75 <= percentage < 100 and not _alerted_75_daily:
            _alerted_75_daily = True
            remaining = budget - cost
            emit_warning(
                f"💰 Budget Alert: {budget_type} budget at {percentage:.1f}% "
                f"(${cost:.4f} / ${budget:.2f}). Remaining: ${remaining:.4f}"
            )

        # Hard stop at 100% (once)
        if percentage >= 100 and not _alerted_100_daily:
            _alerted_100_daily = True
            emit_warning(
                f"🚫 Budget Exceeded: {budget_type} budget depleted! "
                f"(${cost:.4f} / ${budget:.2f}). Further API calls will be blocked."
            )
    else:  # session
        if 75 <= percentage < 100 and not _alerted_75_session:
            _alerted_75_session = True
            remaining = budget - cost
            emit_warning(
                f"💰 Budget Alert: {budget_type} budget at {percentage:.1f}% "
                f"(${cost:.4f} / ${budget:.2f}). Remaining: ${remaining:.4f}"
            )

        # Hard stop at 100% (once)
        if percentage >= 100 and not _alerted_100_session:
            _alerted_100_session = True
            emit_warning(
                f"🚫 Budget Exceeded: {budget_type} budget depleted! "
                f"(${cost:.4f} / ${budget:.2f}). Further API calls will be blocked."
            )


def handle_cost_command(
    command: str,
    name: str,
    get_cost_state_fn,
    get_daily_budget_fn,
    get_session_budget_fn,
    reset_session_costs_fn,
) -> bool | None:
    """Handle /cost slash command.

    Args:
        command: Full command string
        name: Command name
        get_cost_state_fn: Function to get current cost state
        get_daily_budget_fn: Function to get daily budget
        get_session_budget_fn: Function to get session budget
        reset_session_costs_fn: Function to reset session costs

    Returns:
        True if handled, None if not our command
    """
    if name not in ("cost", "costs"):
        return None

    parts = command.strip().split()
    sub = parts[1] if len(parts) > 1 else "status"

    if sub == "status":
        _show_cost_status(
            get_cost_state_fn(), get_daily_budget_fn(), get_session_budget_fn()
        )
        return True

    if sub == "reset":
        reset_session_costs_fn()
        return True

    if sub == "help":
        emit_info("Usage: /cost [status|reset|help]")
        emit_info("  status - Show current cost breakdown")
        emit_info("  reset  - Reset session costs (daily costs persist)")
        emit_info("  help   - Show this help message")
        return True

    # Default to status
    _show_cost_status(
        get_cost_state_fn(), get_daily_budget_fn(), get_session_budget_fn()
    )
    return True


def _show_cost_status(cost_state, daily_budget, session_budget) -> None:
    """Display current cost status."""
    emit_info("💰 Cost Tracker Status")
    emit_info("═" * 50)

    # Budget info
    if daily_budget:
        pct = (cost_state.daily_cost_usd / daily_budget) * 100
        emit_info(
            f"Daily Budget:  ${cost_state.daily_cost_usd:.4f} / ${daily_budget:.2f} ({pct:.1f}%)"
        )
    else:
        emit_info(f"Daily Cost:    ${cost_state.daily_cost_usd:.4f} (no budget set)")

    if session_budget:
        pct = (cost_state.session_cost_usd / session_budget) * 100
        emit_info(
            f"Session Budget: ${cost_state.session_cost_usd:.4f} / ${session_budget:.2f} ({pct:.1f}%)"
        )
    else:
        emit_info(f"Session Cost:   ${cost_state.session_cost_usd:.4f} (no budget set)")

    # Per-model breakdown
    if cost_state.model_costs:
        emit_info("\nPer-Model Breakdown:")
        emit_info("-" * 50)
        for model_name, cost in sorted(
            cost_state.model_costs.items(),
            key=lambda x: x[1].cost_usd,
            reverse=True,
        ):
            emit_info(
                f"  {model_name:20s} ${cost.cost_usd:.4f} "
                f"({cost.input_tokens:,} in / {cost.output_tokens:,} out)"
            )

    emit_info("═" * 50)


def cost_help() -> list[tuple[str, str]]:
    """Return help entries for cost commands."""
    return [
        ("cost", "View cost tracking status and budget information"),
        ("cost reset", "Reset session costs (daily costs persist)"),
    ]
