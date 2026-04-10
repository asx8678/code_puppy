"""Cost Estimator plugin — token counting and cost estimation.

Registers:
- ``/cost`` command to show session cost summary
- ``/estimate <text>`` command to estimate tokens/cost for text
- ``pre_tool_call`` hook for dry-run interception (when enabled)
- ``shutdown`` hook for session summary

Inspired by Agentless ``--mock`` flag and token counting pattern.
"""

from __future__ import annotations

import logging
import os

from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)

# Dry-run mode: set PUP_DRY_RUN=1 to intercept LLM calls
_DRY_RUN = os.environ.get("PUP_DRY_RUN", "").strip() in ("1", "true", "yes")


def _handle_cost_command(command: str, name: str) -> str | None:
    """Handle /cost and /estimate slash commands."""
    if name == "cost":
        from .estimator import get_session_summary

        summary = get_session_summary()
        if not summary["models"]:
            return "No token usage tracked in this session yet."

        lines = ["📊 **Session Cost Summary**\n"]
        for m in summary["models"]:
            lines.append(
                f"  - **{m['model']}**: {m['total_tokens']:,} tokens "
                f"(~${m['estimated_cost_usd']:.4f})"
            )
        lines.append(
            f"\n  **Total estimated cost**: ${summary['total_estimated_cost_usd']:.4f} USD"
        )
        return "\n".join(lines)

    if name == "estimate":
        parts = command.strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return "Usage: /estimate <text or prompt to estimate>"

        from .estimator import estimate_cost

        text = parts[1].strip()
        est = estimate_cost(text)
        return (
            f"📊 **Token Estimate**\n"
            f"  - Input tokens: ~{est.input_tokens:,} ({est.method})\n"
            f"  - Expected output: ~{est.output_tokens:,} tokens\n"
            f"  - Estimated cost: ~${est.estimated_cost_usd:.4f} USD\n"
            f"  - Model: {est.model}"
        )

    return None


def _cost_help() -> list[tuple[str, str]]:
    """Provide help entries for cost commands."""
    return [
        ("/cost", "Show accumulated token usage and estimated costs for this session"),
        ("/estimate <text>", "Estimate token count and cost for given text"),
    ]


def _on_pre_tool_call(
    tool_name: str,
    tool_args: dict,
    context=None,
) -> None:
    """Track token usage on tool calls.

    Always tracks token estimates for /cost reporting.
    In dry-run mode (PUP_DRY_RUN=1), additionally logs estimates.
    """
    if tool_name in ("invoke_agent",):
        prompt = tool_args.get("prompt", "") or tool_args.get("message", "")
        if prompt:
            from .estimator import count_tokens, track_session_tokens

            model = tool_args.get("model", "gpt-4o")
            tokens = count_tokens(str(prompt), model=model)
            track_session_tokens(model, tokens)

            if _DRY_RUN:
                logger.info(
                    "cost_estimator: %s → ~%d tokens (%s)",
                    tool_name, tokens, model,
                )

    return None


def _on_shutdown() -> None:
    """Print session cost summary on shutdown if anything was tracked."""
    from .estimator import get_session_summary

    summary = get_session_summary()
    if summary["models"]:
        total = summary["total_estimated_cost_usd"]
        logger.info("Session cost estimate: ~$%.4f USD", total)


# Register callbacks at module scope
register_callback("custom_command", _handle_cost_command)
register_callback("custom_command_help", _cost_help)
register_callback("pre_tool_call", _on_pre_tool_call)
register_callback("shutdown", _on_shutdown)
