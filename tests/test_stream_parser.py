"""Comprehensive tests for code_puppy/utils/stream_parser.py.

Covers StreamLineParser, SSEParser, and parse_jsonl_lenient.
"""

from __future__ import annotations

import pytest

from code_puppy.utils.stream_parser import (
    SSEEvent,
    SSEParser,
    StreamLineParser,
    parse_jsonl_lenient,
)


# =============================================================================
# StreamLineParser
# =============================================================================


class TestStreamLineParser:
    """Tests for StreamLineParser."""

    # ------------------------------------------------------------------
    # Basic line emission
    # ------------------------------------------------------------------

    def test_complete_line_in_one_chunk(self):
        """A single chunk containing a complete line yields it immediately."""
        parser = StreamLineParser()
        lines = list(parser.feed("hello\n"))
        assert lines == ["hello"]

    def test_line_split_across_two_chunks(self):
        """A line whose newline arrives in a later chunk is held until then."""
        parser = StreamLineParser()
        first = list(parser.feed("hel"))
        assert first == [], "partial chunk should yield nothing"
        second = list(parser.feed("lo\n"))
        assert second == ["hello"]

    def test_multiple_lines_in_one_chunk(self):
        """Multiple newlines in one chunk yield all complete lines."""
        parser = StreamLineParser()
        lines = list(parser.feed("alpha\nbeta\ngamma\n"))
        assert lines == ["alpha", "beta", "gamma"]

    def test_partial_last_line_not_yielded(self):
        """Content after the last newline is buffered, not yielded."""
        parser = StreamLineParser()
        lines = list(parser.feed("line1\nincomplete"))
        assert lines == ["line1"]

    def test_empty_string_feed(self):
        """Feeding an empty string yields nothing."""
        parser = StreamLineParser()
        assert list(parser.feed("")) == []

    # ------------------------------------------------------------------
    # flush()
    # ------------------------------------------------------------------

    def test_flush_returns_incomplete_line(self):
        """flush() yields whatever is left in the buffer."""
        parser = StreamLineParser()
        list(parser.feed("no-newline"))
        flushed = list(parser.flush())
        assert flushed == ["no-newline"]

    def test_flush_empty_buffer_yields_nothing(self):
        """flush() on an empty buffer is a no-op."""
        parser = StreamLineParser()
        assert list(parser.flush()) == []

    def test_flush_clears_buffer(self):
        """After flush(), the buffer is empty so a second flush yields nothing."""
        parser = StreamLineParser()
        list(parser.feed("data"))
        list(parser.flush())
        assert list(parser.flush()) == []

    # ------------------------------------------------------------------
    # reset()
    # ------------------------------------------------------------------

    def test_reset_clears_buffer(self):
        """reset() discards buffered content so flush() yields nothing."""
        parser = StreamLineParser()
        list(parser.feed("buffered"))
        parser.reset()
        assert list(parser.flush()) == []

    def test_reset_allows_fresh_start(self):
        """After reset(), the parser behaves as if newly created."""
        parser = StreamLineParser()
        list(parser.feed("stale"))
        parser.reset()
        lines = list(parser.feed("fresh\n"))
        assert lines == ["fresh"]

    # ------------------------------------------------------------------
    # Line-ending variants
    # ------------------------------------------------------------------

    def test_crlf_line_endings(self):
        r"""'\r\n' line endings are stripped to just the content."""
        parser = StreamLineParser()
        lines = list(parser.feed("line1\r\nline2\r\n"))
        assert lines == ["line1", "line2"]

    def test_cr_in_middle_preserved(self):
        r"""A '\r' not immediately before '\n' is left in the output."""
        parser = StreamLineParser()
        # The spec only strips a trailing \r before \n.
        # A \r mid-string survives.
        lines = list(parser.feed("ab\rcd\n"))
        assert lines == ["ab\rcd"]

    def test_empty_line_yielded(self):
        """A bare newline yields an empty string."""
        parser = StreamLineParser()
        lines = list(parser.feed("\n"))
        assert lines == [""]

    def test_sequential_feeds(self):
        """Multiple small feeds accumulate correctly."""
        parser = StreamLineParser()
        chunks = ["h", "e", "l", "l", "o", "\n"]
        result = []
        for ch in chunks:
            result.extend(parser.feed(ch))
        assert result == ["hello"]

    def test_two_lines_split_at_newline(self):
        """Feed splits right at the newline boundary."""
        parser = StreamLineParser()
        result = []
        result.extend(parser.feed("foo\n"))
        result.extend(parser.feed("bar\n"))
        assert result == ["foo", "bar"]


# =============================================================================
# SSEParser
# =============================================================================


