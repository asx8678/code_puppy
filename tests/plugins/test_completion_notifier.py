"""Tests for the completion_notifier plugin."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch


def _import_plugin() -> ModuleType:
    mod_name = "code_puppy.plugins.completion_notifier.register_callbacks"
    sys.modules.pop(mod_name, None)
    return importlib.import_module(mod_name)


def _make_run_context(parent_run_id: str | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.parent_run_id = parent_run_id
    return ctx


class TestCustomHelp:
    def test_help_returns_notify_entry(self) -> None:
        mod = _import_plugin()
        entries = dict(mod._custom_help())
        assert "notify" in entries

    def test_help_is_list_of_tuples(self) -> None:
        mod = _import_plugin()
        for item in mod._custom_help():
            assert isinstance(item, tuple)
            assert len(item) == 2


class TestModeHelpers:
    def test_valid_modes_accepted(self) -> None:
        mod = _import_plugin()
        for mode in ("off", "bell", "system"):
            with patch("code_puppy.config.set_value") as sv:
                mod._set_mode(mode)
                sv.assert_called_once_with(mod._CONFIG_KEY, mode)

    def test_get_mode_defaults_to_off(self) -> None:
        mod = _import_plugin()
        with patch("code_puppy.config.get_value", return_value=None):
            assert mod._get_mode() == "off"

    def test_get_mode_normalises_case(self) -> None:
        mod = _import_plugin()
        with patch("code_puppy.config.get_value", return_value="BeLL "):
            assert mod._get_mode() == "bell"

    def test_get_mode_rejects_invalid(self) -> None:
        mod = _import_plugin()
        with patch("code_puppy.config.get_value", return_value="yolo"):
            assert mod._get_mode() == "off"


class TestBellEmission:
    def test_bell_writes_bel_to_stderr(self) -> None:
        mod = _import_plugin()
        mock_stderr = MagicMock()
        with patch("code_puppy.plugins.completion_notifier.register_callbacks.sys") as mock_sys:
            mock_sys.stderr = mock_stderr
            mod._emit_bell()
            mock_stderr.write.assert_called_once_with("\a")
            mock_stderr.flush.assert_called_once()

    def test_bell_does_not_crash_on_io_error(self) -> None:
        mod = _import_plugin()
        with patch("code_puppy.plugins.completion_notifier.register_callbacks.sys") as mock_sys:
            mock_sys.stderr.write.side_effect = OSError("boom")
            mod._emit_bell()


class TestOffNoop:
    def test_notify_does_nothing_when_off(self) -> None:
        mod = _import_plugin()
        with (
            patch.object(mod, "_get_mode", return_value="off"),
            patch.object(mod, "_emit_bell") as bell_mock,
            patch.object(mod, "_play_system_sound") as sys_mock,
        ):
            mod._notify()
            bell_mock.assert_not_called()
            sys_mock.assert_not_called()


class TestBellMode:
    def test_notify_bell_calls_emit_bell(self) -> None:
        mod = _import_plugin()
        with (
            patch.object(mod, "_emit_bell") as bell_mock,
            patch.object(mod, "_play_system_sound") as sys_mock,
        ):
            mod._notify("bell")
            bell_mock.assert_called_once()
            sys_mock.assert_not_called()


class TestSystemModeFallback:
    def test_system_falls_back_to_bell_on_import_error(self) -> None:
        mod = _import_plugin()
        with (
            patch("code_puppy.plugins.completion_notifier.register_callbacks.platform") as plat,
            patch("code_puppy.plugins.completion_notifier.register_callbacks.subprocess") as sp,
            patch.object(mod, "_emit_bell") as bell_mock,
        ):
            plat.system.return_value = "Linux"
            sp.Popen.side_effect = FileNotFoundError("no paplay")
            mod._play_system_sound()
            bell_mock.assert_called_once()

    def test_system_calls_afplay_on_macos(self) -> None:
        mod = _import_plugin()
        with (
            patch("code_puppy.plugins.completion_notifier.register_callbacks.platform") as plat,
            patch("code_puppy.plugins.completion_notifier.register_callbacks.subprocess") as sp,
            patch.object(mod, "_emit_bell") as bell_mock,
        ):
            plat.system.return_value = "Darwin"
            mod._play_system_sound()
            sp.Popen.assert_called_once()
            assert sp.Popen.call_args[0][0][0] == "afplay"
            bell_mock.assert_not_called()

    def test_system_falls_back_when_osx_afplay_fails(self) -> None:
        mod = _import_plugin()
        with (
            patch("code_puppy.plugins.completion_notifier.register_callbacks.platform") as plat,
            patch("code_puppy.plugins.completion_notifier.register_callbacks.subprocess") as sp,
            patch.object(mod, "_emit_bell") as bell_mock,
        ):
            plat.system.return_value = "Darwin"
            sp.Popen.side_effect = OSError("afplay gone")
            mod._play_system_sound()
            bell_mock.assert_called_once()


class TestTopLevelOnly:
    def test_notifies_when_no_run_context(self) -> None:
        mod = _import_plugin()
        with patch.object(mod, "_notify") as notify_mock:
            mod._on_agent_run_end("a", "m", run_context=None)
            notify_mock.assert_called_once()

    def test_notifies_when_parent_run_id_is_none(self) -> None:
        mod = _import_plugin()
        ctx = _make_run_context(parent_run_id=None)
        with patch.object(mod, "_notify") as notify_mock:
            mod._on_agent_run_end("a", "m", run_context=ctx)
            notify_mock.assert_called_once()

    def test_suppresses_when_child_run(self) -> None:
        mod = _import_plugin()
        ctx = _make_run_context(parent_run_id="parent-123")
        with patch.object(mod, "_notify") as notify_mock:
            mod._on_agent_run_end("a", "m", run_context=ctx)
            notify_mock.assert_not_called()

    def test_never_crashes_even_with_bad_run_context(self) -> None:
        mod = _import_plugin()
        mod._on_agent_run_end("a", "m", run_context="not-a-context")


class TestNotifyTestCommand:
    def test_test_subcommand_calls_notify(self) -> None:
        mod = _import_plugin()
        with (
            patch("code_puppy.messaging.emit_info"),
            patch.object(mod, "_get_mode", return_value="bell"),
            patch.object(mod, "_notify") as notify_mock,
        ):
            result = mod._handle_custom_command("/notify test", "notify")
            assert result is True
            notify_mock.assert_called_once()

    def test_status_subcommand(self) -> None:
        mod = _import_plugin()
        with (
            patch("code_puppy.messaging.emit_info") as emit_mock,
            patch.object(mod, "_get_mode", return_value="bell"),
        ):
            result = mod._handle_custom_command("/notify status", "notify")
            assert result is True
            emit_mock.assert_called_with("Completion notification mode: bell")

    def test_set_mode_subcommands(self) -> None:
        mod = _import_plugin()
        for mode in ("off", "bell", "system"):
            with (
                patch("code_puppy.messaging.emit_info"),
                patch.object(mod, "_set_mode") as sm,
            ):
                result = mod._handle_custom_command(f"/notify {mode}", "notify")
                assert result is True
                sm.assert_called_once_with(mode)

    def test_unknown_subcommand_shows_message(self) -> None:
        mod = _import_plugin()
        with patch("code_puppy.messaging.emit_info") as emit_mock:
            result = mod._handle_custom_command("/notify yolo", "notify")
            assert result is True
            assert "Unknown" in emit_mock.call_args[0][0]

    def test_non_notify_command_returns_none(self) -> None:
        mod = _import_plugin()
        assert mod._handle_custom_command("/pop", "pop") is None


class TestRunEndBothWays:
    def test_notifies_on_success(self) -> None:
        mod = _import_plugin()
        with patch.object(mod, "_notify") as notify_mock:
            mod._on_agent_run_end("a", "m", success=True)
            notify_mock.assert_called_once()

    def test_notifies_on_failure(self) -> None:
        mod = _import_plugin()
        with patch.object(mod, "_notify") as notify_mock:
            mod._on_agent_run_end("a", "m", success=False, error=RuntimeError("boom"))
            notify_mock.assert_called_once()
class TestDispatcherPath:
    """Verify run_context flows through the real callbacks dispatcher.

    These tests call callbacks.on_agent_run_end (the real dispatcher)
    rather than calling _on_agent_run_end directly, so they exercise
    the full _trigger_callbacks -> callback chain.
    """

    def _register_plugin_callback(self, mod):
        """Re-register the plugin callback for the current test."""
        from code_puppy import callbacks as cb
        cb.clear_callbacks("agent_run_end")
        cb.register_callback("agent_run_end", mod._on_agent_run_end)

    def test_top_level_run_triggers_notification(self):
        """A top-level run (no parent_run_id) should trigger notification."""
        import asyncio
        from code_puppy import callbacks as cb
        from code_puppy.run_context import RunContext

        mod = _import_plugin()
        self._register_plugin_callback(mod)

        ctx = RunContext(
            run_id="root-1", component_type="agent", component_name="test"
        )
        with patch.object(mod, "_notify") as notify_mock:
            asyncio.run(
                cb.on_agent_run_end(
                    "test-agent",
                    "test-model",
                    run_context=ctx,
                )
            )
            notify_mock.assert_called_once()

    def test_child_run_suppresses_notification(self):
        """A child run (has parent_run_id) should NOT trigger notification."""
        import asyncio
        from code_puppy import callbacks as cb
        from code_puppy.run_context import RunContext

        mod = _import_plugin()
        self._register_plugin_callback(mod)

        parent = RunContext(
            run_id="root-1", component_type="agent", component_name="test"
        )
        child = RunContext.create_child(parent, "tool", "some_tool")
        assert child.parent_run_id is not None

        with patch.object(mod, "_notify") as notify_mock:
            asyncio.run(
                cb.on_agent_run_end(
                    "test-agent",
                    "test-model",
                    run_context=child,
                )
            )
            notify_mock.assert_not_called()

    def test_backward_compat_kwargs_callback(self):
        """Callbacks using *args/**kwargs still receive run_context safely."""
        import asyncio
        from code_puppy import callbacks as cb
        from code_puppy.run_context import RunContext

        received = {}

        def legacy_cb(agent_name, model_name, *args, **kwargs):
            # run_context is the last positional arg forwarded by the dispatcher
            received["args_count"] = len(args)
            received["agent_name"] = agent_name
            received["received_all_args"] = len(args) == 6  # session_id..ctx

        cb.clear_callbacks("agent_run_end")
        cb.register_callback("agent_run_end", legacy_cb)

        ctx = RunContext(run_id="r1", component_type="agent", component_name="t")
        asyncio.run(cb.on_agent_run_end("a", "m", run_context=ctx))

        assert received["agent_name"] == "a"
        assert received["received_all_args"] is True

    def teardown_method(self):
        from code_puppy import callbacks as cb
        cb.clear_callbacks("agent_run_end")


class TestNotifyTestOffUX:
    """When mode is off, /notify test should still emit a bell and explain."""

    def test_test_when_off_emits_bell_and_explains(self):
        mod = _import_plugin()
        with (
            patch("code_puppy.messaging.emit_info") as emit_mock,
            patch.object(mod, "_get_mode", return_value="off"),
            patch.object(mod, "_emit_bell") as bell_mock,
            patch.object(mod, "_notify") as notify_mock,
        ):
            result = mod._handle_custom_command("/notify test", "notify")
            assert result is True
            bell_mock.assert_called_once()
            notify_mock.assert_not_called()
            msg = emit_mock.call_args[0][0]
            assert "off" in msg.lower()

    def test_test_when_bell_calls_notify_normally(self):
        mod = _import_plugin()
        with (
            patch("code_puppy.messaging.emit_info"),
            patch.object(mod, "_get_mode", return_value="bell"),
            patch.object(mod, "_notify") as notify_mock,
        ):
            result = mod._handle_custom_command("/notify test", "notify")
            assert result is True
            notify_mock.assert_called_once()
