"""Browser-backed approval prompts for the Code Puppy web dashboard.

The CLI approval flow is synchronous because file tools expect an immediate
``(approved, feedback)`` tuple.  The dashboard bridge keeps that API intact by
emitting an approval request to the frontend and waiting on a thread-safe event.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


from code_puppy.api.redactor import redact_approval_dict, redact_event_data


@dataclass
class PendingApproval:
    """A single approval request waiting for a browser response."""

    approval_id: str
    title: str
    content: str
    preview: Optional[str] = None
    border_style: str = "dim white"
    puppy_name: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    approved: Optional[bool] = None
    feedback: Optional[str] = None
    event: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self, *, redact_sensitive: bool = True) -> Dict[str, Any]:
        """Return a JSON-safe representation for API responses/events.

        When *redact_sensitive* is True (default), content, preview, and
        feedback fields are truncated and secret-patterns are masked.
        """
        d = {
            "approval_id": self.approval_id,
            "title": self.title,
            "content": self.content,
            "preview": self.preview,
            "border_style": self.border_style,
            "puppy_name": self.puppy_name,
            "created_at": self.created_at,
            "approved": self.approved,
            "feedback": self.feedback,
        }
        if redact_sensitive:
            d = redact_approval_dict(d)
        return d


class ApprovalManager:
    """Thread-safe approval request broker."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pending: Dict[str, PendingApproval] = {}

    def request_sync(
        self,
        *,
        title: str,
        content: str,
        preview: Optional[str] = None,
        border_style: str = "dim white",
        puppy_name: Optional[str] = None,
        timeout: float = 3600.0,
    ) -> tuple[bool, Optional[str]]:
        """Emit an approval request and wait for a browser response.

        Args:
            title: Request title.
            content: Main request text.
            preview: Optional diff/content preview.
            border_style: Original Rich border style, forwarded as a UI hint.
            puppy_name: Assistant name used in feedback prompts.
            timeout: Seconds to wait before rejecting defensively.

        Returns:
            ``(approved, feedback)``.
        """
        approval = PendingApproval(
            approval_id=str(uuid4()),
            title=title,
            content=content,
            preview=preview,
            border_style=border_style,
            puppy_name=puppy_name,
        )

        with self._lock:
            self._pending[approval.approval_id] = approval

        try:
            from code_puppy.plugins.frontend_emitter.emitter import emit_event

            emit_event("approval_request", redact_approval_dict(approval.to_dict()))
        except Exception:
            # Never crash file tools because the optional web event emitter failed.
            pass

        if not approval.event.wait(timeout=timeout):
            with self._lock:
                self._pending.pop(approval.approval_id, None)
            try:
                from code_puppy.plugins.frontend_emitter.emitter import emit_event

                emit_event(
                    "approval_timeout",
                    {
                        "approval_id": approval.approval_id,
                        "title": approval.title,
                        "timeout": timeout,
                    },
                )
            except Exception:
                pass
            return False, "Timed out waiting for approval in the web dashboard."

        with self._lock:
            self._pending.pop(approval.approval_id, None)

        return bool(approval.approved), approval.feedback

    def respond(
        self,
        approval_id: str,
        approved: bool,
        feedback: Optional[str] = None,
    ) -> bool:
        """Resolve a pending approval request."""
        with self._lock:
            approval = self._pending.get(approval_id)
            if approval is None:
                return False
            approval.approved = bool(approved)
            approval.feedback = (
                feedback.strip() if isinstance(feedback, str) else feedback
            )
            approval.event.set()

        try:
            from code_puppy.plugins.frontend_emitter.emitter import emit_event

            emit_event(
                "approval_response",
                redact_event_data(
                    {
                        "approval_id": approval_id,
                        "approved": bool(approved),
                        "feedback": approval.feedback,
                    }
                ),
            )
        except Exception:
            pass
        return True

    def cancel_all(self, reason: str = "Cancelled") -> int:
        """Reject every pending approval, usually because the current run stopped."""
        with self._lock:
            approvals = list(self._pending.values())
            for approval in approvals:
                approval.approved = False
                approval.feedback = reason
                approval.event.set()
            self._pending.clear()
        return len(approvals)

    def list_pending(self) -> List[Dict[str, Any]]:
        """Return all pending approval requests (redacted for boundary)."""
        with self._lock:
            return [
                approval.to_dict(redact_sensitive=True)
                for approval in self._pending.values()
            ]


_manager = ApprovalManager()


def get_approval_manager() -> ApprovalManager:
    """Return the global browser approval manager."""
    return _manager


def request_approval_sync(
    title: str,
    content: str,
    preview: Optional[str] = None,
    border_style: str = "dim white",
    puppy_name: Optional[str] = None,
    timeout: float = 3600.0,
) -> tuple[bool, Optional[str]]:
    """Convenience wrapper used by ``tools.common.get_user_approval``."""
    return _manager.request_sync(
        title=title,
        content=content,
        preview=preview,
        border_style=border_style,
        puppy_name=puppy_name,
        timeout=timeout,
    )
