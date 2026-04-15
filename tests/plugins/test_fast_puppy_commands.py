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
)


class TestCustomHelp:
    """Tests for _custom_help() function."""

    def test_custom_help_returns_expected_commands(self):
        """Verify _custom_help returns the expected command tuples."""
        result = _custom_help()

        # Check we have 6 commands (bd-92: cleaned up legacy commands)
        assert len(result) == 6

        # Check each command format
        commands = [cmd for cmd, desc in result]
        assert "fast_puppy" in commands
        assert "fast_puppy build [--all|name]" in commands
        assert "fast_puppy status" in commands
        assert "fast_puppy enable [cap]" in commands
        assert "fast_puppy disable [cap]" in commands
        assert "fast_puppy profile [name]" in commands

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
                    # bd-91: _try_auto_build_all removed - now calls build_single_crate per crate
                    with patch(
                        "code_puppy.plugins.fast_puppy.register_callbacks.build_single_crate",
                        return_value=True,
                    ) as mock_build_single:
                        result = _handle_fast_puppy("/fast_puppy build", "fast_puppy")

        assert result is True
        # bd-91: Should be called once per crate (2 crates: code_puppy_core, turbo_parse)
        assert mock_build_single.call_count == 2
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
                    # bd-91: _try_auto_build_all removed - now calls build_single_crate per crate
                    with patch(
                        "code_puppy.plugins.fast_puppy.register_callbacks.build_single_crate",
                        return_value=True,
                    ) as mock_build_single:
                        result = _handle_fast_puppy("/fast_puppy build --all", "fast_puppy")

        assert result is True
        # bd-91: Should be called once per crate (2 crates: code_puppy_core, turbo_parse)
        assert mock_build_single.call_count == 2

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
        """/fast_puppy build code_puppy_core emits restart notice (bd-91: no runtime reload)."""
        emit_calls = []

        def mock_emit(msg):
            emit_calls.append(msg)

        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info", side_effect=mock_emit):
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._has_rust_toolchain",
                return_value=True,
            ):
                with patch(
                    "code_puppy.plugins.fast_puppy.register_callbacks.build_single_crate",
                    return_value=True,
                ):
                    result = _handle_fast_puppy("/fast_puppy build code_puppy_core", "fast_puppy")

        assert result is True
        # bd-91: No runtime reload - should emit restart notice
        all_output = " ".join([str(call) for call in emit_calls])
        assert "built successfully" in all_output.lower()
        assert "restart" in all_output.lower()

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

    def test_fast_puppy_no_args_shows_default_view(self):
        """Bare /fast_puppy should show default profile view."""
        with patch("code_puppy.plugins.fast_puppy.register_callbacks.emit_info") as mock_emit:
            with patch(
                "code_puppy.plugins.fast_puppy.register_callbacks._handle_default_view",
                return_value="Profile: elixir_first",
            ):
                result = _handle_fast_puppy("/fast_puppy", "fast_puppy")

        assert result is True
        # Should have emitted the default view
        mock_emit.assert_called_once()
        call_args = mock_emit.call_args[0][0]
        assert "Profile" in call_args or "elixir_first" in call_args


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
        # bd-92: _emit_startup_banner format: "🐕⚡ Fast Puppy: elixir_first profile | Elixir ✅"
        assert "Elixir" in all_output or "🐕" in all_output or "⚡" in all_output

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


class TestOnStartupRespectsUserPreference:
    """Regression tests for C2 - capability-based preferences."""

    def test_on_startup_emits_elixir_banner_when_elixir_available(self):
        """When Elixir is available, show Elixir banner."""
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
                        # bd-92: _emit_startup_banner shows Elixir status
                        all_output = " ".join([str(call) for call in mock_emit.call_args_list])
                        assert "Elixir" in all_output or "elixir_first" in all_output

    def test_on_startup_emits_elixir_or_python_banner(self):
        """On startup, show profile banner with backend status."""
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
                        # bd-92: _emit_startup_banner shows profile and backend
                        all_output = " ".join([str(call) for call in mock_emit.call_args_list])
                        # Should show either Elixir active or Python fallback
                        assert "Elixir" in all_output or "Python fallback" in all_output or "🐕" in all_output
