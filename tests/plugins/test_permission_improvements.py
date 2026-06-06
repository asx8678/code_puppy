"""Tests for the permission-system hardening:

* file-permission dispatch fails closed on crashed/denied handlers (#1)
* shared can_prompt_user() gates sub-agents out of interactive prompts (#7)
* destructive/force guards don't prompt sub-agents & don't double-prompt (#2/#3)
* protected-path file policy always requires approval (#5)
* session approval memory for shell commands (#4)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --------------------------------------------------------------------------- #
# #1 — file-permission dispatch fails closed
# --------------------------------------------------------------------------- #
class TestFilePermissionFailClosed:
    def _run_write(self, results, tmp_path):
        from code_puppy.tools import file_modifications as fm

        target = tmp_path / "f.txt"
        target.write_text("orig")
        # write_to_file does `from code_puppy.callbacks import on_file_permission`
        # at call time, so patch the function at its source module.
        with patch("code_puppy.callbacks.on_file_permission", return_value=results):
            res = fm.write_to_file(MagicMock(), str(target), "new", True)
        return res, target

    def test_crashed_handler_none_denies(self, tmp_path):
        # A registered handler that crashed shows up as None -> must fail closed.
        res, target = self._run_write([None], tmp_path)
        assert res["success"] is False
        assert target.read_text() == "orig"

    def test_explicit_false_denies(self, tmp_path):
        res, target = self._run_write([False], tmp_path)
        assert res["success"] is False
        assert target.read_text() == "orig"

    def test_mixed_true_and_none_denies(self, tmp_path):
        # One handler approved, another crashed -> still fail closed.
        res, target = self._run_write([True, None], tmp_path)
        assert res["success"] is False
        assert target.read_text() == "orig"

    def test_all_true_allows(self, tmp_path):
        res, target = self._run_write([True], tmp_path)
        assert res["success"] is True
        assert target.read_text() == "new"

    def test_no_handlers_allows(self, tmp_path):
        # Empty list == no permission plugin installed -> opt-in allow preserved.
        res, target = self._run_write([], tmp_path)
        assert res["success"] is True
        assert target.read_text() == "new"


# --------------------------------------------------------------------------- #
# #7 — can_prompt_user()
# --------------------------------------------------------------------------- #
class TestCanPromptUser:
    def test_requires_tty(self):
        from code_puppy.tools import common

        with patch.object(
            common, "_stdin_supports_interactive_approval", return_value=False
        ):
            assert common.can_prompt_user() is False

    def test_false_for_subagent(self):
        from code_puppy.tools import common

        with (
            patch.object(
                common, "_stdin_supports_interactive_approval", return_value=True
            ),
            patch("code_puppy.tools.subagent_context.is_subagent", return_value=True),
        ):
            assert common.can_prompt_user() is False

    def test_true_for_main_agent_tty(self):
        from code_puppy.tools import common

        with (
            patch.object(
                common, "_stdin_supports_interactive_approval", return_value=True
            ),
            patch("code_puppy.tools.subagent_context.is_subagent", return_value=False),
        ):
            assert common.can_prompt_user() is True


# --------------------------------------------------------------------------- #
# #2 / #3 — destructive guard behaviour
# --------------------------------------------------------------------------- #
class TestDestructiveGuard:
    @pytest.mark.anyio
    async def test_non_interactive_hard_blocks(self):
        from code_puppy.plugins.destructive_command_guard import register_callbacks as g

        with (
            patch("code_puppy.tools.common.can_prompt_user", return_value=False),
            patch.object(g, "emit_warning"),
        ):
            result = await g.destructive_command_guard_callback(None, "rm -rf /")
        assert result is not None and result["blocked"] is True

    @pytest.mark.anyio
    async def test_interactive_non_yolo_defers_no_double_prompt(self):
        """Non-yolo interactive: warn, return None (built-in gate prompts once)."""
        from code_puppy.plugins.destructive_command_guard import register_callbacks as g

        prompt_mock = AsyncMock()
        with (
            patch("code_puppy.tools.common.can_prompt_user", return_value=True),
            patch.object(g, "get_yolo_mode", return_value=False),
            patch.object(g, "_prompt_user_approval", prompt_mock),
            patch.object(g, "emit_warning") as warn,
        ):
            result = await g.destructive_command_guard_callback(None, "rm -rf /")
        assert result is None
        prompt_mock.assert_not_called()  # no second prompt
        warn.assert_called_once()

    @pytest.mark.anyio
    async def test_interactive_yolo_prompts(self):
        from code_puppy.plugins.destructive_command_guard import register_callbacks as g

        prompt_mock = AsyncMock(return_value=None)
        with (
            patch("code_puppy.tools.common.can_prompt_user", return_value=True),
            patch.object(g, "get_yolo_mode", return_value=True),
            patch.object(g, "_prompt_user_approval", prompt_mock),
        ):
            result = await g.destructive_command_guard_callback(None, "rm -rf /")
        assert result is None
        prompt_mock.assert_awaited_once()

    @pytest.mark.anyio
    async def test_safe_command_passes(self):
        from code_puppy.plugins.destructive_command_guard import register_callbacks as g

        assert await g.destructive_command_guard_callback(None, "ls -la") is None


# --------------------------------------------------------------------------- #
# #5 — protected-path file policy
# --------------------------------------------------------------------------- #
class TestProtectedPaths:
    def test_defaults_match_sensitive_files(self):
        from code_puppy.plugins.file_permission_handler.register_callbacks import (
            is_protected_path,
        )

        assert is_protected_path("/proj/.env") is True
        assert is_protected_path("/proj/config/.env.production") is True
        assert is_protected_path("/home/u/.ssh/id_rsa") is True
        assert is_protected_path("/proj/server.pem") is True
        assert is_protected_path("/proj/src/main.py") is False

    def test_protected_path_skips_yolo_autoapprove(self):
        """Even in yolo mode a protected path must not auto-approve; with no TTY
        it falls through to get_user_approval which fails closed."""
        from code_puppy.plugins.file_permission_handler import register_callbacks as fp

        with (
            patch.object(fp, "get_yolo_mode", return_value=True),
            patch.object(fp, "is_protected_path", return_value=True),
            patch.object(
                fp, "get_user_approval", return_value=(False, None)
            ) as approval,
        ):
            confirmed, _ = fp.prompt_for_file_permission("/proj/.env", "write to")
        assert confirmed is False
        approval.assert_called_once()

    def test_unprotected_path_yolo_autoapproves(self):
        from code_puppy.plugins.file_permission_handler import register_callbacks as fp

        with (
            patch.object(fp, "get_yolo_mode", return_value=True),
            patch.object(fp, "is_protected_path", return_value=False),
            patch.object(fp, "get_user_approval") as approval,
        ):
            confirmed, _ = fp.prompt_for_file_permission("/proj/main.py", "write to")
        assert confirmed is True
        approval.assert_not_called()


# --------------------------------------------------------------------------- #
# #4 — session approval memory
# --------------------------------------------------------------------------- #
class TestSessionApprovalMemory:
    @pytest.mark.anyio
    async def test_remembered_command_skips_prompt(self):
        from code_puppy.tools import command_runner as cr

        cr.clear_session_approved_commands()

        approval = AsyncMock(return_value=(True, None))
        exec_mock = AsyncMock(return_value=MagicMock())

        stdin = MagicMock()
        stdin.isatty.return_value = True
        with (
            patch(
                "code_puppy.callbacks.on_run_shell_command",
                AsyncMock(return_value=[]),
            ),
            patch("code_puppy.config.get_yolo_mode", return_value=False),
            patch.object(cr, "is_subagent", return_value=False),
            patch.object(cr.sys, "stdin", stdin),
            patch.object(cr, "get_user_approval_async", approval),
            patch("code_puppy.tools.common.consume_remember_choice", return_value=True),
            patch.object(cr, "_execute_shell_command", exec_mock),
        ):
            # First call: prompt happens, user picks "remember".
            await cr.run_shell_command(MagicMock(), "echo hi", cwd="/tmp")
            assert approval.await_count == 1
            # Second identical call: no prompt — served from the session allowlist.
            await cr.run_shell_command(MagicMock(), "echo hi", cwd="/tmp")
            assert approval.await_count == 1

        assert (
            cr._session_approval_key("echo hi", "/tmp") in cr._SESSION_APPROVED_COMMANDS
        )
        cr.clear_session_approved_commands()

    @pytest.mark.anyio
    async def test_not_remembered_prompts_each_time(self):
        from code_puppy.tools import command_runner as cr

        cr.clear_session_approved_commands()

        approval = AsyncMock(return_value=(True, None))
        exec_mock = AsyncMock(return_value=MagicMock())

        stdin = MagicMock()
        stdin.isatty.return_value = True
        with (
            patch(
                "code_puppy.callbacks.on_run_shell_command",
                AsyncMock(return_value=[]),
            ),
            patch("code_puppy.config.get_yolo_mode", return_value=False),
            patch.object(cr, "is_subagent", return_value=False),
            patch.object(cr.sys, "stdin", stdin),
            patch.object(cr, "get_user_approval_async", approval),
            patch(
                "code_puppy.tools.common.consume_remember_choice", return_value=False
            ),
            patch.object(cr, "_execute_shell_command", exec_mock),
        ):
            await cr.run_shell_command(MagicMock(), "echo hi", cwd="/tmp")
            await cr.run_shell_command(MagicMock(), "echo hi", cwd="/tmp")
            assert approval.await_count == 2
        cr.clear_session_approved_commands()
