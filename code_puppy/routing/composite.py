"""CompositeStrategy — chain of responsibility for model routing.

Tries strategies in order. First non-None decision wins.
The last strategy must be terminal (guaranteed to return a decision).
"""

import logging
import time
from typing import Sequence

from code_puppy.routing.strategy import (
    RoutingContext,
    RoutingDecision,
    RoutingStrategy,
    TerminalStrategy,
)

logger = logging.getLogger(__name__)


class CompositeStrategy:
    """Tries a list of strategies in order; last one must be terminal."""

    def __init__(
        self,
        strategies: Sequence[RoutingStrategy | TerminalStrategy],
        name: str = "composite",
    ) -> None:
        if not strategies:
            raise ValueError("At least one strategy is required")
        self._strategies = list(strategies)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def route(self, context: RoutingContext) -> RoutingDecision:
        start = time.monotonic()

        # Try non-terminal strategies (all but last)
        for strategy in self._strategies[:-1]:
            try:
                decision = strategy.route(context)
                if decision is not None:
                    return self._finalize(decision, strategy.name, start)
            except Exception:
                logger.warning(
                    "Strategy '%s' failed, continuing to next",
                    strategy.name,
                    exc_info=True,
                )

        # Terminal strategy (last) — must succeed
        terminal = self._strategies[-1]
        try:
            decision = terminal.route(context)
            if decision is None:
                raise RuntimeError(f"Terminal strategy '{terminal.name}' returned None")
            return self._finalize(decision, terminal.name, start)
        except Exception:
            logger.error(
                "Terminal strategy '%s' failed — routing cannot proceed",
                terminal.name,
                exc_info=True,
            )
            raise

    def _finalize(
        self,
        decision: RoutingDecision,
        source: str,
        start: float,
    ) -> RoutingDecision:
        elapsed_ms = (time.monotonic() - start) * 1000
        decision.metadata["source"] = f"{self._name}/{source}"
        decision.metadata["latency_ms"] = f"{elapsed_ms:.1f}"
        return decision
