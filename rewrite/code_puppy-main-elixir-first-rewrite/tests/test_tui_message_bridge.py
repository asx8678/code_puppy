"""Tests for the TUI message bridge (TUIMessageBridge and TUIConsole)."""

from unittest.mock import MagicMock


from code_puppy.tui.message_bridge import TUIConsole, TUIMessageBridge, _strip_ansi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockChatLog:
    """Minimal stand-in for Textual's RichLog widget."""

    def __init__(self):
        self.written: list = []

    def write(self, content, **kwargs):
        self.written.append(content)


class MockApp:
    """Mock CodePuppyApp for testing."""

    def __init__(self):
        self._chat = MockChatLog()
        self._call_from_thread_fn = None

    def query_one(self, selector, *args):
        return self._chat

    def call_from_thread(self, fn, *args):
        fn(*args)


# ---------------------------------------------------------------------------
# _strip_ansi
# ---------------------------------------------------------------------------


def test_strip_ansi_removes_codes():
    assert _strip_ansi("\x1b[32mhello\x1b[0m") == "hello"


def test_strip_ansi_leaves_plain_text():
    assert _strip_ansi("plain text") == "plain text"


def test_strip_ansi_empty_string():
    assert _strip_ansi("") == ""


# ---------------------------------------------------------------------------
# TUIMessageBridge
# ---------------------------------------------------------------------------


def test_bridge_creation():
    app = MockApp()
    bridge = TUIMessageBridge(app)
    assert bridge._running is False
    assert bridge._task is None


def test_bridge_stop_before_start_is_safe():
    app = MockApp()
    bridge = TUIMessageBridge(app)
    bridge.stop()  # Should not raise


def test_render_queue_message_info():
    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = UIMessage(type=MessageType.INFO, content="hello info")
    bridge._render_queue_message(msg)
    assert any("hello info" in str(m) for m in app._chat.written)


def test_render_queue_message_error():
    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = UIMessage(type=MessageType.ERROR, content="boom!")
    bridge._render_queue_message(msg)
    written = " ".join(str(m) for m in app._chat.written)
    assert "boom!" in written
    assert "red" in written


def test_render_queue_message_warning():
    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = UIMessage(type=MessageType.WARNING, content="careful!")
    bridge._render_queue_message(msg)
    written = " ".join(str(m) for m in app._chat.written)
    assert "careful!" in written
    assert "yellow" in written


def test_render_queue_message_success():
    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = UIMessage(type=MessageType.SUCCESS, content="done!")
    bridge._render_queue_message(msg)
    written = " ".join(str(m) for m in app._chat.written)
    assert "done!" in written
    assert "green" in written


def test_render_queue_message_system():
    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = UIMessage(type=MessageType.SYSTEM, content="system note")
    bridge._render_queue_message(msg)
    written = " ".join(str(m) for m in app._chat.written)
    assert "system note" in written
    assert "dim" in written


def test_render_queue_message_tool_output():
    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = UIMessage(type=MessageType.TOOL_OUTPUT, content="tool result")
    bridge._render_queue_message(msg)
    written = " ".join(str(m) for m in app._chat.written)
    assert "tool result" in written
    assert "cyan" in written


def test_render_queue_message_human_input():
    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = UIMessage(type=MessageType.HUMAN_INPUT_REQUEST, content="Enter value:")
    bridge._render_queue_message(msg)
    written = " ".join(str(m) for m in app._chat.written)
    assert "Enter value:" in written
    assert "cyan" in written


def test_render_queue_message_rich_renderable():
    """Rich renderables (e.g. Text) pass straight through to write()."""
    from rich.text import Text

    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    rich_content = Text("styled content")
    msg = UIMessage(type=MessageType.INFO, content=rich_content)
    bridge._render_queue_message(msg)
    assert rich_content in app._chat.written


def test_render_queue_message_empty_content():
    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = UIMessage(type=MessageType.INFO, content="")
    bridge._render_queue_message(msg)
    # Nothing should be written for empty content
    assert app._chat.written == []


def test_render_queue_message_none_content():
    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = UIMessage(type=MessageType.INFO, content=None)
    bridge._render_queue_message(msg)
    assert app._chat.written == []


def test_render_queue_message_agent_response():
    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = UIMessage(type=MessageType.AGENT_RESPONSE, content="# Heading\n\nBody text.")
    bridge._render_queue_message(msg)
    # Something should have been written (markdown object or plain text)
    assert len(app._chat.written) > 0


def test_on_queue_message_from_thread_calls_render():
    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = UIMessage(type=MessageType.INFO, content="thread msg")
    bridge._on_queue_message_from_thread(msg)
    assert any("thread msg" in str(m) for m in app._chat.written)


def test_on_queue_message_from_thread_ignores_app_error():
    """If call_from_thread raises, we swallow the exception gracefully."""
    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    app.call_from_thread = MagicMock(side_effect=RuntimeError("app dying"))
    bridge = TUIMessageBridge(app)
    msg = UIMessage(type=MessageType.INFO, content="msg")
    # Should not raise
    bridge._on_queue_message_from_thread(msg)


