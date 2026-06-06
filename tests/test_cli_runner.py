"""Tests for code_puppy.cli_runner.

Consolidated single-file suite covering:
- run_prompt_with_attachments()
- execute_single_prompt()
- interactive_mode() (and its many branches)
- main() argument handling / model+agent validation / version check / uvx
- main_entry()

Plus a small set of CLI-contract smoke tests (argparse / env vars).
"""

import asyncio
import os
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_renderer():
    r = MagicMock()
    r.console = MagicMock()
    r.console.file = MagicMock()
    r.console.file.flush = MagicMock()
    r.start = MagicMock()
    r.stop = MagicMock()
    return r


def _mock_parse_result(
    prompt="hello", warnings=None, attachments=None, link_attachments=None
):
    m = MagicMock()
    m.prompt = prompt
    m.warnings = warnings or []
    m.attachments = attachments or []
    m.link_attachments = link_attachments or []
    return m


def _mock_clipboard(images=None):
    mgr = MagicMock()
    mgr.get_pending_images.return_value = images or []
    mgr.get_pending_count.return_value = len(images) if images else 0
    mgr.clear_pending = MagicMock()
    return mgr


def _apply_patches(stack, patches_dict):
    """Apply a dict of {target: value} patches using an ExitStack."""
    for target, value in patches_dict.items():
        stack.enter_context(patch(target, value))


def _base_main_patches():
    """Common patches needed for main()."""
    return {
        "code_puppy.cli_runner.find_available_port": MagicMock(return_value=8090),
        "code_puppy.cli_runner.ensure_config_exists": MagicMock(),
        "code_puppy.cli_runner.validate_cancel_agent_key": MagicMock(),
        "code_puppy.cli_runner.initialize_command_history_file": MagicMock(),
        "code_puppy.cli_runner.default_version_mismatch_behavior": MagicMock(),
        "code_puppy.cli_runner.print_truecolor_warning": MagicMock(),
        "code_puppy.cli_runner.reset_unix_terminal": MagicMock(),
        "code_puppy.cli_runner.reset_windows_terminal_ansi": MagicMock(),
        "code_puppy.cli_runner.reset_windows_terminal_full": MagicMock(),
        "code_puppy.cli_runner.callbacks": MagicMock(
            on_startup=AsyncMock(),
            on_shutdown=AsyncMock(),
            on_version_check=AsyncMock(),
            get_callbacks=MagicMock(return_value=[]),
        ),
        "code_puppy.cli_runner.plugins": MagicMock(),
        "code_puppy.config.load_api_keys_to_environment": MagicMock(),
    }


def _interactive_patches():
    return {
        "code_puppy.cli_runner.print_truecolor_warning": MagicMock(),
        "code_puppy.cli_runner.get_cancel_agent_display_name": MagicMock(
            return_value="Ctrl+C"
        ),
        "code_puppy.cli_runner.reset_windows_terminal_ansi": MagicMock(),
        "code_puppy.cli_runner.reset_windows_terminal_full": MagicMock(),
        "code_puppy.cli_runner.save_command_to_history": MagicMock(),
        "code_puppy.cli_runner.finalize_autosave_session": MagicMock(
            return_value="session-1"
        ),
        "code_puppy.cli_runner.COMMAND_HISTORY_FILE": "/tmp/test_history",
        "code_puppy.command_line.onboarding_wizard.should_show_onboarding": MagicMock(
            return_value=False
        ),
        "code_puppy.config.auto_save_session_if_enabled": MagicMock(),
    }


async def _run_main(argv, extra_patches=None, base_overrides=None, no_version=True):
    """Drive main() with a standard patch environment."""
    patches = _base_main_patches()
    if base_overrides:
        patches.update(base_overrides)
    with ExitStack() as stack:
        env = {"NO_VERSION_UPDATE": "1" if no_version else ""}
        stack.enter_context(patch.dict(os.environ, env, clear=False))
        stack.enter_context(patch("sys.argv", argv))
        stack.enter_context(
            patch(
                "code_puppy.messaging.SynchronousInteractiveRenderer",
                return_value=_mock_renderer(),
            )
        )
        stack.enter_context(
            patch(
                "code_puppy.messaging.RichConsoleRenderer",
                return_value=_mock_renderer(),
            )
        )
        stack.enter_context(
            patch("code_puppy.messaging.get_global_queue", return_value=MagicMock())
        )
        stack.enter_context(
            patch("code_puppy.messaging.get_message_bus", return_value=MagicMock())
        )
        _apply_patches(stack, patches)
        if extra_patches:
            _apply_patches(stack, extra_patches)
        from code_puppy.cli_runner import main

        await main()


async def _run_interactive(
    renderer,
    patches_dict,
    input_fn,
    agent=None,
    initial_command=None,
    extra_patches=None,
):
    """Drive interactive_mode() with patching."""
    if agent is None:
        agent = MagicMock()
        agent.get_user_prompt.return_value = "task:"

    with ExitStack() as stack:
        _apply_patches(stack, patches_dict)
        stack.enter_context(
            patch(
                "code_puppy.command_line.prompt_toolkit_completion.get_input_with_combined_completion",
                side_effect=input_fn,
            )
        )
        stack.enter_context(
            patch(
                "code_puppy.command_line.prompt_toolkit_completion.get_prompt_with_active_model",
                return_value="> ",
            )
        )
        stack.enter_context(
            patch(
                "code_puppy.agents.agent_manager.get_current_agent",
                return_value=agent,
            )
        )
        if extra_patches:
            _apply_patches(stack, extra_patches)

        from code_puppy.cli_runner import interactive_mode

        await interactive_mode(renderer, initial_command=initial_command)