class TestSSEParser:
    """Tests for SSEParser."""

    # ------------------------------------------------------------------
    # Simple events
    # ------------------------------------------------------------------

    def test_simple_data_event(self):
        """A minimal SSE block with only a data field yields a message event."""
        parser = SSEParser()
        events = list(parser.feed("data: hello\n\n"))
        assert len(events) == 1
        assert events[0].data == "hello"
        assert events[0].event == "message"
        assert events[0].id is None
        assert events[0].retry is None

    def test_event_type_override(self):
        """The 'event:' field sets the event type on the yielded SSEEvent."""
        parser = SSEParser()
        events = list(parser.feed("event: ping\ndata: heartbeat\n\n"))
        assert len(events) == 1
        assert events[0].event == "ping"
        assert events[0].data == "heartbeat"

    # ------------------------------------------------------------------
    # Multi-line data
    # ------------------------------------------------------------------

    def test_multiline_data_concatenated_with_newline(self):
        """Multiple 'data:' lines are joined with '\\n'."""
        parser = SSEParser()
        events = list(parser.feed("data: line1\ndata: line2\ndata: line3\n\n"))
        assert len(events) == 1
        assert events[0].data == "line1\nline2\nline3"

    # ------------------------------------------------------------------
    # id and retry fields
    # ------------------------------------------------------------------

    def test_event_with_id(self):
        """The 'id:' field is captured on the SSEEvent."""
        parser = SSEParser()
        events = list(parser.feed("id: 42\ndata: payload\n\n"))
        assert events[0].id == "42"

    def test_event_with_retry(self):
        """The 'retry:' field is captured as an integer."""
        parser = SSEParser()
        events = list(parser.feed("retry: 3000\ndata: x\n\n"))
        assert events[0].retry == 3000

    def test_event_with_all_fields(self):
        """All four SSE fields are parsed correctly in one event."""
        parser = SSEParser()
        raw = "event: update\ndata: hello\nid: 7\nretry: 500\n\n"
        events = list(parser.feed(raw))
        assert len(events) == 1
        e = events[0]
        assert e.event == "update"
        assert e.data == "hello"
        assert e.id == "7"
        assert e.retry == 500

    # ------------------------------------------------------------------
    # Comment lines
    # ------------------------------------------------------------------

    def test_comment_lines_ignored(self):
        """Lines starting with ':' are treated as comments and discarded."""
        parser = SSEParser()
        events = list(parser.feed(":this is a comment\ndata: real\n\n"))
        assert len(events) == 1
        assert events[0].data == "real"

    def test_only_comment_no_event(self):
        """A block with only comments followed by an empty line yields nothing."""
        parser = SSEParser()
        events = list(parser.feed(":comment1\n:comment2\n\n"))
        assert events == []

    # ------------------------------------------------------------------
    # Chunked / streaming delivery
    # ------------------------------------------------------------------

    def test_events_split_across_chunks(self):
        """An event whose bytes arrive in separate chunks is still emitted once."""
        parser = SSEParser()
        raw = "data: hello\n\n"
        result = []
        for ch in raw:
            result.extend(parser.feed(ch))
        assert len(result) == 1
        assert result[0].data == "hello"

    def test_partial_event_not_yielded_until_empty_line(self):
        """Partial event data accumulates and is not emitted prematurely."""
        parser = SSEParser()
        events = list(parser.feed("data: partial"))
        assert events == [], "no empty-line terminator yet → nothing emitted"
        events = list(parser.feed("\n\n"))
        assert len(events) == 1
        assert events[0].data == "partial"

    def test_multiple_events_in_one_chunk(self):
        """Multiple SSE blocks in a single chunk produce multiple events."""
        parser = SSEParser()
        raw = "data: first\n\ndata: second\n\ndata: third\n\n"
        events = list(parser.feed(raw))
        assert len(events) == 3
        assert [e.data for e in events] == ["first", "second", "third"]

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_data_event(self):
        """An event with 'data:' and no value yields an event with empty data."""
        parser = SSEParser()
        events = list(parser.feed("data:\n\n"))
        assert len(events) == 1
        assert events[0].data == ""

    def test_no_space_after_colon(self):
        """A field value with no leading space is accepted."""
        parser = SSEParser()
        events = list(parser.feed("data:no-space\n\n"))
        assert len(events) == 1
        assert events[0].data == "no-space"

    def test_extra_space_after_colon_stripped(self):
        """All leading spaces after ':' are stripped (implementation uses lstrip)."""
        parser = SSEParser()
        events = list(parser.feed("data:  two spaces\n\n"))
        # implementation uses lstrip(" ") which strips ALL leading spaces
        assert events[0].data == "two spaces"

    def test_field_without_colon(self):
        """A line without ':' is treated as a field name with empty value."""
        parser = SSEParser()
        # 'data' alone → value is ""
        events = list(parser.feed("data\n\n"))
        assert len(events) == 1
        assert events[0].data == ""

    def test_empty_feed_yields_nothing(self):
        """Feeding an empty string to SSEParser is a no-op."""
        parser = SSEParser()
        assert list(parser.feed("")) == []

    def test_default_event_type_is_message(self):
        """When no 'event:' field is present the default type is 'message'."""
        parser = SSEParser()
        events = list(parser.feed("data: x\n\n"))
        assert events[0].event == "message"

    def test_stateful_between_feeds(self):
        """State (current event fields) persists between .feed() calls."""
        parser = SSEParser()
        list(parser.feed("event: custom\n"))
        list(parser.feed("data: body\n"))
        events = list(parser.feed("\n"))
        assert len(events) == 1
        assert events[0].event == "custom"
        assert events[0].data == "body"


