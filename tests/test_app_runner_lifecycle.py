"""Test coverage for app_runner.py - lifecycle and integration tests.

This module covers:
- Missing branches in app_runner.py:
  - ImportError fallback for uvx_detection (lines 185-190)
  - Signal setup skip in TUI mode (line 277)
  - Bridge mode environment setup (lines 286-288)
  - DBOS cleanup at shutdown (lines 383-385)
- AppRunner integration tests
"""

import os
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_renderer():
    """Create a mock message renderer."""
    r = MagicMock()
    r.console = MagicMock()
    r.console.file = MagicMock()
    r.console.file.flush = MagicMock()
    r.start = MagicMock()
    r.stop = MagicMock()
    return r


def _base_main_patches():
    """Return common patches for AppRunner.run() tests."""
    return {
        "code_puppy.app_runner.find_available_port": MagicMock(return_value=8090),
        "code_puppy.app_runner.ensure_config_exists": MagicMock(),
        "code_puppy.app_runner.validate_cancel_agent_key": MagicMock(),
        "code_puppy.app_runner.initialize_command_history_file": MagicMock(),
        "code_puppy.app_runner.get_use_dbos": MagicMock(return_value=False),
        "code_puppy.app_runner.default_version_mismatch_behavior": MagicMock(),
        "code_puppy.cli_runner.reset_unix_terminal": MagicMock(),
        "code_puppy.app_runner.reset_windows_terminal_full": MagicMock(),
        "code_puppy.app_runner.callbacks": MagicMock(
            on_startup=AsyncMock(),
            on_shutdown=AsyncMock(),
            on_version_check=AsyncMock(),
            get_callbacks=MagicMock(return_value=[]),
        ),
        "code_puppy.config.load_api_keys_to_environment": MagicMock(),
    }


def _apply_patches(stack, patches_dict):
    """Apply a dict of patches using an ExitStack."""
    for target, value in patches_dict.items():
        stack.enter_context(patch(target, value))


class TestUVXDetectionImportError:
    """Test ImportError fallback for uvx_detection (lines 185-190)."""

    def test_uvx_detection_import_error_covered(self):
        """Test that ImportError on uvx_detection import is handled gracefully.

        This covers the 'except ImportError: pass' block in setup_signals().
        """
        import builtins
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            # Make code_puppy.uvx_detection import fail
            if name == "code_puppy.uvx_detection":
                raise ImportError("No module named 'code_puppy.uvx_detection'")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", fake_import):
            # The import inside setup_signals should fail with ImportError
            # and the except block should catch it silently
            runner.setup_signals()
            # If we get here without exception, the ImportError was handled


class TestTUIModeSkipsSignalSetup:
    """Test that TUI mode skips signal setup (line 277)."""

    @pytest.mark.anyio
    async def test_tui_mode_skips_signal_setup(self):
        """Test that signal setup is skipped when in TUI mode."""
        patches = _base_main_patches()

        # Create runner before patching class methods
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        # Mock TUI mode to be enabled
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"NO_VERSION_UPDATE": "1"}))
            stack.enter_context(patch("sys.argv", ["code-puppy", "-i"]))
            stack.enter_context(
                patch(
                    "code_puppy.tui.launcher.is_tui_enabled",
                    return_value=True,  # TUI is enabled
                )
            )
            # Mock signal setup to verify it's NOT called - patch before creating runner
            mock_setup_signals = MagicMock()
            stack.enter_context(patch.object(runner, "setup_signals", mock_setup_signals))
            stack.enter_context(
                patch(
                    "code_puppy.tui.launcher.textual_interactive_mode",
                    new_callable=AsyncMock,
                )
            )
            _apply_patches(stack, patches)

            await runner.run()

            # Signal setup should NOT be called in TUI mode
            mock_setup_signals.assert_not_called()