def _seq_input(*values):
    """Build an async input side_effect that returns each value in turn."""
    it = iter(values)

    async def fake_input(*a, **kw):
        return next(it)

    return fake_input


# ---------------------------------------------------------------------------
# CLI-contract smoke tests (argparse / env)
# ---------------------------------------------------------------------------


def test_version_string_exists():
    from code_puppy import __version__

    assert isinstance(__version__, str)
    assert len(__version__) > 0


@pytest.mark.parametrize(
    "env_value, expected",
    [
        ("1", True),
        ("true", True),
        ("yes", True),
        ("on", True),
        ("0", False),
        ("", False),
    ],
)
def test_no_version_update_env_parsing(env_value, expected):
    with patch.dict(os.environ, {"NO_VERSION_UPDATE": env_value}, clear=False):
        is_disabled = os.getenv("NO_VERSION_UPDATE", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    assert is_disabled is expected


# ---------------------------------------------------------------------------
# run_prompt_with_attachments()
# ---------------------------------------------------------------------------


class TestRunPromptWithAttachments:
    @pytest.mark.anyio
    async def test_empty_prompt_returns_none(self):
        from code_puppy.cli_runner import run_prompt_with_attachments

        mock_agent = MagicMock()
        with (
            patch("code_puppy.cli_runner.parse_prompt_attachments") as mock_parse,
            patch("code_puppy.cli_runner.get_clipboard_manager") as mock_clip,
        ):
            mock_parse.return_value = _mock_parse_result(prompt="")
            mock_clip.return_value = _mock_clipboard()

            result, task = await run_prompt_with_attachments(mock_agent, "")
            assert result is None
            assert task is None

    @pytest.mark.anyio
    async def test_with_attachments_and_spinner(self):
        from code_puppy.cli_runner import run_prompt_with_attachments

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(return_value=mock_result)

        mock_attachment = MagicMock()
        mock_attachment.content = b"image-data"
        mock_link = MagicMock()
        mock_link.url_part = "https://example.com"

        with (
            patch("code_puppy.cli_runner.parse_prompt_attachments") as mock_parse,
            patch("code_puppy.cli_runner.get_clipboard_manager") as mock_clip,
            patch("code_puppy.agents.event_stream_handler.set_streaming_console"),
            patch("code_puppy.messaging.spinner.ConsoleSpinner") as mock_spinner,
        ):
            mock_parse.return_value = _mock_parse_result(
                prompt="do stuff",
                warnings=["warn1"],
                attachments=[mock_attachment],
                link_attachments=[mock_link],
            )
            mock_clip.return_value = _mock_clipboard([b"clip-img"])

            mock_spinner.return_value.__enter__ = MagicMock()
            mock_spinner.return_value.__exit__ = MagicMock(return_value=False)

            console = MagicMock()
            result, task = await run_prompt_with_attachments(
                mock_agent, "do stuff", spinner_console=console, use_spinner=True
            )
            assert result is mock_result

    @pytest.mark.anyio
    @pytest.mark.parametrize("use_spinner", [True, False])
    async def test_cancelled(self, use_spinner):
        from code_puppy.cli_runner import run_prompt_with_attachments

        mock_agent = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(side_effect=asyncio.CancelledError)

        with (
            patch("code_puppy.cli_runner.parse_prompt_attachments") as mock_parse,
            patch("code_puppy.cli_runner.get_clipboard_manager") as mock_clip,
            patch("code_puppy.agents.event_stream_handler.set_streaming_console"),
            patch("code_puppy.messaging.spinner.ConsoleSpinner") as mock_spinner,
        ):
            mock_parse.return_value = _mock_parse_result(prompt="do stuff")
            mock_clip.return_value = _mock_clipboard()

            mock_spinner.return_value.__enter__ = MagicMock()
            mock_spinner.return_value.__exit__ = MagicMock(return_value=False)

            console = MagicMock() if use_spinner else None
            result, task = await run_prompt_with_attachments(
                mock_agent, "do stuff", spinner_console=console, use_spinner=use_spinner
            )
            assert result is None

    @pytest.mark.anyio
    async def test_clipboard_placeholder_cleaned(self):
        from code_puppy.cli_runner import run_prompt_with_attachments

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_agent.run_with_mcp = AsyncMock(return_value=mock_result)

        with (
            patch("code_puppy.cli_runner.parse_prompt_attachments") as mock_parse,
            patch("code_puppy.cli_runner.get_clipboard_manager") as mock_clip,
            patch("code_puppy.agents.event_stream_handler.set_streaming_console"),
        ):
            mock_parse.return_value = _mock_parse_result(
                prompt="[📋 clipboard image 1] describe this"
            )
            mock_clip.return_value = _mock_clipboard([b"img"])

            result, task = await run_prompt_with_attachments(
                mock_agent, "test", use_spinner=False
            )
            call_args = mock_agent.run_with_mcp.call_args
            assert "clipboard image" not in call_args[0][0]


# ---------------------------------------------------------------------------
# execute_single_prompt()
# ---------------------------------------------------------------------------


class TestExecuteSinglePrompt:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "run_return, run_side_effect",
        [
            ("result", None),  # success: (result, task)
            ("response_obj", None),  # success: bare response with .output
            (None, None),  # run returns None
            (None, asyncio.CancelledError),  # cancelled
            (None, RuntimeError("boom")),  # generic exception
        ],
    )
    async def test_execute_single_prompt_paths(self, run_return, run_side_effect):
        from code_puppy.cli_runner import execute_single_prompt

        mock_renderer = _mock_renderer()

        if run_side_effect is not None:
            run_mock = AsyncMock(side_effect=run_side_effect)
        elif run_return == "result":
            mock_result = MagicMock()
            mock_result.output = "done!"
            run_mock = AsyncMock(return_value=(mock_result, MagicMock()))
        elif run_return == "response_obj":
            mock_response = MagicMock()
            mock_response.output = "the response"
            run_mock = AsyncMock(return_value=mock_response)
        else:
            run_mock = AsyncMock(return_value=None)

        with (
            patch("code_puppy.cli_runner.get_current_agent"),
            patch("code_puppy.cli_runner.run_prompt_with_attachments", run_mock),
            patch("code_puppy.cli_runner.emit_info"),
        ):
            await execute_single_prompt("hello", mock_renderer)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMain:
    @pytest.mark.anyio
    async def test_prompt_mode(self):
        mock_exec = AsyncMock()
        await _run_main(
            ["fast-puppy", "-p", "hello world"],
            extra_patches={"code_puppy.cli_runner.execute_single_prompt": mock_exec},
        )
        mock_exec.assert_called_once()

    @pytest.mark.anyio
    async def test_interactive_mode_default(self):
        mock_inter = AsyncMock()
        await _run_main(
            ["fast-puppy"],
            extra_patches={
                "code_puppy.cli_runner.interactive_mode": mock_inter,
                "pyfiglet.figlet_format": MagicMock(return_value="LOGO\n\n"),
            },
        )
        mock_inter.assert_called_once()

    @pytest.mark.anyio
    async def test_with_command_args(self):
        mock_inter = AsyncMock()
        await _run_main(
            ["fast-puppy", "do", "something"],
            extra_patches={
                "code_puppy.cli_runner.interactive_mode": mock_inter,
                "pyfiglet.figlet_format": MagicMock(return_value="LOGO\n\n"),
            },
        )
        assert mock_inter.call_args[1]["initial_command"] == "do something"

    @pytest.mark.anyio
    async def test_no_available_port(self):
        await _run_main(
            ["fast-puppy", "-p", "test"],
            base_overrides={
                "code_puppy.cli_runner.find_available_port": MagicMock(
                    return_value=None
                ),
            },
        )

    @pytest.mark.anyio
    async def test_keymap_error(self):
        from code_puppy.keymap import KeymapError

        with pytest.raises(SystemExit):
            await _run_main(
                ["fast-puppy", "-p", "test"],
                base_overrides={
                    "code_puppy.cli_runner.validate_cancel_agent_key": MagicMock(
                        side_effect=KeymapError("bad key")
                    ),
                },
            )

    @pytest.mark.anyio
    async def test_model_valid(self):
        mock_set = MagicMock()
        await _run_main(
            ["fast-puppy", "-m", "gpt-5", "-p", "hi"],
            extra_patches={
                "code_puppy.cli_runner.execute_single_prompt": AsyncMock(),
                "code_puppy.config.set_model_name": mock_set,
                "code_puppy.config._validate_model_exists": MagicMock(
                    return_value=True
                ),
            },
        )
        mock_set.assert_called_with("gpt-5")

    @pytest.mark.anyio
    async def test_model_invalid(self):
        mock_mf = MagicMock()
        mock_mf.load_config.return_value = {"gpt-5": {}}
        with pytest.raises(SystemExit):
            await _run_main(
                ["fast-puppy", "-m", "bad-model", "-p", "hi"],
                extra_patches={
                    "code_puppy.config.set_model_name": MagicMock(),
                    "code_puppy.config._validate_model_exists": MagicMock(
                        return_value=False
                    ),
                    "code_puppy.model_factory.ModelFactory": mock_mf,
                },
            )

    @pytest.mark.anyio
    async def test_model_validation_exception(self):
        with pytest.raises(SystemExit):
            await _run_main(
                ["fast-puppy", "-m", "bad", "-p", "hi"],
                extra_patches={
                    "code_puppy.config.set_model_name": MagicMock(),
                    "code_puppy.config._validate_model_exists": MagicMock(
                        side_effect=RuntimeError("boom")
                    ),
                },
            )

    @pytest.mark.anyio
    async def test_agent_valid(self):
        mock_set = MagicMock()
        await _run_main(
            ["fast-puppy", "-a", "fast-puppy", "-p", "hi"],
            extra_patches={
                "code_puppy.cli_runner.execute_single_prompt": AsyncMock(),
                "code_puppy.agents.agent_manager.get_available_agents": MagicMock(
                    return_value={"fast-puppy": {}}
                ),
                "code_puppy.agents.agent_manager.set_current_agent": mock_set,
            },
        )
        mock_set.assert_called_with("fast-puppy")

    @pytest.mark.anyio
    async def test_agent_invalid(self):
        with pytest.raises(SystemExit):
            await _run_main(
                ["fast-puppy", "-a", "bad-agent", "-p", "hi"],
                extra_patches={
                    "code_puppy.agents.agent_manager.get_available_agents": MagicMock(
                        return_value={"fast-puppy": {}}
                    ),
                },
            )

    @pytest.mark.anyio
    async def test_agent_exception(self):
        with pytest.raises(SystemExit):
            await _run_main(
                ["fast-puppy", "-a", "bad", "-p", "hi"],
                extra_patches={
                    "code_puppy.agents.agent_manager.get_available_agents": MagicMock(
                        side_effect=RuntimeError("boom")
                    ),
                },
            )

    @pytest.mark.anyio
    async def test_version_check_with_callbacks(self):
        cb_mock = MagicMock(
            on_startup=AsyncMock(),
            on_shutdown=AsyncMock(),
            on_version_check=AsyncMock(),
            get_callbacks=MagicMock(return_value=[lambda: None]),
        )
        await _run_main(
            ["fast-puppy", "-p", "hi"],
            no_version=False,
            base_overrides={"code_puppy.cli_runner.callbacks": cb_mock},
            extra_patches={
                "code_puppy.cli_runner.execute_single_prompt": AsyncMock(),
            },
        )
        cb_mock.on_version_check.assert_called_once()

    @pytest.mark.anyio
    async def test_version_check_no_callbacks(self):
        """Version check falls back to default_version_mismatch_behavior."""
        await _run_main(
            ["fast-puppy", "-p", "hi"],
            no_version=False,
            extra_patches={
                "code_puppy.cli_runner.execute_single_prompt": AsyncMock(),
            },
        )

    @pytest.mark.anyio
    async def test_pyfiglet_import_error(self):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "pyfiglet":
                raise ImportError("no pyfiglet")
            return real_import(name, *args, **kwargs)

        await _run_main(
            ["fast-puppy"],
            extra_patches={
                "code_puppy.cli_runner.interactive_mode": AsyncMock(),
                "builtins.__import__": fake_import,
            },
        )

    @pytest.mark.anyio
    async def test_uvx_alternate_cancel_key(self):
        """uvx should_use_alternate_cancel_key returns True branch."""
        await _run_main(
            ["fast-puppy", "-p", "hi"],
            extra_patches={
                "code_puppy.cli_runner.execute_single_prompt": AsyncMock(),
                "code_puppy.uvx_detection.should_use_alternate_cancel_key": MagicMock(
                    return_value=True
                ),
                "code_puppy.terminal_utils.disable_windows_ctrl_c": MagicMock(),
                "code_puppy.terminal_utils.set_keep_ctrl_c_disabled": MagicMock(),
                "signal.signal": MagicMock(),
            },
        )