# =============================================================================
# SSEEvent dataclass
# =============================================================================


class TestSSEEventDataclass:
    """Sanity checks on the SSEEvent dataclass defaults."""

    def test_defaults(self):
        e = SSEEvent()
        assert e.event == "message"
        assert e.data == ""
        assert e.id is None
        assert e.retry is None

    def test_explicit_values(self):
        e = SSEEvent(event="ping", data="ok", id="1", retry=100)
        assert e.event == "ping"
        assert e.data == "ok"
        assert e.id == "1"
        assert e.retry == 100


# =============================================================================
# parse_jsonl_lenient
# =============================================================================


class TestParseJsonlLenient:
    """Tests for parse_jsonl_lenient."""

    def test_valid_jsonl(self):
        """All valid JSON lines are parsed and returned in order."""
        text = '{"a": 1}\n{"b": 2}\n{"c": 3}'
        result = parse_jsonl_lenient(text)
        assert result == [{"a": 1}, {"b": 2}, {"c": 3}]

    def test_mixed_valid_invalid_lines(self):
        """Invalid JSON lines are skipped; valid ones are returned."""
        text = '{"ok": true}\nnot json\n{"also": "ok"}'
        result = parse_jsonl_lenient(text)
        assert result == [{"ok": True}, {"also": "ok"}]

    def test_empty_input(self):
        """Empty string returns an empty list."""
        assert parse_jsonl_lenient("") == []

    def test_whitespace_only_lines_skipped(self):
        """Lines containing only whitespace are skipped."""
        text = '{"x": 1}\n   \n\t\n{"y": 2}'
        result = parse_jsonl_lenient(text)
        assert result == [{"x": 1}, {"y": 2}]

    def test_blank_lines_skipped(self):
        """Blank lines between entries are silently ignored."""
        text = '{"a": 1}\n\n{"b": 2}\n\n'
        result = parse_jsonl_lenient(text)
        assert result == [{"a": 1}, {"b": 2}]

    def test_json_array(self):
        """JSON arrays are valid JSON values and should be parsed."""
        text = "[1, 2, 3]\n[4, 5]"
        result = parse_jsonl_lenient(text)
        assert result == [[1, 2, 3], [4, 5]]

    def test_json_number(self):
        """Bare JSON numbers are valid and should be parsed."""
        text = "42\n3.14"
        result = parse_jsonl_lenient(text)
        assert result == [42, 3.14]

    def test_json_string(self):
        """Bare JSON strings are valid and should be parsed."""
        text = '"hello"\n"world"'
        result = parse_jsonl_lenient(text)
        assert result == ["hello", "world"]

    def test_json_boolean_and_null(self):
        """JSON booleans and null literals are parsed correctly."""
        text = "true\nfalse\nnull"
        result = parse_jsonl_lenient(text)
        assert result == [True, False, None]

    def test_all_invalid_lines(self):
        """If every line is invalid, returns an empty list."""
        text = "garbage\n!!!\nnot-json"
        assert parse_jsonl_lenient(text) == []

    def test_single_valid_line(self):
        """A single valid line without trailing newline is parsed."""
        assert parse_jsonl_lenient('{"key": "val"}') == [{"key": "val"}]

    def test_preserves_order(self):
        """Results maintain the same order as the input lines."""
        lines = [str(i) for i in range(10)]
        text = "\n".join(lines)
        result = parse_jsonl_lenient(text)
        assert result == list(range(10))

    def test_leading_trailing_whitespace_stripped(self):
        """Leading/trailing whitespace around a valid JSON value is OK."""
        text = '  42  \n  {"a": 1}  '
        result = parse_jsonl_lenient(text)
        assert result == [42, {"a": 1}]
