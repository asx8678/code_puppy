"""Tests for code_puppy/api/approvals.py — browser-backed approval manager."""

import threading
from unittest.mock import patch

from code_puppy.api.approvals import (
    ApprovalManager,
    PendingApproval,
    get_approval_manager,
    request_approval_sync,
)


class TestPendingApproval:
    """Tests for PendingApproval dataclass."""

    def test_to_dict_roundtrip(self) -> None:
        pa = PendingApproval(
            approval_id="abc-123",
            title="Delete file?",
            content="rm -rf /important",
            preview="--- a/important\n+++ /dev/null",
            border_style="red",
            puppy_name="Max",
        )
        d = pa.to_dict()
        assert d["approval_id"] == "abc-123"
        assert d["title"] == "Delete file?"
        assert d["content"] == "rm -rf /important"
        assert d["preview"] == "--- a/important\n+++ /dev/null"
        assert d["border_style"] == "red"
        assert d["puppy_name"] == "Max"
        assert d["approved"] is None
        assert d["feedback"] is None
        assert "created_at" in d

    def test_defaults(self) -> None:
        pa = PendingApproval(approval_id="x", title="t", content="c")
        d = pa.to_dict()
        assert d["preview"] is None
        assert d["border_style"] == "dim white"
        assert d["puppy_name"] is None
        assert d["approved"] is None