def test_render_queue_message_ignores_missing_widget():
    """If query_one fails (widget not mounted yet), we swallow the exception."""
    from code_puppy.messaging.message_queue import MessageType, UIMessage

    app = MockApp()
    app.query_one = MagicMock(side_effect=Exception("not mounted"))
    bridge = TUIMessageBridge(app)
    msg = UIMessage(type=MessageType.INFO, content="early msg")
    # Should not raise
    bridge._render_queue_message(msg)


def test_render_agent_response_no_content():
    from code_puppy.messaging.messages import AgentResponseMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = AgentResponseMessage(content="", is_markdown=True)
    bridge._render_agent_response(msg)
    assert app._chat.written == []


def test_render_agent_response_markdown():
    from code_puppy.messaging.messages import AgentResponseMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = AgentResponseMessage(content="# Title\n\nSome text.", is_markdown=True)
    bridge._render_agent_response(msg)
    assert len(app._chat.written) > 0


def test_render_agent_response_plain():
    from code_puppy.messaging.messages import AgentResponseMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = AgentResponseMessage(content="plain response", is_markdown=False)
    bridge._render_agent_response(msg)
    assert any("plain response" in str(m) for m in app._chat.written)


def test_on_bus_message_handles_agent_response():
    from code_puppy.messaging.messages import AgentResponseMessage

    app = MockApp()
    bridge = TUIMessageBridge(app)
    msg = AgentResponseMessage(content="bus response", is_markdown=True)
    bridge._on_bus_message(msg)
    # Something must have been written (Markdown object or plain string)
    assert len(app._chat.written) > 0


def test_on_bus_message_ignores_unknown_type():
    app = MockApp()
    bridge = TUIMessageBridge(app)
    # Should not raise for arbitrary message types
    bridge._on_bus_message(object())
    assert app._chat.written == []


# ---------------------------------------------------------------------------
# TUIConsole
# ---------------------------------------------------------------------------


def test_tui_console_creation():
    app = MockApp()
    console = TUIConsole(app)
    assert console.file is console
    assert console.width > 0


def test_tui_console_print_plain_text():
    app = MockApp()
    console = TUIConsole(app)
    console.print("hello world")
    assert any("hello world" in str(m) for m in app._chat.written)


def test_tui_console_print_rich_renderable():
    from rich.text import Text

    app = MockApp()
    console = TUIConsole(app)
    rt = Text("rich text")
    console.print(rt)
    assert rt in app._chat.written


def test_tui_console_print_empty_args():
    app = MockApp()
    console = TUIConsole(app)
    console.print()  # No args — should not write
    assert app._chat.written == []


def test_tui_console_print_whitespace_only():
    app = MockApp()
    console = TUIConsole(app)
    console.print("   ")
    # Whitespace-only content is not written
    assert app._chat.written == []


def test_tui_console_print_ignores_missing_widget():
    app = MockApp()
    app.query_one = MagicMock(side_effect=Exception("not mounted"))
    console = TUIConsole(app)
    console.print("msg")  # Should not raise


def test_tui_console_flush_no_op():
    app = MockApp()
    console = TUIConsole(app)
    console.flush()  # Must not raise


def test_tui_console_write_plain_text():
    app = MockApp()
    console = TUIConsole(app)
    console.write("some output\n")
    assert len(app._chat.written) > 0


def test_tui_console_write_ansi():
    app = MockApp()
    console = TUIConsole(app)
    # ANSI codes should be decoded / stripped rather than written verbatim
    console.write("\x1b[32mgreen text\x1b[0m\n")
    written = " ".join(str(m) for m in app._chat.written)
    # The ANSI escape markers should not appear in final output
    assert "\x1b" not in written
    assert "green text" in written


def test_tui_console_write_empty():
    app = MockApp()
    console = TUIConsole(app)
    console.write("")
    assert app._chat.written == []


def test_tui_console_write_whitespace_only():
    app = MockApp()
    console = TUIConsole(app)
    console.write("   \n  ")
    assert app._chat.written == []


def test_tui_console_write_ignores_missing_widget():
    app = MockApp()
    app.query_one = MagicMock(side_effect=Exception("not mounted"))
    console = TUIConsole(app)
    console.write("text")  # Should not raise


def test_tui_console_print_exception():
    app = MockApp()
    console = TUIConsole(app)
    try:
        raise ValueError("test error")
    except ValueError:
        console.print_exception()
    # Something should have been written to the chat log
    written = " ".join(str(m) for m in app._chat.written)
    assert "ValueError" in written or "test error" in written or "red" in written


def test_tui_console_print_exception_no_active_exception():
    app = MockApp()
    console = TUIConsole(app)
    # print_exception() with no active exception should not crash
    console.print_exception()


def test_tui_console_width_default():
    app = MockApp()
    console = TUIConsole(app)
    assert console.width == 120


def test_tui_console_print_multiple_args():
    app = MockApp()
    console = TUIConsole(app)
    console.print("first", "second")
    written = " ".join(str(m) for m in app._chat.written)
    assert "first" in written
    assert "second" in written
