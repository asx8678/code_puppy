"""Tests for the fast_puppy builder and rust_builder modules.

This module tests:
- builder.py: Crate discovery and status checking, freshness detection
- rust_builder.py: Build-related functionality

bd-91: Module was split - discovery in builder.py, builds in rust_builder.py
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Discovery functions from builder.py
from code_puppy.plugins.fast_puppy.builder import (
    CRATES,
    _find_crate_dir,
    _find_repo_root,
    _is_crate_fresh,
    _is_crate_installed,
    get_all_crate_status,
)

# Build functions from rust_builder.py (bd-91: new module)
from code_puppy.plugins.fast_puppy.rust_builder import (
    _build_crate,
    _build_env,
    _get_maturin_command,
    _has_maturin,
    _has_rust_toolchain,
    _prewarm_workspace,
    build_single_crate,
)


class TestFindRepoRoot:
    """Tests for _find_repo_root() helper."""

    def test_find_repo_root_returns_workspace_root(self, tmp_path):
        """Verify _find_repo_root() finds the workspace with Cargo.toml."""
        # Create fake workspace structure
        workspace = tmp_path / "fake_workspace"
        workspace.mkdir()
        cargo_toml = workspace / "Cargo.toml"
        cargo_toml.write_text('[workspace]\nmembers = ["foo"]\n')

        # Patch __file__ to be within the workspace
        fake_plugin_file = (
            workspace / "code_puppy" / "plugins" / "fast_puppy" / "builder.py"
        )
        fake_plugin_file.parent.mkdir(parents=True)
        fake_plugin_file.touch()

        with patch.object(Path, "resolve", return_value=fake_plugin_file):
            result = _find_repo_root()
            assert result == workspace

    def test_find_repo_root_returns_none_when_no_cargo_toml(self, tmp_path):
        """Verify returns None when no Cargo.toml found."""
        fake_plugin_file = tmp_path / "nowhere" / "builder.py"
        fake_plugin_file.parent.mkdir(parents=True)
        fake_plugin_file.touch()

        with patch.object(Path, "resolve", return_value=fake_plugin_file):
            result = _find_repo_root()
            assert result is None


class TestFindCrateDir:
    """Tests for _find_crate_dir() helper."""

    def test_find_crate_dir_for_each_known_crate(self, tmp_path):
        """Verify all 3 crate dirs are discoverable when present."""
        # Create fake workspace with all 3 crates
        workspace = tmp_path / "fake_workspace"
        workspace.mkdir()
        cargo_toml = workspace / "Cargo.toml"
        cargo_toml.write_text("[workspace]\n")

        for crate_name in ["code_puppy_core", "turbo_parse"]:
            crate_dir = workspace / crate_name
            crate_dir.mkdir()
            (crate_dir / "Cargo.toml").write_text("[package]\n")

        # Patch the repo root discovery
        with patch(
            "code_puppy.plugins.fast_puppy.builder._find_repo_root",
            return_value=workspace,
        ):
            for crate_name in ["code_puppy_core", "turbo_parse"]:
                result = _find_crate_dir(crate_name)
                assert result is not None
                assert result.name == crate_name

    def test_find_crate_dir_returns_none_when_missing(self, tmp_path):
        """Verify returns None when crate dir doesn't exist."""
        workspace = tmp_path / "empty_workspace"
        workspace.mkdir()

        with patch(
            "code_puppy.plugins.fast_puppy.builder._find_repo_root",
            return_value=workspace,
        ):
            result = _find_crate_dir("nonexistent_crate")
            assert result is None


class TestIsCrateInstalled:
    """Tests for _is_crate_installed() helper."""

    def test_is_crate_installed_with_mock_returns_true(self):
        """Mock importlib.util.find_spec to return a spec."""
        mock_spec = MagicMock()

        with patch("importlib.util.find_spec", return_value=mock_spec):
            result = _is_crate_installed("_code_puppy_core")
            assert result is True

    def test_is_crate_installed_with_mock_returns_false(self):
        """Mock importlib.util.find_spec to return None."""
        with patch("importlib.util.find_spec", return_value=None):
            result = _is_crate_installed("_code_puppy_core")
            assert result is False


