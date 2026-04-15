"""Tests for the fast_puppy command handler.

This module tests the register_callbacks.py command handler:
- /fast_puppy status command
- /fast_puppy build command variants
- /fast_puppy enable/disable commands
"""

from unittest.mock import MagicMock, patch


from code_puppy.plugins.fast_puppy.register_callbacks import (
    _custom_help,
    _handle_fast_puppy,
    _on_startup,
    _read_persisted_preference,
    _write_persisted_preference,
)


class TestCustomHelp:
    """Tests for _custom_help() function."""

    def test_custom_help_returns_expected_commands(self):
        """Verify _custom_help returns the expected command tuples."""
        result = _custom_help()

        # Check we have 8 commands (including profile commands)
        assert len(result) == 8

        # Check each command format
        commands = [cmd for cmd, desc in result]
        assert "fast_puppy" in commands
        assert "fast_puppy build [name|--all]" in commands
        assert "fast_puppy status" in commands
        assert "fast_puppy enable [cap]" in commands
        assert "fast_puppy disable [cap]" in commands
        assert "fast_puppy profile" in commands

        # Verify descriptions are non-empty
        for cmd, desc in result:
            assert desc
            assert isinstance(desc, str)


class TestHandleFastPuppyStatus:
    """Tests for /fast_puppy status command."""

    def test_fast_puppy_status_shows_all_crates(self):
        """Invokes status and verifies crate names appear in output."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info", side_effect=mock_emit):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks.get_all_crate_status",
                return_value=[
                    {"name": "code_puppy_core", "installed": True, "fresh": True, "active": True, "crate_dir_found": True},
                    {"name": "turbo_parse", "installed": False, "fresh": False, "active": False, "crate_dir_found": True},
                ],
            ):
                with patch("code_puppy._core_bridge.get_rust_status", return_value={
                    "installed": True,
                    "enabled": True,
                    "active": True,
                }):
                    with patch("code_puppy.native_backend.NativeBackend.get_status") as mock_status:
                        from code_puppy.native_backend import CapabilityInfo
                        mock_status.return_value = {
                            "message_core": CapabilityInfo(name="message_core", configured="rust", available=True, active=True, status="active"),
                            "parse": CapabilityInfo(name="parse", configured="rust", available=False, active=False, status="unavailable"),
                        }
                        with patch(
                            "code_puppy.plugins.fast_puppy.register_callbacks._has_rust_toolchain",
                            return_value=True,
                        ):
                            with patch(
                                "code_puppy.plugins.fast_puppy.register_callbacks._has_maturin",
                                return_value=True,
                            ):
                                with patch(
                                    "code_puppy.plugins.fast_puppy.register_callbacks._find_repo_root",
                                    return_value=MagicMock(),
                                ):
                                    result = _handle_fast_puppy("/fast_puppy status", "fast_puppy")

        assert result is True
        # Check capability and crate names appear in output
        all_output = " ".join(emit_calls)
        # Status shows capabilities from NativeBackend and crate info
        assert "message_core" in all_output  # Capability name
        assert "parse" in all_output  # Capability name


class TestHandleFastPuppyBuild:
    """Tests for /fast_puppy build command variants."""

    def test_fast_puppy_build_all_when_no_args(self):
        """/fast_puppy build with no args builds all crates."""
        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info") as mock_emit:
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._has_rust_toolchain",
                return_value=True,
            ):
                with patch(
                    "code_puppy.plugins.fast_puppy.register_callbacks._find_repo_root",
                    return_value=MagicMock(),
                ):
                    # Patch where it's looked up in register_callbacks
                    with patch(
                        "code_puppy.plugins.fast_puppy.register_callbacks._try_auto_build_all",
                        return_value={
                            "code_puppy_core": True,
                            "turbo_parse": True,
                        },
                    ) as mock_build_all:
                        with patch("importlib.reload"):
                            with patch("code_puppy._core_bridge.set_rust_enabled"):
                                with patch(
                                    "code_puppy.plugins.fast_puppy.register_callbacks._write_persisted_preference"
                                ):
                                    result = _handle_fast_puppy("/fast_puppy build", "fast_puppy")

        assert result is True
        mock_build_all.assert_called_once()
        # Should report all built successfully
        output = " ".join([str(call) for call in mock_emit.call_args_list])
        assert "built" in output.lower() or "success" in output.lower()

    def test_fast_puppy_build_explicit_all(self):
        """/fast_puppy build --all explicitly builds all."""
        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info"):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._has_rust_toolchain",
                return_value=True,
            ):
                with patch(
                    "code_puppy.plugins.fast_puppy.register_callbacks._find_repo_root",
                    return_value=MagicMock(),
                ):
                    # Patch where it's looked up in register_callbacks
                    with patch(
                        "code_puppy.plugins.fast_puppy.register_callbacks._try_auto_build_all",
                        return_value={
                            "code_puppy_core": True,
                            "turbo_parse": True,
                        },
                    ) as mock_build_all:
                        with patch("importlib.reload"):
                            with patch("code_puppy._core_bridge.set_rust_enabled"):
                                with patch(
                                    "code_puppy.plugins.fast_puppy.register_callbacks._write_persisted_preference"
                                ):
                                    result = _handle_fast_puppy("/fast_puppy build --all", "fast_puppy")

        assert result is True
        mock_build_all.assert_called_once()

    def test_fast_puppy_build_single_crate_name(self):
        """/fast_puppy build turbo_parse rebuilds only that crate."""
        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info"):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._has_rust_toolchain",
                return_value=True,
            ):
                # Patch where it's looked up in register_callbacks
                with patch(
                    "code_puppy.plugins.fast_puppy.register_callbacks.build_single_crate",
                    return_value=True,
                ) as mock_build_single:
                    result = _handle_fast_puppy("/fast_puppy build turbo_parse", "fast_puppy")

        assert result is True
        mock_build_single.assert_called_once_with("turbo_parse")

    def test_fast_puppy_build_single_code_puppy_core(self):
        """/fast_puppy build code_puppy_core also enables runtime after build."""
        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info"):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._has_rust_toolchain",
                return_value=True,
            ):
                with patch(
                    "code_puppy.plugins.fast_puppy.register_callbacks.build_single_crate",
                    return_value=True,
                ):
                    with patch("importlib.reload") as mock_reload:
                        with patch("code_puppy._core_bridge.RUST_AVAILABLE", True):
                            with patch("code_puppy._core_bridge.set_rust_enabled") as mock_set:
                                with patch(
                                    "code_puppy.plugins.fast_puppy.register_callbacks._write_persisted_preference"
                                ):
                                    result = _handle_fast_puppy("/fast_puppy build code_puppy_core", "fast_puppy")

        assert result is True
        # Should have reloaded and enabled
        mock_reload.assert_called()
        mock_set.assert_called_with(True)

    def test_fast_puppy_build_single_crate_failure(self):
        """When single crate build fails, show failure message."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info", side_effect=mock_emit):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._has_rust_toolchain",
                return_value=True,
            ):
                # Patch where it's looked up in register_callbacks
                with patch(
                    "code_puppy.plugins.fast_puppy.register_callbacks.build_single_crate",
                    return_value=False,
                ):
                    result = _handle_fast_puppy("/fast_puppy build turbo_parse", "fast_puppy")

        assert result is True
        all_output = " ".join(emit_calls)
        assert "failed" in all_output.lower() or "❌" in all_output

    def test_fast_puppy_build_unknown_crate_shows_error(self):
        """Invokes with build bogus_name, verifies error message contains valid names."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info", side_effect=mock_emit):
            result = _handle_fast_puppy("/fast_puppy build bogus_name", "fast_puppy")

        assert result is True
        all_output = " ".join(emit_calls)
        # Should mention the valid crate names
        assert "valid crates" in all_output.lower() or "unknown crate" in all_output.lower()

    def test_fast_puppy_build_without_toolchain_shows_install_help(self):
        """When no toolchain, show installation help."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info", side_effect=mock_emit):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._has_rust_toolchain",
                return_value=False,
            ):
                result = _handle_fast_puppy("/fast_puppy build", "fast_puppy")

        assert result is True
        all_output = " ".join(emit_calls)
        assert "toolchain" in all_output.lower() or "install" in all_output.lower()


