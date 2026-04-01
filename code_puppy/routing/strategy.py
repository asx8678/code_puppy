"""Core routing abstractions: protocols, contexts, and decisions."""


import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class RoutingContext:
    """Input context for a routing decision."""

    model_name: str
    config: dict[str, Any]


@dataclass
class RoutingDecision:
    """Output of a routing strategy."""

    model: Any  # The pydantic-ai Model instance
    model_name: str
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class RoutingStrategy(Protocol):
    """A strategy that may return a routing decision or None to decline."""

    @property
    def name(self) -> str: ...

    def route(self, context: RoutingContext) -> RoutingDecision | None: ...


@runtime_checkable
class TerminalStrategy(Protocol):
    """A strategy guaranteed to return a decision (never None)."""

    @property
    def name(self) -> str: ...

    def route(self, context: RoutingContext) -> RoutingDecision: ...
