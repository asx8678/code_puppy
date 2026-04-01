"""Hierarchical run context for tracing agent, tool, and model interactions.

Each run context captures metadata about a single unit of work (e.g. an agent
run, a tool invocation, a model call).  Contexts form a tree via
``parent_run_id`` and are stored in a ``ContextVar`` so that async tasks
naturally inherit the correct parent.

Usage
-----
Inside a callback you can read the current context::

    from code_puppy.run_context import get_current_run_context

    ctx = get_current_run_context()
    if ctx:
        print(ctx.run_id, ctx.component_type)

The *on_agent_run_start* / *on_agent_run_end* helpers in ``callbacks.py``
automatically manage the lifecycle of root and child contexts.
"""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RunContext:
    """Immutable snapshot of a single unit of work.

    Attributes
    ----------
    run_id:
        Unique identifier for this run (UUID4).
    parent_run_id:
        The ``run_id`` of the parent context, or ``None`` for a root context.
    session_id:
        Optional session identifier forwarded from the agent run.
    component_type:
        Category of the component producing this context
        (e.g. ``"agent"``, ``"tool"``, ``"model"``, ``"plugin"``).
    component_name:
        Human-readable name of the specific component
        (e.g. ``"husky-019d4a"``, ``"read_file"``).
    tags:
        Arbitrary labels useful for filtering / grouping traces.
    metadata:
        Extensible dict for additional structured data.
    start_time:
        Monotonic timestamp (``time.monotonic()``) when the context was created.
    end_time:
        Monotonic timestamp when the context was closed, or ``None`` if still
        active.
    """

    run_id: str
    parent_run_id: str | None = None
    session_id: str | None = None
    component_type: str = "unknown"
    component_name: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=time.monotonic)
    end_time: float | None = None

    # -- helpers -------------------------------------------------------------

    @property
    def duration(self) -> float | None:
        """Elapsed time in seconds, or ``None`` if the context is still open."""
        if self.end_time is None:
            return None
        return self.end_time - self.start_time

    @property
    def is_root(self) -> bool:
        """``True`` when this context has no parent."""
        return self.parent_run_id is None

    def close(self) -> None:
        """Mark the context as finished *now*."""
        if self.end_time is None:
            self.end_time = time.monotonic()

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (useful for logging / JSON)."""
        return {
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "session_id": self.session_id,
            "component_type": self.component_type,
            "component_name": self.component_name,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
        }


# ---------------------------------------------------------------------------
# ContextVar integration
# ---------------------------------------------------------------------------

_current_run_context: ContextVar[RunContext | None] = ContextVar(
    "current_run_context", default=None
)


def get_current_run_context() -> RunContext | None:
    """Return the active :class:`RunContext` for the current async context."""
    return _current_run_context.get()


def set_current_run_context(ctx: RunContext | None) -> None:
    """Set (or clear) the active :class:`RunContext` for the current async context."""
    _current_run_context.set(ctx)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_child_run_context(
    parent: RunContext,
    component_type: str,
    component_name: str,
    *,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> RunContext:
    """Create a new child :class:`RunContext` derived from *parent*.

    The child inherits ``session_id`` and ``run_id`` as ``parent_run_id``.
    Extra *tags* / *metadata* are merged with the parent's values (parent
    values come first; child values override on conflict).
    """
    merged_tags = list(parent.tags)
    if tags:
        merged_tags.extend(t for t in tags if t not in merged_tags)

    merged_meta = dict(parent.metadata)
    if metadata:
        merged_meta.update(metadata)

    return RunContext(
        run_id=str(uuid.uuid4()),
        parent_run_id=parent.run_id,
        session_id=parent.session_id,
        component_type=component_type,
        component_name=component_name,
        tags=merged_tags,
        metadata=merged_meta,
        start_time=time.monotonic(),
    )


def create_root_run_context(
    component_type: str,
    component_name: str,
    *,
    session_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> RunContext:
    """Create a new root :class:`RunContext` (no parent).

    Convenience wrapper for callers that know they are creating a top-level
    context.
    """
    return RunContext(
        run_id=str(uuid.uuid4()),
        parent_run_id=None,
        session_id=session_id,
        component_type=component_type,
        component_name=component_name,
        tags=list(tags or []),
        metadata=dict(metadata or {}),
        start_time=time.monotonic(),
    )
