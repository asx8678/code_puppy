"""Tests for the fast_puppy multi-crate builder module.

This module tests the builder.py module which provides:
- Crate discovery and status checking
- Freshness detection (binary vs source mtime)
- Auto-building functionality
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.plugins.fast_puppy.builder import (
    CRATES,
    _check_disable_autobuild,
    _find_crate_dir,
    _find_repo_root,
    _has_maturin,
    _has_rust_toolchain,
    _is_crate_fresh,
    _is_crate_installed,
    _prewarm_workspace,
    _reload_and_patch_crate,
    _try_auto_build,
    _try_auto_build_all,
    build_single_crate,
    get_all_crate_status,
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

        for crate_name in ["code_puppy_core", "turbo_ops", "turbo_parse"]:
            crate_dir = workspace / crate_name
            crate_dir.mkdir()
            (crate_dir / "Cargo.toml").write_text("[package]\n")

        # Patch the repo root discovery
        with patch(
            "code_puppy.plugins.fast_puppy.builder._find_repo_root",
            return_value=workspace,
        ):
            for crate_name in ["code_puppy_core", "turbo_ops", "turbo_parse"]:
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

    def test_get_all_crate_status_returns_three_entries(self):
        """Verify new helper returns list of 3 dicts."""
        with patch(
            "code_puppy.plugins.fast_puppy.builder._find_crate_dir",
            return_value=Path("/fake"),
        ):
            with patch("importlib.util.find_spec", return_value=None):
                with patch(
                    "importlib.import_module", side_effect=ImportError("not found")
                ):
                    result = get_all_crate_status()

        assert len(result) == 3
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
            "code_puppy.plugins.fast_puppy.builder._has_rust_toolchain",
            return_value=False,
        ):
            result = build_single_crate("turbo_ops")
            assert result is False

    def test_build_single_crate_success_path(self):
        """Test successful single crate build."""
        fake_crate_dir = MagicMock()

        with patch(
            "code_puppy.plugins.fast_puppy.builder._has_rust_toolchain",
            return_value=True,
        ):
            with patch(
                "code_puppy.plugins.fast_puppy.builder._has_maturin", return_value=True
            ):
                with patch(
                    "code_puppy.plugins.fast_puppy.builder._find_crate_dir",
                    return_value=fake_crate_dir,
                ):
                    with patch(
                        "code_puppy.plugins.fast_puppy.builder._build_crate",
                        return_value=(True, ""),
                    ):
                        with patch(
                            "code_puppy.plugins.fast_puppy.builder._reload_and_patch_crate",
                            return_value=True,
                        ):
                            result = build_single_crate("turbo_ops")
                            assert result is True


class TestTryAutoBuildAll:
    """Tests for _try_auto_build_all() helper."""

    def test_try_auto_build_all_respects_disable_flag(self):
        """Mocks config disable_rust_autobuild=true and verifies no build attempted."""
        with patch(
            "code_puppy.plugins.fast_puppy.builder._check_disable_autobuild",
            return_value=True,
        ):
            with patch(
                "code_puppy.plugins.fast_puppy.builder._has_rust_toolchain"
            ) as mock_has_rust:
                result = _try_auto_build_all()
                mock_has_rust.assert_not_called()
                assert result == {}

    def test_try_auto_build_all_returns_empty_without_toolchain(self):
        """Returns empty dict when no Rust toolchain."""
        with patch(
            "code_puppy.plugins.fast_puppy.builder._check_disable_autobuild",
            return_value=False,
        ):
            with patch(
                "code_puppy.plugins.fast_puppy.builder._has_rust_toolchain",
                return_value=False,
            ):
                result = _try_auto_build_all()
                assert result == {}


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


class TestReloadAndPatchCrateOld:
    """Tests for _reload_and_patch_crate() helper."""

    def test_reload_and_patch_imports_and_patches(self):
        """Verify it imports probe module and patches targets."""
        crate_spec = {
            "name": "test_crate",
            "probe": "some_module",
            "bridges": ["bridge_module"],
            "patch_targets": [
                {
                    "module": "target.module",
                    "flags": {"SOME_FLAG": "available"},
                }
            ],
        }

        with patch("importlib.util.find_spec", return_value=MagicMock()):
            with patch("importlib.import_module") as mock_import:
                mock_mod = MagicMock()
                mock_import.side_effect = [
                    mock_mod,  # First call for probe module
                    MagicMock(),  # Second call for bridge
                    MagicMock(),  # Third call for patch target
                ]

                with patch("importlib.reload"):
                    _result = _reload_and_patch_crate(crate_spec)
                    # Should succeed if import_module doesn't raise
                    mock_import.assert_called()


class TestCheckDisableAutobuild:
    """Tests for _check_disable_autobuild() helper."""

    def test_check_disable_autobuild_returns_true_when_set(self):
        """Returns True when config has disable_rust_autobuild=true."""
        with patch("code_puppy.config.get_value", return_value="true"):
            result = _check_disable_autobuild()
            assert result is True

    def test_check_disable_autobuild_returns_false_when_not_set(self):
        """Returns False when config value is not set."""
        with patch("code_puppy.config.get_value", return_value=None):
            result = _check_disable_autobuild()
            assert result is False


class TestTryAutoBuildLegacy:
    """Tests for _try_auto_build() backward compatibility."""

    def test_try_auto_build_calls_auto_build_all(self):
        """Legacy function should call _try_auto_build_all and return code_puppy_core result."""
        with patch(
            "code_puppy.plugins.fast_puppy.builder._try_auto_build_all",
            return_value={"code_puppy_core": True, "turbo_ops": False},
        ):
            result = _try_auto_build()
            assert result is True


@pytest.mark.slow
class TestFullBuildCycle:
    """Integration test that actually exercises the build cycle.

    This test is marked as slow because it may run actual builds.
    It only runs if a Rust toolchain is available.
    """

    def test_full_build_cycle(self):
        """If Rust toolchain available, runs _try_auto_build_all() and verifies all 3 modules."""
        if not _has_rust_toolchain():
            pytest.skip("Rust toolchain not available")

        if not _has_maturin():
            pytest.skip("maturin not available")

        # Run the full auto-build
        results = _try_auto_build_all()

        # We don't assert all succeed (they may not be committed/ready)
        # but we verify the structure of the results
        assert isinstance(results, dict)
        for crate_spec in CRATES:
            # Every crate in CRATES should appear in results (either True or False)
            assert crate_spec["name"] in results
            assert isinstance(results[crate_spec["name"]], bool)


class TestReloadAndPatchCrateRebind:
    """Tests for the reload+rebind logic that prevents stale function references."""

    def test_rebind_updates_stale_function_references(self, tmp_path):
        """Regression test for C1: consumer modules using 'from X import Y'
        must see the fresh Y after _reload_and_patch_crate runs.
        """
        import sys
        import types
        from unittest.mock import patch, MagicMock
        from code_puppy.plugins.fast_puppy.builder import _reload_and_patch_crate

        # Create a fake bridge module with a stub function
        fake_bridge = types.ModuleType("fake_bridge_module")
        fake_bridge.STUB_FLAG = False
        fake_bridge.do_thing = lambda: "STUB"
        sys.modules["fake_bridge_module"] = fake_bridge

        # Create a fake consumer that imports the stub function
        fake_consumer = types.ModuleType("fake_consumer_module")
        fake_consumer.STUB_FLAG = False
        fake_consumer.do_thing = fake_bridge.do_thing  # simulate 'from X import Y'
        sys.modules["fake_consumer_module"] = fake_consumer

        # Swap the bridge's implementation (simulating a rebuild)
        fake_bridge.STUB_FLAG = True
        fake_bridge.do_thing = lambda: "REAL"

        # Mock find_spec to return a spec for the probe module
        mock_spec = MagicMock()

        crate_spec = {
            "name": "fake",
            "probe": "fake_probe_module",
            "bridges": [],  # don't reload, we already swapped
            "patch_targets": [
                {
                    "module": "fake_consumer_module",
                    "flags": {"STUB_FLAG": "available"},
                    "rebind_from": "fake_bridge_module",
                    "rebind_names": ["do_thing"],
                },
            ],
        }

        try:
            with patch("importlib.util.find_spec", return_value=mock_spec):
                result = _reload_and_patch_crate(crate_spec)
            assert result is True
            assert fake_consumer.STUB_FLAG is True
            # The critical assertion: the consumer's function ref was rebound
            assert fake_consumer.do_thing() == "REAL"
        finally:
            del sys.modules["fake_bridge_module"]
            del sys.modules["fake_consumer_module"]

    def test_rebind_with_alias_map(self):
        """Rebind should support aliasing (e.g., list_files → turbo_list_files)."""
        import sys
        import types
        from unittest.mock import patch, MagicMock
        from code_puppy.plugins.fast_puppy.builder import _reload_and_patch_crate

        fake_source = types.ModuleType("fake_source_module")
        fake_source.real_name = lambda: "REAL"
        sys.modules["fake_source_module"] = fake_source

        fake_consumer = types.ModuleType("fake_aliased_consumer")
        fake_consumer.local_alias = lambda: "STUB"
        sys.modules["fake_aliased_consumer"] = fake_consumer

        # Mock find_spec to return a spec for the probe module
        mock_spec = MagicMock()

        crate_spec = {
            "name": "fake",
            "probe": "fake_probe2",
            "bridges": [],
            "patch_targets": [
                {
                    "module": "fake_aliased_consumer",
                    "flags": {},
                    "rebind_from": "fake_source_module",
                    "rebind_names": ["real_name"],
                    "rebind_as": {"real_name": "local_alias"},
                },
            ],
        }

        try:
            with patch("importlib.util.find_spec", return_value=mock_spec):
                _reload_and_patch_crate(crate_spec)
            assert fake_consumer.local_alias() == "REAL"
        finally:
            del sys.modules["fake_source_module"]
            del sys.modules["fake_aliased_consumer"]
