"""Tests for CompositeStrategy routing chain."""

import pytest
from code_puppy.routing.composite import CompositeStrategy
from code_puppy.routing.strategy import RoutingContext, RoutingDecision


class AlwaysDecline:
    """Strategy that always returns None (declines)."""
    @property
    def name(self) -> str:
        return "always_decline"

    def route(self, context: RoutingContext) -> RoutingDecision | None:
        return None


class AlwaysRoute:
    """Strategy that always returns a decision."""
    def __init__(self, label: str = "always_route"):
        self._label = label

    @property
    def name(self) -> str:
        return self._label

    def route(self, context: RoutingContext) -> RoutingDecision:
        return RoutingDecision(
            model="mock_model",
            model_name=context.model_name,
            metadata={"reasoning": self._label},
        )


class FailingStrategy:
    """Strategy that raises an exception."""
    @property
    def name(self) -> str:
        return "failing"

    def route(self, context: RoutingContext) -> RoutingDecision | None:
        raise RuntimeError("Strategy failed!")


class ConditionalRoute:
    """Strategy that matches only a specific model name."""
    def __init__(self, target: str):
        self._target = target

    @property
    def name(self) -> str:
        return f"conditional_{self._target}"

    def route(self, context: RoutingContext) -> RoutingDecision | None:
        if context.model_name == self._target:
            return RoutingDecision(
                model="conditional_model",
                model_name=self._target,
                metadata={"reasoning": f"matched {self._target}"},
            )
        return None


@pytest.fixture
def ctx():
    return RoutingContext(model_name="test-model", config={"test-model": {"type": "openai"}})


def test_terminal_strategy_always_returns(ctx):
    chain = CompositeStrategy([AlwaysRoute("terminal")], name="test")
    decision = chain.route(ctx)
    assert decision.model_name == "test-model"
    assert "test/terminal" in decision.metadata["source"]


def test_first_match_wins(ctx):
    chain = CompositeStrategy(
        [AlwaysRoute("first"), AlwaysRoute("second"), AlwaysRoute("terminal")],
        name="test",
    )
    decision = chain.route(ctx)
    assert "first" in decision.metadata["source"]


def test_decline_falls_through(ctx):
    chain = CompositeStrategy(
        [AlwaysDecline(), AlwaysRoute("terminal")],
        name="test",
    )
    decision = chain.route(ctx)
    assert "terminal" in decision.metadata["source"]


def test_failing_strategy_caught_gracefully(ctx):
    chain = CompositeStrategy(
        [FailingStrategy(), AlwaysRoute("terminal")],
        name="test",
    )
    decision = chain.route(ctx)
    assert "terminal" in decision.metadata["source"]


def test_conditional_routing(ctx):
    chain = CompositeStrategy(
        [ConditionalRoute("gpt-4"), ConditionalRoute("test-model"), AlwaysRoute("terminal")],
        name="test",
    )
    decision = chain.route(ctx)
    assert decision.model_name == "test-model"
    assert "conditional_test-model" in decision.metadata["source"]


def test_metadata_includes_latency(ctx):
    chain = CompositeStrategy([AlwaysRoute("terminal")], name="test")
    decision = chain.route(ctx)
    assert "latency_ms" in decision.metadata


def test_empty_strategies_raises():
    with pytest.raises(ValueError, match="At least one"):
        CompositeStrategy([], name="empty")


def test_terminal_returning_none_raises(ctx):
    """If the terminal strategy returns None, should raise RuntimeError."""

    class BadTerminal:
        @property
        def name(self) -> str:
            return "bad_terminal"

        def route(self, context: RoutingContext) -> RoutingDecision | None:
            return None

    chain = CompositeStrategy([BadTerminal()], name="test")
    with pytest.raises(RuntimeError, match="returned None"):
        chain.route(ctx)
