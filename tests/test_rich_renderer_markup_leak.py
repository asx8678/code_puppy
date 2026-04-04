"""Test for Rich markup leak in subagent invocation renderer.

Issue: code_puppy-1l6n
Bug: `[dim](7976 more chars)[/dim]` renders as literal text in terminal

The bug was that Rich markup tags were embedded in a string that gets passed
to Markdown() renderer, which doesn't process Rich markup. The fix is to use
plain text for the truncation indicator.
"""

from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from code_puppy.messaging.bus import MessageBus
from code_puppy.messaging.messages import SubAgentInvocationMessage
from code_puppy.messaging.rich_renderer import RichConsoleRenderer


@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def console():
    return Console(file=StringIO(), force_terminal=False, width=120)


@pytest.fixture
def renderer(bus, console):
    return RichConsoleRenderer(bus, console=console)


def output(console):
    return console.file.getvalue()


@patch("code_puppy.messaging.rich_renderer.is_subagent", return_value=False)
def test_subagent_invocation_truncation_no_rich_markup(mock_sub, renderer, console):
    """Test that truncation indicator doesn't contain Rich markup tags.

    When a long prompt is truncated, the "(N more chars)" indicator
    should be plain text, not Rich markup like [dim](N more chars)[/dim],
    because the string gets passed to Markdown() which doesn't process
    Rich markup and would render it as literal text.
    """
    # Create a very long prompt (>100 chars) to trigger truncation
    long_prompt = "This is a very long prompt. " * 10  # ~300 chars

    msg = SubAgentInvocationMessage(
        agent_name="test-agent",
        session_id="test-session",
        prompt=long_prompt,
        is_new_session=True,
        message_count=0,
    )

    renderer._render_subagent_invocation(msg)
    out = output(console)

    # The output should contain the truncation indicator with plain text
    # e.g., "(200 more chars)" but NOT "[dim](200 more chars)[/dim]"
    assert "more chars)" in out, "Truncation indicator should appear in output"

    # Rich markup tags should NOT appear in the output (they would render as literal text)
    assert "[dim]" not in out, "Rich markup [dim] tag should not appear in output - it renders as literal text"
    assert "[/dim]" not in out, "Rich markup [/dim] tag should not appear in output - it renders as literal text"


@patch("code_puppy.messaging.rich_renderer.is_subagent", return_value=False)
def test_subagent_invocation_truncation_format(mock_sub, renderer, console):
    """Test that truncation indicator shows correct character count."""
    # Create a prompt with known length (~150 chars)
    prompt = "x" * 150

    msg = SubAgentInvocationMessage(
        agent_name="test-agent",
        session_id="test-session",
        prompt=prompt,
        is_new_session=True,
        message_count=0,
    )

    renderer._render_subagent_invocation(msg)
    out = output(console)

    # Should show "(50 more chars)" since first 100 are displayed
    # The exact number depends on console width calculation, but there should
    # be a number inside parentheses followed by "more chars"
    import re
    pattern = r"\((\d+) more chars\)"
    match = re.search(pattern, out)
    assert match is not None, f"Should find '(N more chars)' pattern in output. Got: {out[:500]}"

    remaining_chars = int(match.group(1))
    # With width 120, max_prompt_len = min(100, 120-20) = min(100, 100) = 100
    # So remaining = 150 - 100 = 50
    assert remaining_chars == 50, f"Expected 50 remaining chars, got {remaining_chars}"


@patch("code_puppy.messaging.rich_renderer.is_subagent", return_value=False)
def test_subagent_invocation_short_prompt_no_truncation(mock_sub, renderer, console):
    """Test that short prompts are not truncated."""
    short_prompt = "Short prompt"  # < 100 chars

    msg = SubAgentInvocationMessage(
        agent_name="test-agent",
        session_id="test-session",
        prompt=short_prompt,
        is_new_session=True,
        message_count=0,
    )

    renderer._render_subagent_invocation(msg)
    out = output(console)

    # Should NOT contain truncation indicator
    assert "more chars)" not in out, "Short prompt should not be truncated"
    # Should contain the full prompt
    assert short_prompt in out, "Full short prompt should appear in output"