class TestBridgeModeEnvironment:
    """Test bridge mode environment variable setup (lines 286-288)."""

    @pytest.mark.anyio
    async def test_bridge_mode_sets_env_var(self):
        """Test that --bridge-mode sets CODE_PUPPY_BRIDGE=1."""
        patches = _base_main_patches()

        # Start with clean environment
        env_without_bridge = {k: v for k, v in os.environ.items() if k != "CODE_PUPPY_BRIDGE"}

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env_without_bridge, clear=True))
            stack.enter_context(patch.dict(os.environ, {"NO_VERSION_UPDATE": "1"}))
            stack.enter_context(patch("sys.argv", ["code-puppy", "--bridge-mode", "-p", "test"]))
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
            stack.enter_context(
                patch(
                    "code_puppy.app_runner.execute_single_prompt",
                    new_callable=AsyncMock,
                )
            )
            _apply_patches(stack, patches)

            from code_puppy.app_runner import AppRunner

            runner = AppRunner()
            await runner.run()

            # Verify CODE_PUPPY_BRIDGE was set
            assert os.environ.get("CODE_PUPPY_BRIDGE") == "1"

    @pytest.mark.anyio
    async def test_bridge_mode_preserves_existing_env_var(self):
        """Test that --bridge-mode preserves existing CODE_PUPPY_BRIDGE value."""
        patches = _base_main_patches()

        with ExitStack() as stack:
            stack.enter_context(
                patch.dict(os.environ, {"CODE_PUPPY_BRIDGE": "existing", "NO_VERSION_UPDATE": "1"})
            )
            stack.enter_context(patch("sys.argv", ["code-puppy", "--bridge-mode", "-p", "test"]))
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
            stack.enter_context(
                patch(
                    "code_puppy.app_runner.execute_single_prompt",
                    new_callable=AsyncMock,
                )
            )
            _apply_patches(stack, patches)

            from code_puppy.app_runner import AppRunner

            runner = AppRunner()
            await runner.run()

            # Verify CODE_PUPPY_BRIDGE preserves existing value
            assert os.environ.get("CODE_PUPPY_BRIDGE") == "existing"


class TestDBOSShutdownCleanup:
    """Test DBOS cleanup at shutdown (lines 383-385)."""

    @pytest.mark.anyio
    async def test_dbos_destroy_called_on_shutdown(self):
        """Test that DBOS.destroy() is called during shutdown when DBOS is enabled."""
        patches = _base_main_patches()
        patches["code_puppy.app_runner.get_use_dbos"] = MagicMock(return_value=True)

        mock_dbos_cls = MagicMock()

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"NO_VERSION_UPDATE": "1"}))
            stack.enter_context(patch("sys.argv", ["code-puppy", "-p", "test"]))
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
            stack.enter_context(
                patch(
                    "code_puppy.app_runner.execute_single_prompt",
                    new_callable=AsyncMock,
                )
            )
            stack.enter_context(patch("code_puppy.app_runner.DBOS", mock_dbos_cls))
            _apply_patches(stack, patches)

            from code_puppy.app_runner import AppRunner

            runner = AppRunner()
            await runner.run()

            # Verify DBOS.destroy() was called
            mock_dbos_cls.destroy.assert_called_once()

    @pytest.mark.anyio
    async def test_dbos_destroy_not_called_when_disabled(self):
        """Test that DBOS.destroy() is NOT called when DBOS is disabled."""
        patches = _base_main_patches()
        patches["code_puppy.app_runner.get_use_dbos"] = MagicMock(return_value=False)

        mock_dbos_cls = MagicMock()

        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"NO_VERSION_UPDATE": "1"}))
            stack.enter_context(patch("sys.argv", ["code-puppy", "-p", "test"]))
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
            stack.enter_context(
                patch(
                    "code_puppy.app_runner.execute_single_prompt",
                    new_callable=AsyncMock,
                )
            )
            stack.enter_context(patch("code_puppy.app_runner.DBOS", mock_dbos_cls))
            _apply_patches(stack, patches)

            from code_puppy.app_runner import AppRunner

            runner = AppRunner()
            await runner.run()

            # Verify DBOS.destroy() was NOT called
            mock_dbos_cls.destroy.assert_not_called()


# =============================================================================
# AppRunner Full Integration Tests
# =============================================================================


