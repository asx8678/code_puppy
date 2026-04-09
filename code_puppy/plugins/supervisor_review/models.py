"""Supervisor review plugin data models (bd code_puppy-79p).

Dataclasses used by the iterative multi-agent review orchestrator. Ported from
orion-multistep-analysis supervisor/orchestrator.py with improvements:
- Structured result type instead of whole-loop crash on errors
- Per-iteration snapshots for replay / debugging
- Agent-agnostic (Orion hardcoded 3 specific agents; we allow any list)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "FeedbackEntry",
    "IterationResult",
    "ReviewLoopConfig",
    "SatisfactionResult",
    "SupervisorReviewResult",
]


@dataclass(slots=True)
class FeedbackEntry:
    """Supervisor feedback captured at the end of an iteration."""

    iteration: int
    supervisor_output: str
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class SatisfactionResult:
    """Result returned by a satisfaction checker."""

    satisfied: bool
    confidence: float  # 0.0 to 1.0
    reason: str = ""

    def __post_init__(self) -> None:
        # Clamp confidence to [0, 1] defensively
        if self.confidence < 0.0:
            self.confidence = 0.0
        elif self.confidence > 1.0:
            self.confidence = 1.0


@dataclass(slots=True)
class IterationResult:
    """Snapshot of a single iteration of the review loop."""

    iteration: int
    worker_outputs: dict[str, str] = field(default_factory=dict)
    supervisor_output: str = ""
    satisfaction: SatisfactionResult | None = None
    error: str | None = None
    duration_seconds: float = 0.0

    @property
    def satisfied(self) -> bool:
        return self.satisfaction is not None and self.satisfaction.satisfied


@dataclass(slots=True)
class ReviewLoopConfig:
    """Configuration for a supervisor-review loop run."""

    worker_agents: list[str]
    supervisor_agent: str
    task_prompt: str
    max_iterations: int = 3
    satisfaction_mode: str = "structured"  # "structured" | "keyword" | "llm_judge"
    session_prefix: str | None = None

    def __post_init__(self) -> None:
        if not self.worker_agents:
            raise ValueError("worker_agents must not be empty")
        if not self.supervisor_agent:
            raise ValueError("supervisor_agent must not be empty")
        if self.max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1, got {self.max_iterations}")
        if self.satisfaction_mode not in ("structured", "keyword", "llm_judge"):
            raise ValueError(
                f"satisfaction_mode must be one of 'structured', 'keyword', 'llm_judge'; "
                f"got {self.satisfaction_mode!r}"
            )


@dataclass(slots=True)
class SupervisorReviewResult:
    """Final result of a supervisor-review loop run."""

    success: bool
    iterations_run: int
    max_iterations: int
    iterations: list[IterationResult] = field(default_factory=list)
    final_worker_outputs: dict[str, str] = field(default_factory=dict)
    final_supervisor_output: str = ""
    feedback_history: list[FeedbackEntry] = field(default_factory=list)
    error: str | None = None
    artifacts_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "success": self.success,
            "iterations_run": self.iterations_run,
            "max_iterations": self.max_iterations,
            "final_worker_outputs": dict(self.final_worker_outputs),
            "final_supervisor_output": self.final_supervisor_output,
            "feedback_history": [
                {
                    "iteration": fe.iteration,
                    "supervisor_output": fe.supervisor_output,
                    "timestamp": fe.timestamp,
                }
                for fe in self.feedback_history
            ],
            "iterations": [
                {
                    "iteration": it.iteration,
                    "worker_outputs": dict(it.worker_outputs),
                    "supervisor_output": it.supervisor_output,
                    "satisfied": it.satisfied,
                    "error": it.error,
                    "duration_seconds": it.duration_seconds,
                }
                for it in self.iterations
            ],
            "error": self.error,
            "artifacts_dir": self.artifacts_dir,
        }