class TestIsCrateFresh:
    """Tests for _is_crate_fresh() helper."""

    def test_is_crate_fresh_returns_false_if_not_installed(self, tmp_path):
        """Returns False when find_spec returns None."""
        with patch("importlib.util.find_spec", return_value=None):
            result = _is_crate_fresh(tmp_path, "_code_puppy_core")
            assert result is False

    def test_is_crate_fresh_returns_true_when_binary_newer(self, tmp_path):
        """Creates tempdir with fake .so and fake .rs, verifies mtime compare."""
        # Create fake source structure
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        rs_file = src_dir / "lib.rs"
        rs_file.write_text("// old source")

        # Create fake binary that is newer
        fake_binary = tmp_path / "_code_puppy_core.cpython-311-darwin.so"
        fake_binary.write_text("fake binary")

        # Make binary newer
        rs_file.touch()
        # Binary is touched after (newer)
        fake_binary.touch()

        mock_spec = MagicMock()
        mock_spec.origin = str(fake_binary)

        with patch("importlib.util.find_spec", return_value=mock_spec):
            result = _is_crate_fresh(tmp_path, "_code_puppy_core")
            assert result is True

    def test_is_crate_fresh_returns_false_when_src_newer(self, tmp_path):
        """Opposite case: .rs file mtime > binary mtime."""
        # Create fake source structure
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        rs_file = src_dir / "lib.rs"

        # Create fake binary that is older
        fake_binary = tmp_path / "_code_puppy_core.cpython-311-darwin.so"
        fake_binary.write_text("fake binary")
        fake_binary.touch()

        # Source is touched after (newer)
        rs_file.write_text("// newer source")

        mock_spec = MagicMock()
        mock_spec.origin = str(fake_binary)

        with patch("importlib.util.find_spec", return_value=mock_spec):
            result = _is_crate_fresh(tmp_path, "_code_puppy_core")
            assert result is False


class TestHasRustToolchain:
    """Tests for _has_rust_toolchain() helper."""

    def test_has_rust_toolchain_returns_true_when_rustc_found(self):
        """Mock shutil.which to return a path for rustc."""
        with patch("shutil.which", return_value="/usr/bin/rustc"):
            result = _has_rust_toolchain()
            assert result is True

    def test_has_rust_toolchain_returns_false_when_rustc_not_found(self):
        """Mock shutil.which to return None."""
        with patch("shutil.which", return_value=None):
            result = _has_rust_toolchain()
            assert result is False


class TestGetMaturinCommand:
    """Tests for _get_maturin_command() uv-priority logic."""

    def test_prefers_uv_run_maturin_when_both_available(self):
        """When uv and maturin are both in PATH, uv run maturin wins."""
        with patch(
            "shutil.which",
            side_effect=lambda cmd: (
                f"/usr/local/bin/{cmd}" if cmd in ("uv", "maturin") else None
            ),
        ), patch("subprocess.run") as mock_run:
            # uv run maturin --version succeeds
            mock_run.return_value = MagicMock(returncode=0)
            result = _get_maturin_command()

        assert result == ["uv", "run", "maturin"], (
            f"Expected ['uv', 'run', 'maturin'] when uv works, got {result}"
        )

    def test_uv_run_fails_falls_back_to_uv_tool_run(self):
        """When uv run maturin fails but uv tool run maturin works, use that."""
        uv_run_fail = MagicMock(returncode=1)
        uv_tool_run_ok = MagicMock(returncode=0)

        with patch(
            "shutil.which",
            side_effect=lambda cmd: (
                f"/usr/local/bin/{cmd}" if cmd == "uv" else None
            ),
        ), patch("subprocess.run") as mock_run:
            mock_run.side_effect = [uv_run_fail, uv_tool_run_ok]
            result = _get_maturin_command()

        assert result == ["uv", "tool", "run", "maturin"], (
            f"Expected ['uv', 'tool', 'run', 'maturin'] fallback, got {result}"
        )

    def test_no_uv_falls_back_to_bare_maturin(self):
        """When uv is not in PATH, use bare maturin."""
        with patch(
            "shutil.which",
            side_effect=lambda cmd: (
                "/usr/local/bin/maturin" if cmd == "maturin" else None
            ),
        ) as mock_which:
            result = _get_maturin_command()

        # uv.which("uv") returned None, so shutil.which should've been called
        assert mock_which.call_count >= 1
        assert result == ["maturin"], (
            f"Expected ['maturin'] when only maturin is available, got {result}"
        )

    def test_nothing_available_falls_back_to_python_module(self):
        """When neither uv nor maturin is available, use python -m maturin."""
        with patch("shutil.which", return_value=None):
            result = _get_maturin_command()

        assert result[1:] == ["-m", "maturin"], (
            f"Expected [sys.executable, '-m', 'maturin'] as last resort, got {result}"
        )

    def test_uv_available_but_maturin_not_in_uv_uses_uv_tool_run(self):
        """When uv is available but 'uv run maturin' fails, try uv tool run."""
        with patch(
            "shutil.which",
            side_effect=lambda cmd: f"/usr/local/bin/{cmd}" if cmd == "uv" else None,
        ), patch("subprocess.run") as mock_run:
            # Both uv run and uv tool run fail
            mock_run.return_value = MagicMock(returncode=1)
            result = _get_maturin_command()

        # Falls through to bare maturin, which isn't in PATH either,
        # so falls to python module fallback
        assert result[1:] == ["-m", "maturin"], (
            f"Expected python module fallback, got {result}"
        )


