"""Tests for bd-106: Elixir Bridge Protocol Optimizations.

Tests the Python-side optimizations for IPC overhead reduction:
- _ResponseSlot: threading.Event-based response matching (replaces 10ms polling)
- _serialize_json / _deserialize_json: orjson support with fallback
- call_batch: N requests in single frame
- send_batch_to_elixir: batch framing transport
- handle_response: response slot completion

bd-106 builds on bd-103 optimizations to verify performance targets:
- Req/Resp latency < 0.020ms
- Throughput > 100,000 ops/s (8 workers)
- Zero-latency response notification (no polling floor)
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from code_puppy.plugins.elixir_bridge import (
    _ResponseSlot,
    _pending_responses,
    _response_lock,
    handle_response,
)
from code_puppy.plugins.elixir_bridge.wire_protocol import (
    _serialize_json,
    _deserialize_json,
    _HAS_ORJSON,
)


# ── _ResponseSlot Tests (Phase 1: Polling Fix) ──────────────────────────────


class TestResponseSlot:
    """Tests for _ResponseSlot with threading.Event for zero-latency notification."""

    def test_initial_state(self):
        """Response slot should start with no result and unset event."""
        slot = _ResponseSlot()
        assert slot.result is None
        assert slot.error is None
        assert not slot.event.is_set()

    def test_complete_sets_result_and_event(self):
        """complete() should set result, error, and signal the event."""
        slot = _ResponseSlot()
        slot.complete({"data": "test"}, None)

        assert slot.event.is_set()
        assert slot.result == {"data": "test"}
        assert slot.error is None

    def test_complete_with_error(self):
        """complete() should handle error responses."""
        slot = _ResponseSlot()
        slot.complete(None, {"code": -32000, "message": "Server error"})

        assert slot.event.is_set()
        assert slot.result is None
        assert slot.error == {"code": -32000, "message": "Server error"}

    def test_wait_returns_immediately_when_complete(self):
        """wait() should return instantly when event is already set."""
        slot = _ResponseSlot()
        slot.complete({"ok": True}, None)

        start = time.perf_counter()
        result, error = slot.wait(timeout=5.0)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result == {"ok": True}
        assert error is None
        # Should be near-instant (< 1ms), not 10ms polling floor
        assert elapsed_ms < 1.0, f"Response took {elapsed_ms:.3f}ms, expected < 1ms"

    def test_wait_blocks_until_complete(self):
        """wait() should block until complete() is called from another thread."""
        slot = _ResponseSlot()
        results = []

        def waiter():
            result, error = slot.wait(timeout=5.0)
            results.append((result, error))

        thread = threading.Thread(target=waiter)
        thread.start()

        # Give waiter time to block
        time.sleep(0.01)
        assert len(results) == 0, "wait() returned before complete()"

        # Complete from main thread
        slot.complete({"data": "delayed"}, None)
        thread.join(timeout=1.0)

        assert len(results) == 1
        assert results[0] == ({"data": "delayed"}, None)

    def test_wait_timeout(self):
        """wait() should return (None, None) on timeout."""
        slot = _ResponseSlot()

        start = time.perf_counter()
        result, error = slot.wait(timeout=0.05)
        elapsed = time.perf_counter() - start

        assert result is None
        assert error is None
        assert elapsed >= 0.04, "Timeout returned too early"

    def test_thread_safety_of_complete(self):
        """Multiple threads calling complete() should be safe (lock protected)."""
        slot = _ResponseSlot()
        errors = []

        def complete_with_value(val):
            try:
                slot.complete({"value": val}, None)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=complete_with_value, args=(i,)) for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=1.0)

        assert len(errors) == 0, f"Thread safety errors: {errors}"
        assert slot.event.is_set()

    def test_latency_no_polling_floor(self):
        latencies = []

        for _ in range(100):
            slot = _ResponseSlot()

            def respond():
                time.sleep(0.001)  # 1ms simulated network delay
                slot.complete({"ok": True}, None)

            thread = threading.Thread(target=respond)
            thread.start()

            start = time.perf_counter()
            result, error = slot.wait(timeout=1.0)
            elapsed_ms = (time.perf_counter() - start) * 1000

            thread.join()
            latencies.append(elapsed_ms)

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)

        # Average should be ~1ms (the simulated delay), not 10ms+ from polling
        assert avg_latency < 5.0, (
            f"Average latency {avg_latency:.3f}ms too high (polling floor?)"
        )
        assert max_latency < 10.0, f"Max latency {max_latency:.3f}ms too high"


# ── Serialization Tests (Phase 2: orjson) ────────────────────────────────────


class TestSerialization:
    """Tests for _serialize_json / _deserialize_json with orjson optimization."""

    def test_serialize_dict(self):
        """Should serialize a dict to JSON bytes."""
        data = {"jsonrpc": "2.0", "method": "test", "params": {"key": "value"}}
        result = _serialize_json(data)

        assert isinstance(result, bytes)
        parsed = json.loads(result)
        assert parsed == data

    def test_serialize_list(self):
        """Should serialize a list (batch format) to JSON bytes."""
        data = [
            {"jsonrpc": "2.0", "id": 1, "method": "a"},
            {"jsonrpc": "2.0", "id": 2, "method": "b"},
        ]
        result = _serialize_json(data)

        assert isinstance(result, bytes)
        parsed = json.loads(result)
        assert parsed == data

    def test_serialize_nested_structures(self):
        """Should handle deeply nested structures."""
        data = {
            "jsonrpc": "2.0",
            "method": "file_read",
            "params": {
                "path": "/test/file.py",
                "options": {"start_line": 1, "num_lines": 100},
                "metadata": {"tags": ["python", "test"], "count": 42},
            },
        }
        result = _serialize_json(data)
        parsed = json.loads(result)
        assert parsed == data

    def test_serialize_unicode(self):
        """Should handle Unicode characters correctly."""
        data = {"text": "Hello 世界 🐕 Ñoño"}
        result = _serialize_json(data)
        parsed = json.loads(result)
        assert parsed == data

    def test_serialize_empty_containers(self):
        """Should handle empty dict and list."""
        assert _serialize_json({}) == b"{}"
        assert _serialize_json([]) == b"[]"

    def test_deserialize_bytes(self):
        """Should deserialize JSON bytes to Python objects."""
        raw = b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}'
        result = _deserialize_json(raw)

        assert result == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    def test_deserialize_batch(self):
        """Should deserialize JSON array (batch format)."""
        raw = b'[{"id":1},{"id":2}]'
        result = _deserialize_json(raw)

        assert isinstance(result, list)
        assert len(result) == 2

    def test_serialize_deserialize_roundtrip(self):
        """Data should survive serialize → deserialize roundtrip."""
        original = {
            "jsonrpc": "2.0",
            "id": "req-abc123",
            "method": "file_list",
            "params": {"directory": ".", "recursive": True},
        }
        serialized = _serialize_json(original)
        deserialized = _deserialize_json(serialized)
        assert deserialized == original

    def test_serialize_compact_no_whitespace(self):
        """Serialized output should be compact (no unnecessary whitespace)."""
        data = {"key": "value", "nested": {"a": 1}}
        result = _serialize_json(data)

        # Should not contain spaces after : or ,
        assert b": " not in result
        assert b", " not in result

    def test_orjson_flag_available(self):
        """_HAS_ORJSON should be defined (True if orjson installed, False otherwise)."""
        assert isinstance(_HAS_ORJSON, bool)


# ── handle_response Tests ────────────────────────────────────────────────────


class TestHandleResponse:
    """Tests for handle_response() response slot matching."""

    def test_handle_response_completes_slot(self):
        """handle_response should complete the matching pending slot."""
        # Register a pending response
        slot = _ResponseSlot()
        request_id = "test-handle-001"

        with _response_lock:
            _pending_responses[request_id] = slot

        try:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"files": ["a.py", "b.py"]},
            }
            handle_response(response)

            assert slot.event.is_set()
            assert slot.result == {"files": ["a.py", "b.py"]}
            assert slot.error is None
        finally:
            with _response_lock:
                _pending_responses.pop(request_id, None)

    def test_handle_response_error(self):
        """handle_response should complete slot with error."""
        slot = _ResponseSlot()
        request_id = "test-handle-error"

        with _response_lock:
            _pending_responses[request_id] = slot

        try:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "Method not found"},
            }
            handle_response(response)

            assert slot.event.is_set()
            assert slot.result is None
            assert slot.error == {"code": -32601, "message": "Method not found"}
        finally:
            with _response_lock:
                _pending_responses.pop(request_id, None)

    def test_handle_response_no_matching_slot(self):
        """handle_response should silently ignore unknown request IDs."""
        # Should not raise
        handle_response(
            {
                "jsonrpc": "2.0",
                "id": "unknown-id-999",
                "result": {"ok": True},
            }
        )

    def test_handle_response_notification_no_id(self):
        """handle_response should ignore notifications (no id field)."""
        # Should not raise
        handle_response(
            {
                "jsonrpc": "2.0",
                "method": "event",
                "params": {"type": "status"},
            }
        )

    def test_handle_response_concurrent_slots(self):
        """Multiple concurrent response slots should resolve independently."""
        slots = {}
        for i in range(10):
            rid = f"concurrent-{i}"
            slot = _ResponseSlot()
            slots[rid] = slot
            with _response_lock:
                _pending_responses[rid] = slot

        try:
            # Resolve in reverse order
            for i in range(9, -1, -1):
                rid = f"concurrent-{i}"
                handle_response(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "result": {"index": i},
                    }
                )

            # All should be resolved
            for i in range(10):
                rid = f"concurrent-{i}"
                assert slots[rid].event.is_set()
                assert slots[rid].result == {"index": i}
        finally:
            with _response_lock:
                for rid in slots:
                    _pending_responses.pop(rid, None)


# ── Batch Framing Tests (Phase 3) ───────────────────────────────────────────


class TestBatchFraming:
    """Tests for batch request framing in wire_protocol."""

    def test_frame_message_single(self):
        """frame_message should produce Content-Length framed bytes."""
        from code_puppy.plugins.elixir_bridge.wire_protocol import frame_message

        message = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        framed = frame_message(message)

        assert isinstance(framed, bytes)
        assert framed.startswith(b"Content-Length: ")
        assert b"\r\n\r\n" in framed

        # Extract and verify body
        header, body = framed.split(b"\r\n\r\n", 1)
        content_length = int(header.split(b": ")[1])
        assert content_length == len(body)
        assert json.loads(body) == message

    def test_parse_framed_message_roundtrip(self):
        """frame_message → parse_framed_message should roundtrip."""
        from code_puppy.plugins.elixir_bridge.wire_protocol import (
            frame_message,
            parse_framed_message,
        )

        original = {
            "jsonrpc": "2.0",
            "id": "req-123",
            "result": {"status": "ok", "data": [1, 2, 3]},
        }
        framed = frame_message(original)
        parsed = parse_framed_message(framed)
        assert parsed == original

    def test_batch_serialization(self):
        """Batch format (list of messages) should serialize correctly."""
        batch = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "file_read",
                "params": {"path": "a.py"},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "file_read",
                "params": {"path": "b.py"},
            },
        ]
        serialized = _serialize_json(batch)
        parsed = _deserialize_json(serialized)
        assert parsed == batch
        assert len(parsed) == 2


# ── Performance / Latency Tests ─────────────────────────────────────────────


class TestPerformance:
    """Performance validation tests for bd-106 targets."""

    def test_serialization_latency(self):
        """_serialize_json should be fast (< 0.02ms per call for small payloads)."""
        data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "file_list",
            "params": {"directory": "."},
        }

        # Warm up
        for _ in range(100):
            _serialize_json(data)

        # Measure
        iterations = 1000
        start = time.perf_counter()
        for _ in range(iterations):
            _serialize_json(data)
        elapsed = time.perf_counter() - start

        per_call_us = (elapsed / iterations) * 1_000_000  # microseconds
        # Target: < 20μs per call (well within < 0.020ms target)
        assert per_call_us < 20, (
            f"Serialization took {per_call_us:.1f}μs/call, expected < 20μs"
        )

    def test_deserialization_latency(self):
        """_deserialize_json should be fast."""
        raw = b'{"jsonrpc":"2.0","id":1,"result":{"files":["a.py","b.py"]}}'

        # Warm up
        for _ in range(100):
            _deserialize_json(raw)

        iterations = 1000
        start = time.perf_counter()
        for _ in range(iterations):
            _deserialize_json(raw)
        elapsed = time.perf_counter() - start

        per_call_us = (elapsed / iterations) * 1_000_000
        assert per_call_us < 100, (
            f"Deserialization took {per_call_us:.1f}μs/call, expected < 100μs"
        )

    def test_response_slot_notification_latency(self):
        """Response notification should be < 0.1ms (no polling floor)."""
        latencies = []

        for _ in range(50):
            slot = _ResponseSlot()

            def respond():
                slot.complete({"ok": True}, None)

            # Measure from complete() to wait() returning
            start = time.perf_counter()
            thread = threading.Thread(target=respond)
            thread.start()
            result, _ = slot.wait(timeout=1.0)
            elapsed_ms = (time.perf_counter() - start) * 1000

            thread.join()
            latencies.append(elapsed_ms)

        avg_ms = sum(latencies) / len(latencies)
        # Target: instant notification, well under 1ms
        assert avg_ms < 1.0, (
            f"Average notification latency {avg_ms:.3f}ms, expected < 1ms"
        )

    def test_handle_response_throughput(self):
        """handle_response should process > 100k responses/sec."""
        # Pre-register slots
        num_responses = 10000
        for i in range(num_responses):
            slot = _ResponseSlot()
            with _response_lock:
                _pending_responses[f"perf-{i}"] = slot

        try:
            responses = [
                {"jsonrpc": "2.0", "id": f"perf-{i}", "result": {"i": i}}
                for i in range(num_responses)
            ]

            start = time.perf_counter()
            for resp in responses:
                handle_response(resp)
            elapsed = time.perf_counter() - start

            ops_per_sec = num_responses / elapsed
            # Target: > 100k ops/s
            assert ops_per_sec > 100000, (
                f"Throughput {ops_per_sec:.0f} ops/s, expected > 100k ops/s"
            )
        finally:
            with _response_lock:
                for i in range(num_responses):
                    _pending_responses.pop(f"perf-{i}", None)


# ── send_batch_to_elixir Tests ──────────────────────────────────────────────


class TestSendBatchToElixir:
    """Tests for send_batch_to_elixir() batch framing transport."""

    def test_send_batch_writes_framed_json_array(self, monkeypatch):
        """send_batch_to_elixir should write Content-Length framed JSON array to stdout."""
        import io
        import sys

        from code_puppy.plugins.elixir_bridge import send_batch_to_elixir

        # Enable bridge mode
        monkeypatch.setattr("code_puppy.plugins.elixir_bridge.BRIDGE_ENABLED", True)

        # Capture stdout buffer writes by replacing sys.stdout with a custom object
        captured = io.BytesIO()

        class FakeStdout:
            buffer = captured

        monkeypatch.setattr(sys, "stdout", FakeStdout())

        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "file_list",
                "params": {"directory": "."},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "file_read",
                "params": {"path": "a.py"},
            },
        ]

        send_batch_to_elixir(requests)

        output = captured.getvalue()
        # Should have Content-Length framing
        assert output.startswith(b"Content-Length: ")
        assert b"\r\n\r\n" in output

        # Extract and verify body
        header, body = output.split(b"\r\n\r\n", 1)
        content_length = int(header.split(b": ")[1])
        assert content_length == len(body)

        # Body should be JSON array
        parsed = json.loads(body)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["method"] == "file_list"
        assert parsed[1]["method"] == "file_read"

    def test_send_batch_raises_when_bridge_disabled(self):
        """send_batch_to_elixir should raise NotImplementedError when bridge is off."""
        from code_puppy.plugins.elixir_bridge import send_batch_to_elixir

        with pytest.raises(NotImplementedError):
            send_batch_to_elixir([{"jsonrpc": "2.0", "id": 1, "method": "ping"}])

    def test_send_batch_connection_error_on_write_failure(self, monkeypatch):
        """send_batch_to_elixir should raise ConnectionError on write failure."""
        import sys

        from code_puppy.plugins.elixir_bridge import send_batch_to_elixir

        monkeypatch.setattr("code_puppy.plugins.elixir_bridge.BRIDGE_ENABLED", True)

        # Make stdout.buffer.write raise
        class BrokenBuffer:
            def write(self, _):
                raise OSError("pipe broken")

            def flush(self):
                pass

        class FakeStdout:
            buffer = BrokenBuffer()

        monkeypatch.setattr(sys, "stdout", FakeStdout())

        with pytest.raises(ConnectionError, match="Failed to send batch"):
            send_batch_to_elixir([{"jsonrpc": "2.0", "id": 1, "method": "ping"}])


# ── call_batch Tests ─────────────────────────────────────────────────────────


class TestCallBatch:
    """Tests for call_batch() batch request/response matching."""

    def test_call_batch_result_ordering(self, monkeypatch):
        """call_batch should return results in same order as input calls."""
        from code_puppy.plugins.elixir_bridge import call_batch

        monkeypatch.setattr(
            "code_puppy.plugins.elixir_bridge.is_connected", lambda: True
        )

        # Capture registered slots and request IDs so we can respond in order
        registered_ids = []

        def mock_send_batch(requests):
            nonlocal registered_ids
            registered_ids = [r["id"] for r in requests]

        monkeypatch.setattr(
            "code_puppy.plugins.elixir_bridge.send_batch_to_elixir", mock_send_batch
        )

        calls = [
            ("file_list", {"directory": "/a"}),
            ("file_list", {"directory": "/b"}),
            ("file_list", {"directory": "/c"}),
        ]

        def run_batch():
            return call_batch(calls, timeout=5.0)

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_batch)

            # Wait for slots to be registered
            deadline = time.time() + 2.0
            while not registered_ids and time.time() < deadline:
                time.sleep(0.001)

            assert len(registered_ids) == 3

            # Respond in reverse order
            handle_response(
                {"jsonrpc": "2.0", "id": registered_ids[2], "result": {"dir": "/c"}}
            )
            handle_response(
                {"jsonrpc": "2.0", "id": registered_ids[0], "result": {"dir": "/a"}}
            )
            handle_response(
                {"jsonrpc": "2.0", "id": registered_ids[1], "result": {"dir": "/b"}}
            )

            results = future.result(timeout=5.0)

        # Results should be in original call order, not response order
        assert results == [
            {"dir": "/a"},
            {"dir": "/b"},
            {"dir": "/c"},
        ]

    def test_call_batch_timeout(self, monkeypatch):
        """call_batch should raise TimeoutError if responses don't arrive in time."""
        from code_puppy.plugins.elixir_bridge import call_batch

        monkeypatch.setattr(
            "code_puppy.plugins.elixir_bridge.is_connected", lambda: True
        )
        monkeypatch.setattr(
            "code_puppy.plugins.elixir_bridge.send_batch_to_elixir",
            lambda requests: None,  # No-op, no responses will come
        )

        calls = [("file_list", {"directory": "."})]

        with pytest.raises(TimeoutError):
            call_batch(calls, timeout=0.1)

    def test_call_batch_cleans_up_pending_responses(self, monkeypatch):
        """call_batch should clean up _pending_responses even on timeout."""
        from code_puppy.plugins.elixir_bridge import call_batch

        monkeypatch.setattr(
            "code_puppy.plugins.elixir_bridge.is_connected", lambda: True
        )
        monkeypatch.setattr(
            "code_puppy.plugins.elixir_bridge.send_batch_to_elixir",
            lambda requests: None,
        )

        # Record how many pending responses exist before and after
        before_count = len(_pending_responses)

        calls = [("file_list", {"directory": "."})]

        try:
            call_batch(calls, timeout=0.05)
        except TimeoutError:
            pass

        after_count = len(_pending_responses)
        assert after_count == before_count, (
            f"Pending responses leaked: {after_count - before_count} slots not cleaned up"
        )

    def test_call_batch_connection_error_when_disconnected(self, monkeypatch):
        """call_batch should raise ConnectionError when not connected."""
        from code_puppy.plugins.elixir_bridge import call_batch

        monkeypatch.setattr(
            "code_puppy.plugins.elixir_bridge.is_connected", lambda: False
        )

        with pytest.raises(ConnectionError, match="not connected"):
            call_batch([("ping", {})])

    def test_call_batch_error_propagation(self, monkeypatch):
        """call_batch should raise RuntimeError with error from Elixir."""
        from code_puppy.plugins.elixir_bridge import call_batch

        monkeypatch.setattr(
            "code_puppy.plugins.elixir_bridge.is_connected", lambda: True
        )

        registered_ids = []

        def mock_send_batch(requests):
            nonlocal registered_ids
            registered_ids = [r["id"] for r in requests]

        monkeypatch.setattr(
            "code_puppy.plugins.elixir_bridge.send_batch_to_elixir", mock_send_batch
        )

        calls = [("file_read", {"path": "/nonexistent"})]

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(call_batch, calls, 5.0)

            deadline = time.time() + 2.0
            while not registered_ids and time.time() < deadline:
                time.sleep(0.001)

            handle_response(
                {
                    "jsonrpc": "2.0",
                    "id": registered_ids[0],
                    "error": {"code": -32000, "message": "File not found"},
                }
            )

            with pytest.raises(RuntimeError, match="Elixir call failed"):
                future.result(timeout=5.0)
