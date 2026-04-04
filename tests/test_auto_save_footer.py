"""Test auto-save footer functionality in RichConsoleRenderer."""

import io
from unittest.mock import Mock

import pytest
from rich.console import Console

from code_puppy.messaging import MessageBus, RichConsoleRenderer, TextMessage, MessageLevel


@pytest.fixture
def renderer():
    """Create a renderer with a mock console."""
    console = Console(file=io.StringIO(), force_terminal=True)
    bus = MessageBus()
    return RichConsoleRenderer(bus, console=console), console


def test_auto_save_message_intercepted(renderer):
    """Test that auto-save messages are intercepted and not displayed inline."""
    renderer_obj, console = renderer
    
    # Render an auto-save message
    msg = TextMessage(level=MessageLevel.INFO, text='🐾 Auto-saved session: 31 messages (22083 tokens)')
    renderer_obj._render_text(msg)
    
    # Check that session info was updated
    assert renderer_obj._session_info["message_count"] == 31
    assert renderer_obj._session_info["token_count"] == 22083
    assert renderer_obj._session_info["last_save_time"] is not None


def test_auto_save_footer_rendered(renderer):
    """Test that a footer is rendered after auto-save message."""
    renderer_obj, console = renderer
    
    # Render an auto-save message
    msg = TextMessage(level=MessageLevel.INFO, text='🐾 Auto-saved session: 31 messages (22083 tokens)')
    renderer_obj._render_text(msg)
    
    # Check that footer was rendered (strip ANSI codes for easier testing)
    output = console.file.getvalue()
    # Remove ANSI escape codes for testing
    import re
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    clean_output = ansi_escape.sub('', output)
    
    assert "Auto-saved session" in clean_output
    assert "31 messages" in clean_output or "31" in clean_output
    assert "22083 tokens" in clean_output or "22083" in clean_output


def test_normal_messages_not_intercepted(renderer):
    """Test that normal messages are not intercepted."""
    renderer_obj, console = renderer
    
    # Render a normal message
    msg = TextMessage(level=MessageLevel.INFO, text='Normal info message')
    renderer_obj._render_text(msg)
    
    # Check that message was rendered
    output = console.file.getvalue()
    assert "Normal info message" in output
    
    # Check that session info was NOT updated
    assert renderer_obj._session_info["message_count"] == 0
    assert renderer_obj._session_info["token_count"] == 0


def test_session_state_updated_on_multiple_saves(renderer):
    """Test that session state is updated correctly on multiple saves."""
    renderer_obj, console = renderer
    
    # First save
    msg1 = TextMessage(level=MessageLevel.INFO, text='🐾 Auto-saved session: 10 messages (5000 tokens)')
    renderer_obj._render_text(msg1)
    
    assert renderer_obj._session_info["message_count"] == 10
    assert renderer_obj._session_info["token_count"] == 5000
    
    # Second save
    msg2 = TextMessage(level=MessageLevel.INFO, text='🐾 Auto-saved session: 20 messages (10000 tokens)')
    renderer_obj._render_text(msg2)
    
    # State should be updated to latest values
    assert renderer_obj._session_info["message_count"] == 20
    assert renderer_obj._session_info["token_count"] == 10000


def test_footer_includes_time_stamp(renderer):
    """Test that footer includes a timestamp."""
    renderer_obj, console = renderer
    
    # Render an auto-save message
    msg = TextMessage(level=MessageLevel.INFO, text='🐾 Auto-saved session: 31 messages (22083 tokens)')
    renderer_obj._render_text(msg)
    
    # Check that footer includes time
    output = console.file.getvalue()
    # Time format is HH:MM:SS, so we should see a colon-separated pattern
    import re
    time_pattern = r'\d{2}:\d{2}:\d{2}'
    assert re.search(time_pattern, output) is not None


def test_footer_is_dimmed(renderer):
    """Test that footer is rendered with dim styling."""
    renderer_obj, console = renderer
    
    # Render an auto-save message
    msg = TextMessage(level=MessageLevel.INFO, text='🐾 Auto-saved session: 31 messages (22083 tokens)')
    renderer_obj._render_text(msg)
    
    # Check for ANSI dim code (ESC[2m)
    output = console.file.getvalue()
    assert '\x1b[2m' in output  # Dim ANSI code


def test_session_state_initialization():
    """Test that session state is initialized correctly."""
    console = Console(file=io.StringIO(), force_terminal=True)
    bus = MessageBus()
    renderer = RichConsoleRenderer(bus, console=console)
    
    assert renderer._session_info["message_count"] == 0
    assert renderer._session_info["token_count"] == 0
    assert renderer._session_info["last_save_time"] is None