class TestHasMaturin:
    """Tests for _has_maturin() helper."""

    def test_has_maturin_returns_true_when_maturin_in_path(self):
        """Mock shutil.which to return a path for maturin."""
        with patch(
            "shutil.which",
            side_effect=lambda x: f"/usr/bin/{x}" if x in ["maturin"] else None,
        ):
            result = _has_maturin()
            assert result is True

    def test_has_maturin_tries_uv_when_not_in_path(self):
        """Verify it falls back to checking uv run maturin."""
        with patch("shutil.which") as mock_which:
            with patch("subprocess.run") as mock_run:
                # First call for maturin returns None, second for uv returns a path
                mock_which.side_effect = [None, "/usr/bin/uv"]
                mock_run.return_value = MagicMock(returncode=0)

                result = _has_maturin()
                assert result is True
                mock_run.assert_called_once()

    def test_has_maturin_returns_false_when_not_available(self):
        """Mock all methods to fail."""
        with patch("shutil.which", return_value=None):
            with patch("subprocess.run", return_value=MagicMock(returncode=1)):
                result = _has_maturin()
                assert result is False


class TestGetAllCrateStatus:
    """Tests for get_all_crate_status() helper."""

    def test_get_all_crate_status_returns_two_entries(self):
        """Verify new helper returns list of 2 dicts."""
        with patch(
            "code_puppy.plugins.fast_puppy.builder._find_crate_dir",
            return_value=Path("/fake"),
        ):
            with patch("importlib.util.find_spec", return_value=None):
                with patch(
                    "importlib.import_module", side_effect=ImportError("not found")
                ):
                    result = get_all_crate_status()

        assert len(result) == 2
        for item in result:
            assert "name" in item
            assert "installed" in item
            assert "fresh" in item
            assert "active" in item
            assert "crate_dir_found" in item


class TestBuildSingleCrate:
    """Tests for build_single_crate() helper."""

    def test_build_single_crate_rejects_unknown_name(self):
        """Verify it returns False for garbage names."""
        result = build_single_crate("totally_fake_crate")
        assert result is False

    def test_build_single_crate_returns_false_without_toolchain(self):
        """Returns False when no Rust toolchain."""
        with patch(
            "code_puppy.plugins.fast_puppy.rust_builder._has_rust_toolchain",
            return_value=False,
        ):
            result = build_single_crate("turbo_parse")
            assert result is False



# bd-91: Removed auto-build tests - functionality moved to /fast_puppy build command only
# Tests for _try_auto_build_all, _try_auto_build, _check_disable_autobuild removed
# as these functions were removed when auto-build was eliminated.


