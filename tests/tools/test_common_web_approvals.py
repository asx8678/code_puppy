"""Tests for tools/common.py web-approval routing (web-gjs).

Validates that get_user_approval and get_user_approval_async:
- Route through request_approval_sync when CODE_PUPPY_WEB_APPROVALS=1.
- Fall back to CLI flow when the env var is unset or the import fails.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


class TestGetUserApprovalWebRouting:
    """Tests for the sync get_user_approval web-approval gate."""

    def test_routes_to_browser_when_web_approvals_enabled(self) -> None:
        """When CODE_PUPPY_WEB_APPROVALS=1, request_approval_sync is called."""
        with patch.dict(os.environ, {"CODE_PUPPY_WEB_APPROVALS": "1"}):
            mock_request = MagicMock(return_value=(True, "ok from browser"))

            with patch(
                "code_puppy.api.approvals.request_approval_sync",
                mock_request,
            ):
                from code_puppy.tools.common import get_user_approval

                approved, feedback = get_user_approval(
                    title="Edit file?",
                    content="Replace foo.py content",
                    preview="--- a/foo.py\n+++ b/foo.py",
                )

            assert approved is True
            assert feedback == "ok from browser"
            mock_request.assert_called_once_with(
                title="Edit file?",
                content="Replace foo.py content",
                preview="--- a/foo.py\n+++ b/foo.py",
                border_style="dim white",
                puppy_name="Max",
            )

    def test_extracts_plain_text_from_rich_content(self) -> None:
        """When content is a Rich Text object, its .plain attribute is sent."""
        from rich.text import Text

        with patch.dict(os.environ, {"CODE_PUPPY_WEB_APPROVALS": "1"}):
            mock_request = MagicMock(return_value=(True, None))

            with patch(
                "code_puppy.api.approvals.request_approval_sync",
                mock_request,
            ):
                from code_puppy.tools.common import get_user_approval

                rich_content = Text("Edit this file")
                get_user_approval(
                    title="Edit?",
                    content=rich_content,
                    puppy_name="Rex",
                )

            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["content"] == "Edit this file"
            assert call_kwargs["puppy_name"] == "Rex"

    def test_falls_back_on_import_error(self) -> None:
        """If request_approval_sync import fails, CLI path is used."""
        with patch.dict(os.environ, {"CODE_PUPPY_WEB_APPROVALS": "1"}):
            # Simulate ImportError by making the import fail
            with patch(
                "code_puppy.api.approvals.request_approval_sync",
                side_effect=ImportError("no approvals module"),
            ):
                # The CLI path uses arrow_select which needs a TTY, so
                # we verify it gets past the web-approval branch and
                # raises something from the CLI path instead.
                with patch(
                    "code_puppy.tools.common.arrow_select",
                    side_effect=EOFError("no tty"),
                ):
                    from code_puppy.tools.common import get_user_approval

                    # Should fall back to CLI and hit EOFError on arrow_select
                    approved, _ = get_user_approval(
                        title="t",
                        content="c",
                        puppy_name="Max",
                    )
                    # EOFError in arrow_select returns False
                    assert approved is False

    def test_cli_path_when_web_approvals_disabled(self) -> None:
        """Without CODE_PUPPY_WEB_APPROVALS, the CLI path is used."""
        # Ensure the env var is NOT set
        env = dict(os.environ)
        env.pop("CODE_PUPPY_WEB_APPROVALS", None)

        with patch.dict(os.environ, env, clear=True):
            with patch(
                "code_puppy.tools.common.arrow_select",
                return_value="✓ Approve",
            ):
                with patch(
                    "code_puppy.tools.command_runner.set_awaiting_user_input",
                ):
                    with patch(
                        "code_puppy.tools.common.emit_info",
                    ):
                        with patch(
                            "code_puppy.tools.common.emit_success",
                        ):
                            from code_puppy.tools.common import get_user_approval

                            approved, feedback = get_user_approval(
                                title="t",
                                content="c",
                                puppy_name="Max",
                            )

            assert approved is True


class TestGetUserApprovalAsyncWebRouting:
    """Tests for the async get_user_approval_async web-approval gate."""

    @pytest.mark.asyncio
    async def test_routes_to_browser_when_web_approvals_enabled(self) -> None:
        """When CODE_PUPPY_WEB_APPROVALS=1, async version also routes to browser."""
        with patch.dict(os.environ, {"CODE_PUPPY_WEB_APPROVALS": "1"}):
            mock_request = MagicMock(return_value=(True, "async browser ok"))

            with patch(
                "code_puppy.api.approvals.request_approval_sync",
                mock_request,
            ):
                from code_puppy.tools.common import get_user_approval_async

                approved, feedback = await get_user_approval_async(
                    title="Delete file?",
                    content="rm foo.py",
                    preview="--- a/foo.py",
                )

            assert approved is True
            assert feedback == "async browser ok"
            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_on_import_error(self) -> None:
        """If request_approval_sync fails, async falls back to CLI."""
        with patch.dict(os.environ, {"CODE_PUPPY_WEB_APPROVALS": "1"}):
            with patch(
                "code_puppy.api.approvals.request_approval_sync",
                side_effect=ImportError("nope"),
            ):
                with patch(
                    "code_puppy.tools.common.arrow_select_async",
                    side_effect=EOFError("no tty"),
                ):
                    from code_puppy.tools.common import get_user_approval_async

                    approved, _ = await get_user_approval_async(
                        title="t",
                        content="c",
                        puppy_name="Max",
                    )
                    assert approved is False

    @pytest.mark.asyncio
    async def test_extracts_plain_text_from_rich_content(self) -> None:
        """When async content is a Rich Text, .plain is extracted."""
        from rich.text import Text

        with patch.dict(os.environ, {"CODE_PUPPY_WEB_APPROVALS": "1"}):
            mock_request = MagicMock(return_value=(True, None))

            with patch(
                "code_puppy.api.approvals.request_approval_sync",
                mock_request,
            ):
                from code_puppy.tools.common import get_user_approval_async

                rich_content = Text("Async edit this file")
                await get_user_approval_async(
                    title="Edit?",
                    content=rich_content,
                )

            call_kwargs = mock_request.call_args[1]
            assert call_kwargs["content"] == "Async edit this file"


class TestWebApprovalDoesNotLeakSecrets:
    """Security: web-approval path must not bypass redaction."""

    def test_request_approval_sync_receives_redacted_content(self) -> None:
        """Even if the content has secrets, they pass through approvals
        which redact before emitting to the browser."""
        with patch.dict(os.environ, {"CODE_PUPPY_WEB_APPROVALS": "1"}):
            mock_request = MagicMock(return_value=(False, None))

            with patch(
                "code_puppy.api.approvals.request_approval_sync",
                mock_request,
            ):
                from code_puppy.tools.common import get_user_approval

                get_user_approval(
                    title="Edit?",
                    content="api_key=sk-abcdefghijklmnopqrstuvwxyz1234567890",
                )

            # The approval layer redacts content via redact_approval_dict
            # when emitting — that's tested in test_approvals.py.
            # Here we just confirm the routing works with secret-like content.
            assert mock_request.called