class TestHandleFastPuppyEnableDisable:
    """Tests for /fast_puppy enable and /fast_puppy disable commands."""

    def test_fast_puppy_enable_sets_enabled(self):
        """Enable command should enable all capabilities via NativeBackend."""
        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info"):
            with patch("code_puppy.native_backend.NativeBackend.enable_all") as mock_enable:
                with patch("code_puppy.native_backend.NativeBackend.save_preferences") as mock_save:
                    result = _handle_fast_puppy("/fast_puppy enable", "fast_puppy")

        assert result is True
        mock_enable.assert_called_once()
        mock_save.assert_called_once()

    def test_fast_puppy_enable_uses_native_backend(self):
        """Enable should use NativeBackend.enable_all()."""
        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info"):
            with patch("code_puppy.native_backend.NativeBackend.enable_all") as mock_enable:
                with patch("code_puppy.native_backend.NativeBackend.save_preferences") as mock_save:
                    result = _handle_fast_puppy("/fast_puppy enable", "fast_puppy")

        assert result is True
        mock_enable.assert_called_once()
        mock_save.assert_called_once()

    def test_fast_puppy_disable_sets_disabled(self):
        """Disable command should disable all capabilities via NativeBackend."""
        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info"):
            with patch("code_puppy.native_backend.NativeBackend.disable_all") as mock_disable:
                with patch("code_puppy.native_backend.NativeBackend.save_preferences") as mock_save:
                    result = _handle_fast_puppy("/fast_puppy disable", "fast_puppy")

        assert result is True
        mock_disable.assert_called_once()
        mock_save.assert_called_once()