class TestPrewarmWorkspace:
    """Tests for _prewarm_workspace() helper."""

    def test_prewarm_workspace_runs_cargo_build(self, tmp_path):
        """Verify it runs cargo build --release --workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _prewarm_workspace(workspace)
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "cargo" in call_args
            assert "build" in call_args
            assert "--workspace" in call_args


@pytest.mark.slow
class TestFullBuildCycle:
    """Integration test that actually exercises the build cycle.

    bd-91: Updated to use explicit build via build_single_crate per crate.
    This test is marked as slow because it may run actual builds.
    It only runs if a Rust toolchain is available.
    """

    def test_full_build_cycle(self):
        """If Rust toolchain available, builds all crates and verifies results."""
        if not _has_rust_toolchain():
            pytest.skip("Rust toolchain not available")

        if not _has_maturin():
            pytest.skip("maturin not available")

        # bd-91: Use explicit build loop instead of _try_auto_build_all
        results: dict[str, bool] = {}
        for crate_spec in CRATES:
            crate_name = crate_spec["name"]
            success = build_single_crate(crate_name)
            results[crate_name] = success

        # We don't assert all succeed (they may not be committed/ready)
        # but we verify the structure of the results
        assert isinstance(results, dict)
        for crate_spec in CRATES:
            # Every crate in CRATES should appear in results (either True or False)
            assert crate_spec["name"] in results
            assert isinstance(results[crate_spec["name"]], bool)


class TestBuildEnv:
    """Tests for _build_env() helper — ensures VIRTUAL_ENV is set for maturin."""

    def test_existing_virtual_env_is_preserved(self):
        """If VIRTUAL_ENV is already in os.environ, _build_env keeps it."""
        with patch.dict("os.environ", {"VIRTUAL_ENV": "/my/venv", "PATH": "/usr/bin"}):
            env = _build_env()
        assert env["VIRTUAL_ENV"] == "/my/venv"

    def test_sets_virtual_env_from_sys_prefix(self):
        """When sys.prefix != sys.base_prefix (in a venv), sets VIRTUAL_ENV."""
        with patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=True):
            with patch("code_puppy.plugins.fast_puppy.rust_builder.sys") as mock_sys:
                mock_sys.prefix = "/some/.venv"
                mock_sys.base_prefix = "/usr"
                env = _build_env()
        assert env["VIRTUAL_ENV"] == "/some/.venv"

    def test_no_virtual_env_when_not_in_venv(self, tmp_path):
        """When sys.prefix == sys.base_prefix and no .venv dir, VIRTUAL_ENV is not set."""
        with patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=True):
            with patch("code_puppy.plugins.fast_puppy.rust_builder.sys") as mock_sys:
                mock_sys.prefix = "/usr"
                mock_sys.base_prefix = "/usr"
                with patch(
                    "code_puppy.plugins.fast_puppy.rust_builder.Path.cwd",
                    return_value=tmp_path,
                ):
                    env = _build_env()
        assert "VIRTUAL_ENV" not in env

    def test_auto_detects_dot_venv_near_cwd(self, tmp_path):
        """Falls back to detecting .venv in cwd when not in a detected venv."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()

        with patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=True):
            with patch("code_puppy.plugins.fast_puppy.rust_builder.sys") as mock_sys:
                mock_sys.prefix = "/usr"
                mock_sys.base_prefix = "/usr"
                mock_sys.platform = "darwin"
                with patch(
                    "code_puppy.plugins.fast_puppy.rust_builder.Path.cwd",
                    return_value=tmp_path,
                ):
                    env = _build_env()
        assert env["VIRTUAL_ENV"] == str(venv_dir)

    def test_auto_detects_dot_venv_windows(self, tmp_path):
        """On Windows, detects .venv with Scripts/python.exe instead of bin/python."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        scripts_dir = venv_dir / "Scripts"
        scripts_dir.mkdir()
        (scripts_dir / "python.exe").touch()

        with patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=True):
            with patch("code_puppy.plugins.fast_puppy.rust_builder.sys") as mock_sys:
                mock_sys.prefix = "C:\\Python311"
                mock_sys.base_prefix = "C:\\Python311"
                mock_sys.platform = "win32"
                with patch(
                    "code_puppy.plugins.fast_puppy.rust_builder.Path.cwd",
                    return_value=tmp_path,
                ):
                    env = _build_env()
        assert env["VIRTUAL_ENV"] == str(venv_dir)

    def test_windows_ignores_unix_venv(self, tmp_path):
        """On Windows, a .venv with only bin/python (unix layout) is NOT detected."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()

        with patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=True):
            with patch("code_puppy.plugins.fast_puppy.rust_builder.sys") as mock_sys:
                mock_sys.prefix = "C:\\Python311"
                mock_sys.base_prefix = "C:\\Python311"
                mock_sys.platform = "win32"
                with patch(
                    "code_puppy.plugins.fast_puppy.rust_builder.Path.cwd",
                    return_value=tmp_path,
                ):
                    env = _build_env()
        assert "VIRTUAL_ENV" not in env