class TestApprovalManager:
    """Tests for ApprovalManager thread-safe broker."""

    def test_request_sync_respond_approved(self) -> None:
        """Approve a pending request from another thread."""
        mgr = ApprovalManager()
        results: list[tuple[bool, str | None]] = []

        def waiter():
            result = mgr.request_sync(
                title="Allow edit?",
                content="edit file.py",
                timeout=5.0,
            )
            results.append(result)

        t = threading.Thread(target=waiter)
        t.start()

        # Wait until the request is pending
        import time

        for _ in range(50):
            if mgr.list_pending():
                break
            time.sleep(0.02)

        pending = mgr.list_pending()
        assert len(pending) == 1
        approval_id = pending[0]["approval_id"]

        ok = mgr.respond(approval_id, True, "Looks good")
        assert ok is True
        t.join(timeout=5.0)

        assert len(results) == 1
        assert results[0][0] is True
        assert results[0][1] == "Looks good"

    def test_request_sync_respond_rejected(self) -> None:
        """Reject a pending request."""
        mgr = ApprovalManager()
        results: list[tuple[bool, str | None]] = []

        def waiter():
            result = mgr.request_sync(
                title="Delete?",
                content="rm foo.py",
                timeout=5.0,
            )
            results.append(result)

        t = threading.Thread(target=waiter)
        t.start()

        import time

        for _ in range(50):
            if mgr.list_pending():
                break
            time.sleep(0.02)

        pending = mgr.list_pending()
        approval_id = pending[0]["approval_id"]

        ok = mgr.respond(approval_id, False, "Nope")
        assert ok is True
        t.join(timeout=5.0)

        assert len(results) == 1
        assert results[0][0] is False
        assert results[0][1] == "Nope"

    def test_respond_unknown_approval(self) -> None:
        """Responding to a non-existent approval returns False."""
        mgr = ApprovalManager()
        assert mgr.respond("nonexistent-id", True) is False

    def test_respond_already_resolved(self) -> None:
        """Responding twice to the same approval returns False the second time."""
        mgr = ApprovalManager()
        results: list[tuple[bool, str | None]] = []

        def waiter():
            result = mgr.request_sync(title="t", content="c", timeout=5.0)
            results.append(result)

        t = threading.Thread(target=waiter)
        t.start()

        import time

        for _ in range(50):
            if mgr.list_pending():
                break
            time.sleep(0.02)

        approval_id = mgr.list_pending()[0]["approval_id"]
        assert mgr.respond(approval_id, True) is True
        t.join(timeout=5.0)

        # Already resolved
        assert mgr.respond(approval_id, True) is False

    def test_respond_emits_redacted_feedback(self) -> None:
        """approval_response event payload must have feedback redacted."""
        mgr = ApprovalManager()
        captured_events: list[tuple[str, dict]] = []

        def fake_emit(event_type: str, payload: dict) -> None:
            captured_events.append((event_type, payload))

        # Start a pending request
        results: list[tuple[bool, str | None]] = []

        def waiter():
            result = mgr.request_sync(title="t", content="c", timeout=5.0)
            results.append(result)

        t = threading.Thread(target=waiter)
        t.start()

        import time

        for _ in range(50):
            if mgr.list_pending():
                break
            time.sleep(0.02)

        approval_id = mgr.list_pending()[0]["approval_id"]

        # Respond with feedback containing a secret pattern
        with patch(
            "code_puppy.plugins.frontend_emitter.emitter.emit_event",
            side_effect=fake_emit,
        ):
            mgr.respond(
                approval_id,
                True,
                "Looks good, api_key=sk-abcdefghijklmnopqrstuvwxyz1234567890",
            )

        t.join(timeout=5.0)

        # Find the approval_response event
        response_events = [p for et, p in captured_events if et == "approval_response"]
        assert len(response_events) == 1
        payload = response_events[0]
        assert "REDACTED" in payload["feedback"]
        assert "sk-" not in payload["feedback"]

    def test_cancel_all(self) -> None:
        """cancel_all rejects every pending request."""
        mgr = ApprovalManager()

        # Start 3 waiters
        threads = []
        for _ in range(3):
            r: list[tuple[bool, str | None]] = []

            def waiter(result_list=r):
                result_list.append(
                    mgr.request_sync(title="t", content="c", timeout=5.0)
                )

            t = threading.Thread(target=waiter)
            t.start()
            threads.append((t, r))

        import time

        for _ in range(50):
            if len(mgr.list_pending()) >= 3:
                break
            time.sleep(0.02)

        count = mgr.cancel_all("Run stopped")
        assert count == 3
        assert mgr.list_pending() == []

        for t, r in threads:
            t.join(timeout=5.0)
            assert r[0][0] is False
            assert r[0][1] == "Run stopped"

    def test_request_sync_timeout(self) -> None:
        """Request that times out returns (False, timeout message)."""
        mgr = ApprovalManager()

        # Very short timeout, no response
        approved, feedback = mgr.request_sync(title="t", content="c", timeout=0.1)
        assert approved is False
        assert "timed out" in (feedback or "").lower() or "Timed out" in (
            feedback or ""
        )

    def test_list_pending_empty(self) -> None:
        mgr = ApprovalManager()
        assert mgr.list_pending() == []

    def test_list_pending_returns_all(self) -> None:
        mgr = ApprovalManager()
        events = []

        # Create two pending requests in threads
        for _ in range(2):
            e = threading.Event()

            def waiter(evt=e):
                mgr.request_sync(
                    title="t",
                    content="c",
                    timeout=10.0,
                )
                evt.set()

            t = threading.Thread(target=waiter)
            t.daemon = True
            t.start()
            events.append((t, e))

        import time

        # Wait for requests to register
        for _ in range(100):
            if len(mgr.list_pending()) >= 2:
                break
            time.sleep(0.02)

        assert len(mgr.list_pending()) == 2

        # Clean up
        mgr.cancel_all("done")
        for t, e in events:
            t.join(timeout=2.0)


class TestModuleLevel:
    """Tests for module-level convenience functions."""

    def test_get_approval_manager_singleton(self) -> None:
        mgr1 = get_approval_manager()
        mgr2 = get_approval_manager()
        assert mgr1 is mgr2

    def test_request_approval_sync_delegates(self) -> None:
        """request_approval_sync wraps the singleton manager."""
        with patch.object(
            get_approval_manager().__class__, "request_sync", return_value=(True, "ok")
        ) as mock:
            result = request_approval_sync(title="t", content="c")
            assert result == (True, "ok")
            mock.assert_called_once()