class TestAppRunnerArgumentParsing:
    """Test AppRunner.parse_args() for all argument combinations."""

    def test_parse_args_all_flags(self):
        """Test parsing all supported flags."""
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        test_cases = [
            # (argv, expected_attrs)
            (["--help"], None),  # SystemExit with code 0
            (["--version"], None),  # SystemExit with code 0
            (["-v"], None),  # SystemExit with code 0
            (["-p", "test"], {"prompt": "test", "interactive": False}),
            (["--prompt", "test"], {"prompt": "test", "interactive": False}),
            (["-i"], {"interactive": True, "prompt": None}),
            (["--interactive"], {"interactive": True, "prompt": None}),
            (["-a", "code-puppy"], {"agent": "code-puppy"}),
            (["--agent", "code-puppy"], {"agent": "code-puppy"}),
            (["-m", "gpt-5"], {"model": "gpt-5"}),
            (["--model", "gpt-5"], {"model": "gpt-5"}),
            (["--bridge-mode"], {"bridge_mode": True}),
            (["do", "something"], {"command": ["do", "something"]}),
            ([], {"interactive": False, "prompt": None}),
        ]

        for argv, expected_attrs in test_cases:
            with patch("sys.argv", ["code-puppy"] + argv):
                if expected_attrs is None:
                    # Expect SystemExit for --help and --version
                    with pytest.raises(SystemExit) as exc_info:
                        runner.parse_args()
                    assert exc_info.value.code == 0
                else:
                    args = runner.parse_args()
                    for attr, expected in expected_attrs.items():
                        assert getattr(args, attr) == expected, f"Failed for argv={argv}"


class TestAppRunnerShowLogo:
    """Test AppRunner.show_logo() behavior."""

    def test_show_logo_skipped_in_prompt_mode(self):
        """Test that logo is skipped when args.prompt is set."""
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        mock_args = MagicMock()
        mock_args.prompt = "test prompt"

        mock_console = MagicMock()

        runner.show_logo(mock_args, mock_console)

        # Logo should be skipped, no print calls
        mock_console.print.assert_not_called()

    def test_show_logo_displayed_in_interactive_mode(self):
        """Test that logo is displayed in interactive mode."""
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        mock_args = MagicMock()
        mock_args.prompt = None

        mock_console = MagicMock()

        # Patch pyfiglet at the module level where it's imported
        with patch("builtins.__import__") as mock_import:

            def import_side_effect(name, *args, **kwargs):
                if name == "pyfiglet":
                    mock_pyfiglet = MagicMock()
                    mock_pyfiglet.figlet_format.return_value = "LOGO\n\n"
                    return mock_pyfiglet
                return __builtins__["__import__"](name, *args, **kwargs)

            mock_import.side_effect = import_side_effect
            runner.show_logo(mock_args, mock_console)

        # Logo should be displayed
        mock_console.print.assert_called()

    def test_show_logo_skipped_when_prompt_set(self):
        """Test that logo display is skipped when prompt is provided."""
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        mock_args = MagicMock()
        mock_args.prompt = "some prompt"  # Prompt is set

        mock_console = MagicMock()

        # Should return early and not print anything
        runner.show_logo(mock_args, mock_console)
        mock_console.print.assert_not_called()


class TestAppRunnerSetupRenderers:
    """Test AppRunner.setup_renderers() for renderer creation."""

    def test_setup_renderers_returns_tuple(self):
        """Test that setup_renderers returns a tuple of (message_renderer, bus_renderer, display_console)."""
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        with patch("code_puppy.app_runner.build_console", return_value=MagicMock()):
            with patch("code_puppy.messaging.get_global_queue", return_value=MagicMock()):
                with patch("code_puppy.messaging.get_message_bus", return_value=MagicMock()):
                    with patch("code_puppy.messaging.SynchronousInteractiveRenderer") as mock_sync:
                        with patch("code_puppy.messaging.RichConsoleRenderer") as mock_rich:
                            mock_sync.return_value = MagicMock()
                            mock_rich.return_value = MagicMock()

                            result = runner.setup_renderers()

                            assert len(result) == 3
                            assert result[0] is not None  # message_renderer
                            assert result[1] is not None  # bus_renderer
                            assert result[2] is not None  # display_console


class TestAppRunnerLoadAPIKeys:
    """Test AppRunner.load_api_keys()."""

    def test_load_api_keys_calls_config_function(self):
        """Test that load_api_keys calls the config function."""
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        with patch("code_puppy.config.load_api_keys_to_environment") as mock_load:
            runner.load_api_keys()
            mock_load.assert_called_once()