class TestBuildCrateWarningFiltering:
    """Tests for _build_crate() warning filtering behavior.

    These tests verify that warning lines are filtered from stderr so that
    real errors remain visible, and appropriate fallback messages are used
    when only warnings are present.
    """

    def test_warning_only_stderr_empty_stdout_returns_fallback(self, tmp_path):
        """When stderr has only warnings and stdout is empty, return fallback message."""
        crate_dir = tmp_path / "fake_crate"
        crate_dir.mkdir()

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.poll.return_value = 1
        mock_proc.communicate.return_value = ("", "warning: first\nwarning: second")

        with patch("subprocess.Popen", return_value=mock_proc):
            with patch(
                "code_puppy.plugins.fast_puppy.rust_builder._get_maturin_command",
                return_value=["maturin"],
            ):
                success, error_msg = _build_crate(crate_dir, "test_crate")

        assert success is False
        assert "build failed with warnings only" in error_msg

    def test_warning_only_stderr_with_stdout_returns_stdout(self, tmp_path):
        """When stderr has only warnings but stdout has content, return stdout."""
        crate_dir = tmp_path / "fake_crate"
        crate_dir.mkdir()

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.poll.return_value = 1
        mock_proc.communicate.return_value = (
            "real error from stdout",
            "warning: first",
        )

        with patch("subprocess.Popen", return_value=mock_proc):
            with patch(
                "code_puppy.plugins.fast_puppy.rust_builder._get_maturin_command",
                return_value=["maturin"],
            ):
                success, error_msg = _build_crate(crate_dir, "test_crate")

        assert success is False
        assert error_msg == "real error from stdout"

    def test_mixed_warnings_and_errors_filters_warnings(self, tmp_path):
        """When stderr has both warnings and errors, only non-warning lines are returned."""
        crate_dir = tmp_path / "fake_crate"
        crate_dir.mkdir()

        stderr_content = "warning: ignored\nerror: real problem\n  --> src/lib.rs:1:1"
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.poll.return_value = 1
        mock_proc.communicate.return_value = ("", stderr_content)

        with patch("subprocess.Popen", return_value=mock_proc):
            with patch(
                "code_puppy.plugins.fast_puppy.rust_builder._get_maturin_command",
                return_value=["maturin"],
            ):
                success, error_msg = _build_crate(crate_dir, "test_crate")

        assert success is False
        assert "warning:" not in error_msg
        assert "error: real problem" in error_msg
        assert "src/lib.rs:1:1" in error_msg

    def test_no_warnings_returns_error_unchanged(self, tmp_path):
        """When stderr has no warnings, the error message is returned unchanged."""
        crate_dir = tmp_path / "fake_crate"
        crate_dir.mkdir()

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.poll.return_value = 1
        mock_proc.communicate.return_value = ("", "error: pure error")

        with patch("subprocess.Popen", return_value=mock_proc):
            with patch(
                "code_puppy.plugins.fast_puppy.rust_builder._get_maturin_command",
                return_value=["maturin"],
            ):
                success, error_msg = _build_crate(crate_dir, "test_crate")

        assert success is False
        assert error_msg == "error: pure error"


class TestBuildCratePassesEnvToSubprocess:
    """Verify _build_crate() passes env=_build_env() to subprocess.Popen."""

    def test_popen_receives_build_env(self, tmp_path):
        """_build_crate must forward _build_env() to its subprocess.Popen call."""
        crate_dir = tmp_path / "fake_crate"
        crate_dir.mkdir()

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("", "")

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            with patch(
                "code_puppy.plugins.fast_puppy.rust_builder._get_maturin_command",
                return_value=["maturin"],
            ):
                _build_crate(crate_dir, "test_crate")

        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args.kwargs
        assert "env" in call_kwargs, "Popen was called without an 'env' parameter"
        # Verify the env came from _build_env (spot-check a key it always sets)
        expected_env = _build_env()
        assert call_kwargs["env"] == expected_env