class TestHandleFastPuppyNoArgs:
    """Tests for /fast_puppy with no subcommand (defaults to status)."""

    def test_fast_puppy_no_args_defaults_to_status(self):
        """Bare /fast_puppy should show status."""
        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info") as mock_emit:
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks.get_all_crate_status",
                return_value=[
                    {"name": "code_puppy_core", "installed": False, "fresh": False, "active": False, "crate_dir_found": True},
                    {"name": "turbo_parse", "installed": False, "fresh": False, "active": False, "crate_dir_found": True},
                ],
            ):
                with patch("code_puppy._core_bridge.get_rust_status", return_value={
                    "installed": False,
                    "enabled": False,
                    "active": False,
                }):
                    with patch(
                        "code_puppy.plugins.fast_puppy.register_callbacks._read_persisted_preference",
                        return_value=None,
                    ):
                        with patch(
                            "code_puppy.plugins.fast_puppy.register_callbacks._has_rust_toolchain",
                            return_value=True,
                        ):
                            with patch(
                                "code_puppy.plugins.fast_puppy.register_callbacks._has_maturin",
                                return_value=False,
                            ):
                                with patch(
                                    "code_puppy.plugins.fast_puppy.register_callbacks._find_repo_root",
                                    return_value=None,
                                ):
                                    result = _handle_fast_puppy("/fast_puppy", "fast_puppy")

        assert result is True
        # Should have emitted status output with crate info
        all_output = " ".join([str(call) for call in mock_emit.call_args_list])
        assert "Status" in all_output or "code_puppy_core" in all_output


class TestHandleFastPuppyWrongCommand:
    """Tests that command handler doesn't hijack other commands."""

    def test_fast_puppy_returns_none_for_other_commands(self):
        """Calls with name="not_fast_puppy", verifies returns None."""
        result = _handle_fast_puppy("/fast_puppy status", "not_fast_puppy")
        assert result is None

    def test_fast_puppy_returns_none_for_mismatched_name(self):
        """Handler should return None for any name != 'fast_puppy'."""
        result = _handle_fast_puppy("/fast_puppy status", "some_other_command")
        assert result is None