# ---------------------------------------------------------------------------
# interactive_mode()
# ---------------------------------------------------------------------------


class TestInteractiveMode:
    @pytest.mark.anyio
    @pytest.mark.parametrize("exit_value", ["/exit", "quit"])
    async def test_exit_commands(self, exit_value):
        agent = MagicMock()
        # exercise both the "task:" prompt and the None-prompt fallback branch
        agent.get_user_prompt.return_value = None if exit_value == "quit" else "task:"
        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            AsyncMock(return_value=exit_value),
            agent=agent,
        )

    @pytest.mark.anyio
    async def test_eof_exits(self):
        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            AsyncMock(side_effect=EOFError),
        )

    @pytest.mark.anyio
    async def test_keyboard_interrupt_continues(self):
        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _kbi_then_exit(),
            extra_patches={
                "code_puppy.command_line.wiggum_state.is_wiggum_active": MagicMock(
                    return_value=False
                ),
            },
        )

    @pytest.mark.anyio
    async def test_keyboard_interrupt_notifies_continuation_plugins(self):
        mock_cancel = AsyncMock()
        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _kbi_then_exit(),
            extra_patches={
                "code_puppy.callbacks.on_interactive_turn_cancel": mock_cancel,
            },
        )
        mock_cancel.assert_awaited()

    @pytest.mark.anyio
    @pytest.mark.parametrize("clip_images", [None, [b"img"], [b"img1", b"img2"]])
    async def test_clear_command(self, clip_images):
        agent = MagicMock()
        agent.get_user_prompt.return_value = "task:"

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("/clear", "/exit"),
            agent=agent,
            extra_patches={
                "code_puppy.cli_runner.get_current_agent": MagicMock(
                    return_value=agent
                ),
                "code_puppy.cli_runner.get_clipboard_manager": MagicMock(
                    return_value=_mock_clipboard(clip_images)
                ),
            },
        )
        agent.clear_message_history.assert_called()

    @pytest.mark.anyio
    async def test_bare_clear_rewritten(self):
        """Bare `clear` (no slash) is rewritten to /clear."""
        agent = MagicMock()
        agent.get_user_prompt.return_value = "task:"

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("clear", "/exit"),
            agent=agent,
            extra_patches={
                "code_puppy.cli_runner.get_current_agent": MagicMock(
                    return_value=agent
                ),
                "code_puppy.command_line.clipboard.get_clipboard_manager": MagicMock(
                    return_value=_mock_clipboard([b"img1", b"img2"])
                ),
            },
        )

    @pytest.mark.anyio
    async def test_slash_command_handled(self):
        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("/help", "/exit"),
            extra_patches={
                "code_puppy.command_line.command_handler.handle_command": MagicMock(
                    return_value=True
                ),
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("/help")
                ),
            },
        )

    @pytest.mark.anyio
    async def test_slash_command_returns_prompt(self):
        mock_result = MagicMock(output="done")
        mock_result.all_messages.return_value = []

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("/custom", "/exit"),
            extra_patches={
                "code_puppy.command_line.command_handler.handle_command": MagicMock(
                    return_value="run this"
                ),
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("/custom")
                ),
                "code_puppy.cli_runner.run_prompt_with_attachments": AsyncMock(
                    return_value=(mock_result, MagicMock())
                ),
                "code_puppy.command_line.wiggum_state.is_wiggum_active": MagicMock(
                    return_value=False
                ),
            },
        )

    @pytest.mark.anyio
    async def test_slash_command_exception(self):
        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("/bad", "/exit"),
            extra_patches={
                "code_puppy.command_line.command_handler.handle_command": MagicMock(
                    side_effect=RuntimeError("cmd error")
                ),
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("/bad")
                ),
            },
        )

    @pytest.mark.anyio
    async def test_slash_command_returns_false(self):
        """Command returns False = not recognized, fall through to agent run."""
        mock_result = MagicMock(output="ok")
        mock_result.all_messages.return_value = []

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("/unknown", "/exit"),
            extra_patches={
                "code_puppy.command_line.command_handler.handle_command": MagicMock(
                    return_value=False
                ),
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("/unknown")
                ),
                "code_puppy.cli_runner.run_prompt_with_attachments": AsyncMock(
                    return_value=(mock_result, MagicMock())
                ),
                "code_puppy.command_line.wiggum_state.is_wiggum_active": MagicMock(
                    return_value=False
                ),
            },
        )

    @pytest.mark.anyio
    async def test_normal_prompt_execution(self):
        mock_result = MagicMock(output="done")
        mock_result.all_messages.return_value = []

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("write hello", "/exit"),
            extra_patches={
                "code_puppy.cli_runner.run_prompt_with_attachments": AsyncMock(
                    return_value=(mock_result, MagicMock())
                ),
                "code_puppy.command_line.wiggum_state.is_wiggum_active": MagicMock(
                    return_value=False
                ),
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("write hello")
                ),
            },
        )

    @pytest.mark.anyio
    async def test_prompt_returns_none_cancelled(self):
        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("write hello", "/exit"),
            extra_patches={
                "code_puppy.cli_runner.run_prompt_with_attachments": AsyncMock(
                    return_value=(None, MagicMock())
                ),
                "code_puppy.command_line.wiggum_state.is_wiggum_active": MagicMock(
                    return_value=False
                ),
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("write hello")
                ),
            },
        )

    @pytest.mark.anyio
    async def test_prompt_cancelled_notifies_continuation_plugins(self):
        mock_cancel = AsyncMock()
        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("write hello", "/exit"),
            extra_patches={
                "code_puppy.cli_runner.run_prompt_with_attachments": AsyncMock(
                    return_value=(None, MagicMock())
                ),
                "code_puppy.callbacks.on_interactive_turn_cancel": mock_cancel,
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("write hello")
                ),
            },
        )
        mock_cancel.assert_awaited()

    @pytest.mark.anyio
    async def test_prompt_exception(self):
        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("write hello", "/exit"),
            extra_patches={
                "code_puppy.cli_runner.run_prompt_with_attachments": AsyncMock(
                    side_effect=RuntimeError("agent error")
                ),
                "code_puppy.command_line.wiggum_state.is_wiggum_active": MagicMock(
                    return_value=False
                ),
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("write hello")
                ),
                "code_puppy.messaging.queue_console.get_queue_console": MagicMock(
                    return_value=MagicMock()
                ),
            },
        )

    @pytest.mark.anyio
    async def test_empty_input_skipped(self):
        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("   ", "/exit"),
            extra_patches={
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("   ")
                ),
            },
        )

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "run_kind",
        ["success", "none", "error"],
    )
    async def test_initial_command_paths(self, run_kind):
        agent = MagicMock()
        agent.get_user_prompt.return_value = "task:"

        if run_kind == "success":
            mock_result = MagicMock(output="done")
            mock_result.all_messages.return_value = []
            run_mock = AsyncMock(return_value=(mock_result, MagicMock()))
        elif run_kind == "none":
            run_mock = AsyncMock(return_value=(None, MagicMock()))
        else:
            run_mock = AsyncMock(side_effect=RuntimeError("fail"))

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            AsyncMock(return_value="/exit"),
            agent=agent,
            initial_command="do stuff",
            extra_patches={
                "code_puppy.cli_runner.get_current_agent": MagicMock(
                    return_value=agent
                ),
                "code_puppy.cli_runner.run_prompt_with_attachments": run_mock,
            },
        )

    @pytest.mark.anyio
    async def test_initial_command_awaiting_input(self):
        """is_awaiting_user_input True branch (skips spinner)."""
        agent = MagicMock()
        agent.get_user_prompt.return_value = "task:"
        mock_result = MagicMock(output="done")
        mock_result.all_messages.return_value = []

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            AsyncMock(return_value="/exit"),
            agent=agent,
            initial_command="do stuff",
            extra_patches={
                "code_puppy.cli_runner.get_current_agent": MagicMock(
                    return_value=agent
                ),
                "code_puppy.cli_runner.run_prompt_with_attachments": AsyncMock(
                    return_value=(mock_result, MagicMock())
                ),
                "code_puppy.tools.command_runner.is_awaiting_user_input": MagicMock(
                    return_value=True
                ),
            },
        )

    @pytest.mark.anyio
    async def test_initial_command_awaiting_input_import_error(self):
        """ImportError for is_awaiting_user_input -> awaiting_input False fallback."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "code_puppy.tools.command_runner":
                raise ImportError("no command_runner")
            return real_import(name, *args, **kwargs)

        agent = MagicMock()
        agent.get_user_prompt.return_value = "task:"
        mock_result = MagicMock(output="done")
        mock_result.all_messages.return_value = []

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            AsyncMock(return_value="/exit"),
            agent=agent,
            initial_command="test",
            extra_patches={
                "code_puppy.cli_runner.get_current_agent": MagicMock(
                    return_value=agent
                ),
                "code_puppy.cli_runner.run_prompt_with_attachments": AsyncMock(
                    return_value=(mock_result, MagicMock())
                ),
                "builtins.__import__": fake_import,
            },
        )

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "isatty, no_tui_env",
        [
            (False, ""),  # non-TTY -> text picker
            (True, "1"),  # TTY but CODE_PUPPY_NO_TUI=1 -> text picker
        ],
    )
    async def test_autosave_load_non_interactive_picker(self, isatty, no_tui_env):
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = isatty
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = isatty

        with patch.dict(os.environ, {"CODE_PUPPY_NO_TUI": no_tui_env}, clear=False):
            await _run_interactive(
                _mock_renderer(),
                _interactive_patches(),
                _seq_input("/autosave_load", "/exit"),
                extra_patches={
                    "code_puppy.command_line.command_handler.handle_command": MagicMock(
                        return_value="__AUTOSAVE_LOAD__"
                    ),
                    "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                        return_value=_mock_parse_result("/autosave_load")
                    ),
                    "sys.stdin": mock_stdin,
                    "sys.stdout": mock_stdout,
                    "code_puppy.session_storage.restore_autosave_interactively": AsyncMock(),
                },
            )

    @pytest.mark.anyio
    async def test_autosave_load_tty_cancelled(self):
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = True

        with patch.dict(os.environ, {"CODE_PUPPY_NO_TUI": ""}, clear=False):
            await _run_interactive(
                _mock_renderer(),
                _interactive_patches(),
                _seq_input("/autosave_load", "/exit"),
                extra_patches={
                    "code_puppy.command_line.command_handler.handle_command": MagicMock(
                        return_value="__AUTOSAVE_LOAD__"
                    ),
                    "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                        return_value=_mock_parse_result("/autosave_load")
                    ),
                    "sys.stdin": mock_stdin,
                    "sys.stdout": mock_stdout,
                    "code_puppy.command_line.autosave_menu.interactive_autosave_picker": AsyncMock(
                        return_value=None
                    ),
                },
            )

    @pytest.mark.anyio
    async def test_autosave_load_tty_success(self):
        agent = MagicMock()
        agent.get_user_prompt.return_value = "task:"
        agent.estimate_tokens_for_message.return_value = 10

        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = True

        with patch.dict(os.environ, {"CODE_PUPPY_NO_TUI": ""}, clear=False):
            await _run_interactive(
                _mock_renderer(),
                _interactive_patches(),
                _seq_input("/autosave_load", "/exit"),
                agent=agent,
                extra_patches={
                    "code_puppy.command_line.command_handler.handle_command": MagicMock(
                        return_value="__AUTOSAVE_LOAD__"
                    ),
                    "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                        return_value=_mock_parse_result("/autosave_load")
                    ),
                    "sys.stdin": mock_stdin,
                    "sys.stdout": mock_stdout,
                    "code_puppy.command_line.autosave_menu.interactive_autosave_picker": AsyncMock(
                        return_value="my-session"
                    ),
                    "code_puppy.session_storage.load_session": MagicMock(
                        return_value=[MagicMock()]
                    ),
                    "code_puppy.config.set_current_autosave_from_session_name": MagicMock(),
                    "code_puppy.command_line.autosave_menu.display_resumed_history": MagicMock(),
                    "code_puppy.cli_runner.get_current_agent": MagicMock(
                        return_value=agent
                    ),
                },
            )

    @pytest.mark.anyio
    async def test_autosave_load_exception(self):
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = False
        mock_stdout = MagicMock()
        mock_stdout.isatty.return_value = False

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("/autosave_load", "/exit"),
            extra_patches={
                "code_puppy.command_line.command_handler.handle_command": MagicMock(
                    return_value="__AUTOSAVE_LOAD__"
                ),
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("/autosave_load")
                ),
                "sys.stdin": mock_stdin,
                "sys.stdout": mock_stdout,
                "code_puppy.session_storage.restore_autosave_interactively": AsyncMock(
                    side_effect=RuntimeError("fail")
                ),
            },
        )

    @pytest.mark.anyio
    async def test_continuation_loop(self):
        mock_result = MagicMock(output="done")
        mock_result.all_messages.return_value = []

        mock_run = AsyncMock(return_value=(mock_result, MagicMock()))
        mock_turn_end = AsyncMock(
            side_effect=[[{"prompt": "repeat", "clear_context": True}], []]
        )

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("write hello", "/exit"),
            extra_patches={
                "code_puppy.cli_runner.run_prompt_with_attachments": mock_run,
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("write hello")
                ),
                "code_puppy.callbacks.on_interactive_turn_end": mock_turn_end,
            },
        )
        assert mock_run.await_count == 2

    @pytest.mark.anyio
    async def test_continuation_loop_stops_at_core_cap(self):
        mock_result = MagicMock(output="done")
        mock_result.all_messages.return_value = []

        mock_run = AsyncMock(return_value=(mock_result, MagicMock()))
        mock_turn_end = AsyncMock(return_value=[{"prompt": "repeat"}])
        mock_warning = MagicMock()

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("write hello", "/exit"),
            extra_patches={
                "code_puppy.cli_runner.run_prompt_with_attachments": mock_run,
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("write hello")
                ),
                "code_puppy.callbacks.on_interactive_turn_end": mock_turn_end,
                "code_puppy.cli_runner.get_max_continuation_iterations": MagicMock(
                    return_value=1
                ),
                "code_puppy.messaging.emit_warning": mock_warning,
            },
        )

        assert mock_run.await_count == 2
        assert mock_turn_end.await_count == 2
        assert any(
            "Continuation stopped" in str(call.args[0])
            for call in mock_warning.call_args_list
        )

    @pytest.mark.anyio
    async def test_continuation_loop_cancelled(self):
        mock_result = MagicMock(output="done")
        mock_result.all_messages.return_value = []
        run_call = 0

        async def fake_run(*a, **kw):
            nonlocal run_call
            run_call += 1
            if run_call == 1:
                return (mock_result, MagicMock())
            return (None, MagicMock())

        mock_cancel = AsyncMock()
        mock_turn_end = AsyncMock(
            side_effect=[[{"prompt": "repeat", "clear_context": True}], []]
        )

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("write hello", "/exit"),
            extra_patches={
                "code_puppy.cli_runner.run_prompt_with_attachments": fake_run,
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("write hello")
                ),
                "code_puppy.callbacks.on_interactive_turn_end": mock_turn_end,
                "code_puppy.callbacks.on_interactive_turn_cancel": mock_cancel,
            },
        )
        mock_cancel.assert_awaited()

    @pytest.mark.anyio
    async def test_continuation_no_request_stops(self):
        mock_result = MagicMock(output="done")
        mock_result.all_messages.return_value = []

        mock_turn_end = AsyncMock(return_value=[])
        mock_run = AsyncMock(return_value=(mock_result, MagicMock()))
        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("write hello", "/exit"),
            extra_patches={
                "code_puppy.cli_runner.run_prompt_with_attachments": mock_run,
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("write hello")
                ),
                "code_puppy.callbacks.on_interactive_turn_end": mock_turn_end,
            },
        )
        mock_turn_end.assert_called()
        assert mock_run.await_count == 1

    @pytest.mark.anyio
    async def test_continuation_loop_exception_is_reported_to_plugins(self):
        mock_result = MagicMock(output="done")
        mock_result.all_messages.return_value = []
        run_call = 0

        async def fake_run(*a, **kw):
            nonlocal run_call
            run_call += 1
            if run_call == 1:
                return (mock_result, MagicMock())
            raise RuntimeError("wiggum fail")

        mock_turn_end = AsyncMock(
            side_effect=[[{"prompt": "repeat", "clear_context": True}], []]
        )

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            _seq_input("write hello", "/exit"),
            extra_patches={
                "code_puppy.cli_runner.run_prompt_with_attachments": fake_run,
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("write hello")
                ),
                "code_puppy.callbacks.on_interactive_turn_end": mock_turn_end,
            },
        )
        assert mock_turn_end.call_count >= 2

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "wizard_result, extra",
        [
            (
                "chatgpt",
                {
                    "code_puppy.plugins.chatgpt_oauth.oauth_flow.run_oauth_flow": MagicMock(),
                    "code_puppy.config.set_model_name": MagicMock(),
                    "code_puppy.command_line.onboarding_wizard.run_onboarding_wizard": AsyncMock(
                        return_value="chatgpt"
                    ),
                },
            ),
            (
                "claude",
                {
                    "code_puppy.plugins.claude_code_oauth.register_callbacks._perform_authentication": MagicMock(),
                    "code_puppy.config.set_model_name": MagicMock(),
                },
            ),
            ("completed", {}),
            ("skipped", {}),
        ],
    )
    async def test_onboarding_results(self, wizard_result, extra):
        patches = _interactive_patches()
        patches["code_puppy.command_line.onboarding_wizard.should_show_onboarding"] = (
            MagicMock(return_value=True)
        )

        mock_future = MagicMock()
        mock_future.result.return_value = wizard_result
        mock_pool = MagicMock()
        mock_pool.submit.return_value = mock_future
        mock_executor = MagicMock()
        mock_executor.__enter__ = MagicMock(return_value=mock_pool)
        mock_executor.__exit__ = MagicMock(return_value=False)

        extra_patches = {
            "concurrent.futures.ThreadPoolExecutor": MagicMock(
                return_value=mock_executor
            ),
        }
        extra_patches.update(extra)

        await _run_interactive(
            _mock_renderer(),
            patches,
            AsyncMock(return_value="/exit"),
            extra_patches=extra_patches,
        )

    @pytest.mark.anyio
    async def test_onboarding_exception(self):
        patches = _interactive_patches()
        patches["code_puppy.command_line.onboarding_wizard.should_show_onboarding"] = (
            MagicMock(side_effect=RuntimeError("fail"))
        )

        await _run_interactive(
            _mock_renderer(),
            patches,
            AsyncMock(return_value="/exit"),
        )


class TestInteractiveModeRunningTask:
    """Branches where a running agent task must be cancelled on exit/EOF."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("second_input", ["/exit", EOFError])
    async def test_running_task_cancelled_on_exit(self, second_input):
        call_count = 0

        async def fake_input(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "do work"
            if second_input is EOFError:
                raise EOFError
            return second_input

        agent = MagicMock()
        agent.get_user_prompt.return_value = "task:"
        mock_result = MagicMock(output="done")
        mock_result.all_messages.return_value = []

        loop = asyncio.get_event_loop()
        mock_task = loop.create_future()  # stays pending (not done)

        async def fake_run(*a, **kw):
            return (mock_result, mock_task)

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            fake_input,
            agent=agent,
            extra_patches={
                "code_puppy.cli_runner.run_prompt_with_attachments": fake_run,
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("do work")
                ),
                "code_puppy.command_line.wiggum_state.is_wiggum_active": MagicMock(
                    return_value=False
                ),
            },
        )

    @pytest.mark.anyio
    async def test_wiggum_keyboard_interrupt(self):
        """KeyboardInterrupt raised inside the wiggum continuation loop."""
        call_count = 0

        async def fake_input(*a, **kw):
            nonlocal call_count
            call_count += 1
            return "write hello" if call_count == 1 else "/exit"

        mock_result = MagicMock(output="done")
        mock_result.all_messages.return_value = []
        run_call = 0

        async def fake_run(*a, **kw):
            nonlocal run_call
            run_call += 1
            if run_call == 1:
                return (mock_result, MagicMock())
            raise KeyboardInterrupt

        wiggum_calls = 0

        def fake_wiggum():
            nonlocal wiggum_calls
            wiggum_calls += 1
            return wiggum_calls == 1

        await _run_interactive(
            _mock_renderer(),
            _interactive_patches(),
            fake_input,
            extra_patches={
                "code_puppy.cli_runner.run_prompt_with_attachments": fake_run,
                "code_puppy.cli_runner.parse_prompt_attachments": MagicMock(
                    return_value=_mock_parse_result("write hello")
                ),
                "code_puppy.command_line.wiggum_state.is_wiggum_active": fake_wiggum,
                "code_puppy.command_line.wiggum_state.get_wiggum_prompt": MagicMock(
                    return_value="repeat"
                ),
                "code_puppy.command_line.wiggum_state.increment_wiggum_count": MagicMock(
                    return_value=1
                ),
                "code_puppy.command_line.wiggum_state.stop_wiggum": MagicMock(),
            },
        )


# ---------------------------------------------------------------------------
# main_entry()
# ---------------------------------------------------------------------------


class TestMainEntry:
    @patch("asyncio.run")
    def test_normal_exit(self, mock_run):
        from code_puppy.cli_runner import main_entry

        mock_run.return_value = None
        with patch("code_puppy.cli_runner.reset_unix_terminal"):
            result = main_entry()
        assert result is None

    @patch("asyncio.run", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt(self, mock_run):
        from code_puppy.cli_runner import main_entry

        with patch("code_puppy.cli_runner.reset_unix_terminal"):
            result = main_entry()
        assert result == 0


# ---------------------------------------------------------------------------
# Local helper that needs the test module's scope
# ---------------------------------------------------------------------------


def _kbi_then_exit():
    """Async input that raises KeyboardInterrupt once then returns /exit."""
    state = {"n": 0}

    async def fake_input(*a, **kw):
        state["n"] += 1
        if state["n"] == 1:
            raise KeyboardInterrupt
        return "/exit"

    return fake_input