class TestAppRunnerConfigureAgent:
    """Test AppRunner.configure_agent() with various scenarios."""

    @patch("code_puppy.config.set_model_name")
    @patch("code_puppy.config._validate_model_exists", return_value=True)
    @patch("code_puppy.messaging.emit_system_message")
    def test_configure_agent_valid_model(self, mock_emit, mock_validate, mock_set):
        """Test configure_agent with valid model."""
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        mock_args = MagicMock()
        mock_args.model = "gpt-5"
        mock_args.agent = None

        runner.configure_agent(mock_args)

        mock_set.assert_called_once_with("gpt-5")
        mock_emit.assert_called()

    @patch("code_puppy.config.set_model_name")
    @patch("code_puppy.config._validate_model_exists", return_value=False)
    @patch("code_puppy.messaging.emit_error")
    @patch("code_puppy.messaging.emit_system_message")
    @patch("code_puppy.model_factory.ModelFactory.load_config")
    def test_configure_agent_invalid_model_exits(
        self, mock_load_config, mock_emit_sys, mock_emit_err, mock_validate, mock_set
    ):
        """Test configure_agent with invalid model causes sys.exit."""
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        mock_args = MagicMock()
        mock_args.model = "invalid-model"
        mock_args.agent = None

        # Mock ModelFactory to return some available models
        mock_load_config.return_value = {"gpt-5": {}}

        with pytest.raises(SystemExit) as exc_info:
            runner.configure_agent(mock_args)

        assert exc_info.value.code == 1

    @patch("code_puppy.config.set_model_name")
    @patch("code_puppy.config._validate_model_exists", side_effect=RuntimeError("validation error"))
    @patch("code_puppy.messaging.emit_error")
    @patch("code_puppy.error_logging.log_error")
    def test_configure_agent_validation_exception(self, mock_log, mock_emit, mock_validate, mock_set):
        """Test configure_agent with exception during validation."""
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        mock_args = MagicMock()
        mock_args.model = "some-model"
        mock_args.agent = None

        with pytest.raises(SystemExit) as exc_info:
            runner.configure_agent(mock_args)

        assert exc_info.value.code == 1
        mock_log.assert_called_once()

    @patch("code_puppy.agents.agent_manager.get_available_agents", return_value={"code-puppy": {}})
    @patch("code_puppy.agents.agent_manager.set_current_agent")
    @patch("code_puppy.messaging.emit_system_message")
    def test_configure_agent_valid_agent(self, mock_emit, mock_set_agent, mock_get_agents):
        """Test configure_agent with valid agent."""
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        mock_args = MagicMock()
        mock_args.model = None
        mock_args.agent = "code-puppy"

        runner.configure_agent(mock_args)

        mock_set_agent.assert_called_once_with("code-puppy")
        mock_emit.assert_called()

    @patch("code_puppy.agents.agent_manager.get_available_agents", return_value={"code-puppy": {}})
    @patch("code_puppy.messaging.emit_error")
    @patch("code_puppy.messaging.emit_system_message")
    def test_configure_agent_invalid_agent_exits(self, mock_emit_sys, mock_emit_err, mock_get_agents):
        """Test configure_agent with invalid agent causes sys.exit."""
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        mock_args = MagicMock()
        mock_args.model = None
        mock_args.agent = "invalid-agent"

        with pytest.raises(SystemExit) as exc_info:
            runner.configure_agent(mock_args)

        assert exc_info.value.code == 1

    @patch("code_puppy.agents.agent_manager.get_available_agents", side_effect=RuntimeError("agent error"))
    @patch("code_puppy.messaging.emit_error")
    @patch("code_puppy.error_logging.log_error")
    def test_configure_agent_agent_exception(self, mock_log, mock_emit, mock_get_agents):
        """Test configure_agent with exception during agent lookup."""
        from code_puppy.app_runner import AppRunner

        runner = AppRunner()

        mock_args = MagicMock()
        mock_args.model = None
        mock_args.agent = "some-agent"

        with pytest.raises(SystemExit) as exc_info:
            runner.configure_agent(mock_args)

        assert exc_info.value.code == 1
        mock_log.assert_called_once()
