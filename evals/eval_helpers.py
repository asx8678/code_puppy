"""Core eval infrastructure for testing agent behavior.

This module provides the building blocks for writing evals:
- EvalPolicy: classifies how reliable a test is expected to be
- ToolCall: captures a single tool call made by the agent
- EvalResult: captures the full result of running an eval prompt
- log_eval: persists eval results to evals/logs/ for debugging
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class EvalPolicy(Enum):
    """Describes how deterministic an eval is expected to be.

    ALWAYS_PASSES — fully deterministic (e.g. mock-backed), should never flake.
    USUALLY_PASSES — depends on LLM output and may occasionally fail.
    """

    ALWAYS_PASSES = "always_passes"
    USUALLY_PASSES = "usually_passes"


@dataclass
class ToolCall:
    """A single tool call captured from an agent run."""

    name: str
    args: dict
    result: str | None = None


@dataclass
class EvalResult:
    """The full result of running an eval prompt against an agent."""

    response_text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    duration_seconds: float = 0.0
    model_name: str = ""


EVAL_LOGS_DIR = Path("evals/logs")


def log_eval(name: str, result: EvalResult) -> None:
    """Persist eval results to evals/logs/<name>.json for later inspection.

    Args:
        name: Human-readable name for this eval (used as the filename).
        result: The EvalResult to persist.
    """
    EVAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    sanitized = name.replace(" ", "_").replace("/", "_").lower()
    log_file = EVAL_LOGS_DIR / f"{sanitized}.json"

    log_data = {
        "name": name,
        "timestamp": datetime.now().isoformat(),
        "model": result.model_name,
        "duration_seconds": result.duration_seconds,
        # Truncate very long responses so logs stay readable
        "response_text": result.response_text[:2000],
        "tool_calls": [
            {"name": tc.name, "args": tc.args, "result": tc.result}
            for tc in result.tool_calls
        ],
    }

    log_file.write_text(json.dumps(log_data, indent=2))