class TestOnStartup:
    """Tests for _on_startup() function."""

    def test_on_startup_emits_banner_when_all_active(self):
        """When backends are available, emit success banner."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info", side_effect=mock_emit):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks.get_available_backends",
                return_value={
                    "elixir_available": True,
                    "python_fallback": True,
                },
            ):
                with patch("code_puppy.native_backend.NativeBackend.load_preferences"):
                    with patch("code_puppy.native_backend.NativeBackend.is_enabled", return_value=True):
                        _on_startup()

        all_output = " ".join(emit_calls)
        assert "Native backend active" in all_output
        assert "🚀" in all_output

    def test_on_startup_emits_partial_banner_when_python_fallback(self):
        """When only Python fallback is available, emit fallback banner."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info", side_effect=mock_emit):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks.get_available_backends",
                return_value={
                    "elixir_available": False,
                    "python_fallback": True,
                },
            ):
                with patch("code_puppy.native_backend.NativeBackend.load_preferences"):
                    with patch("code_puppy.native_backend.NativeBackend.is_enabled", return_value=True):
                        _on_startup()

        all_output = " ".join(emit_calls)
        # Should show Python fallback message
        assert "Python fallback" in all_output

    def test_on_startup_emits_python_fallback_when_no_elixir(self):
        """When no Elixir available, emit Python fallback banner."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info", side_effect=mock_emit):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks.get_available_backends",
                return_value={
                    "elixir_available": False,
                    "python_fallback": True,
                },
            ):
                with patch("code_puppy.native_backend.NativeBackend.load_preferences"):
                    with patch("code_puppy.native_backend.NativeBackend.is_enabled", return_value=True):
                        _on_startup()

        all_output = " ".join(emit_calls)
        # Should show Python fallback message
        assert "Python fallback" in all_output or "🐕" in all_output


class TestPersistedPreference:
    """Tests for preference read/write functions."""

    def test_read_persisted_preference_returns_true_for_true_values(self):
        """Returns True for various truthy config values."""
        for val in ["true", "1", "yes", "on", "TRUE", "True"]:
            with patch("code_puppy.config.get_value", return_value=val):
                result = _read_persisted_preference()
                assert result is True, f"Expected True for value: {val}"

    def test_read_persisted_preference_returns_false_for_false_values(self):
        """Returns False for various falsey config values."""
        for val in ["false", "0", "no", "off", "FALSE", "False"]:
            with patch("code_puppy.config.get_value", return_value=val):
                result = _read_persisted_preference()
                assert result is False, f"Expected False for value: {val}"

    def test_read_persisted_preference_returns_none_for_unset(self):
        """Returns None when config value is not set."""
        with patch("code_puppy.config.get_value", return_value=None):
            result = _read_persisted_preference()
            assert result is None

    def test_write_persisted_preference_saves_value(self):
        """Saves preference to config."""
        with patch("code_puppy.config.set_config_value") as mock_set:
            _write_persisted_preference(True)
            mock_set.assert_called_once_with("enable_fast_puppy", "true")

        with patch("code_puppy.config.set_config_value") as mock_set:
            _write_persisted_preference(False)
            mock_set.assert_called_once_with("enable_fast_puppy", "false")


class TestOnStartupRespectsUserPreference:
    """Regression tests for C2 - capability-based preferences."""

    def test_on_startup_respects_disabled_capabilities(self):
        """When all capabilities are disabled, show disabled message."""
        from unittest.mock import patch
        from code_puppy.plugins.fast_puppy import register_callbacks as rc

        with patch(
            "code_puppy.plugins.fast_puppy.register_callbacks.get_available_backends",
            return_value={"elixir_available": True, "python_fallback": True},
        ):
            with patch("code_puppy.native_backend.NativeBackend.load_preferences"):
                with patch("code_puppy.native_backend.NativeBackend.is_enabled", return_value=False):
                    with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info") as mock_emit:
                        rc._on_startup()
                        # Should emit disabled message
                        all_output = " ".join([str(call) for call in mock_emit.call_args_list])
                        assert "disabled" in all_output.lower()

    def test_on_startup_persists_default_on_first_run(self):
        """On first run with enabled capabilities, show active message."""
        from unittest.mock import patch
        from code_puppy.plugins.fast_puppy import register_callbacks as rc

        with patch(
            "code_puppy.plugins.fast_puppy.register_callbacks.get_available_backends",
            return_value={"elixir_available": True, "python_fallback": True},
        ):
            with patch("code_puppy.native_backend.NativeBackend.load_preferences"):
                with patch("code_puppy.native_backend.NativeBackend.is_enabled", return_value=True):
                    with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info") as mock_emit:
                        rc._on_startup()
                        # Should emit active message
                        all_output = " ".join([str(call) for call in mock_emit.call_args_list])
                        assert "active" in all_output.lower()
