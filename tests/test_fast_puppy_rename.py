"""Tests for the code-puppy -> fast-puppy rename: config-dir migration and the
legacy agent-id alias that keeps pre-rename sessions/configs working.
"""

from __future__ import annotations

from code_puppy import config as cp_config


class TestLegacyDirFor:
    def test_dotted_home_dir(self):
        assert cp_config._legacy_dir_for("/home/u/.fast_puppy") == "/home/u/.code_puppy"

    def test_xdg_dir(self):
        assert cp_config._legacy_dir_for("/x/share/fast_puppy") == "/x/share/code_puppy"

    def test_unknown_layout_returns_empty(self):
        # A temp/test dir with an unrelated name must never map to a real legacy
        # path, so migration can't fire against it.
        assert cp_config._legacy_dir_for("/tmp/whatever") == ""


class TestMigrateLegacyConfigDirs:
    def _point_dirs_at(self, monkeypatch, path):
        for attr in ("CONFIG_DIR", "DATA_DIR", "CACHE_DIR", "STATE_DIR"):
            monkeypatch.setattr(cp_config, attr, str(path))

    def test_copies_legacy_when_new_absent(self, tmp_path, monkeypatch):
        legacy = tmp_path / ".code_puppy"
        legacy.mkdir()
        (legacy / "puppy.cfg").write_text("[puppy]\nowner = me\n")
        new = tmp_path / ".fast_puppy"  # does not exist yet
        self._point_dirs_at(monkeypatch, new)

        cp_config.migrate_legacy_config_dirs()

        assert (new / "puppy.cfg").read_text().strip().endswith("owner = me")
        # Non-destructive: the legacy dir is left in place.
        assert (legacy / "puppy.cfg").exists()

    def test_skips_when_new_already_exists(self, tmp_path, monkeypatch):
        legacy = tmp_path / ".code_puppy"
        legacy.mkdir()
        (legacy / "secret.txt").write_text("x")
        new = tmp_path / ".fast_puppy"
        new.mkdir()  # already present -> must not be overwritten
        self._point_dirs_at(monkeypatch, new)

        cp_config.migrate_legacy_config_dirs()

        assert not (new / "secret.txt").exists()

    def test_noop_when_no_legacy(self, tmp_path, monkeypatch):
        new = tmp_path / ".fast_puppy"
        self._point_dirs_at(monkeypatch, new)
        # No legacy dir exists; migration must not create the new one.
        cp_config.migrate_legacy_config_dirs()
        assert not new.exists()


class TestLegacyAgentAlias:
    def test_alias_maps_code_puppy_to_fast_puppy(self):
        from code_puppy.agents import agent_manager

        assert agent_manager._LEGACY_AGENT_ALIASES.get("code-puppy") == "fast-puppy"

    def test_builtin_agent_id_is_fast_puppy(self):
        from code_puppy.agents.agent_code_puppy import CodePuppyAgent

        assert CodePuppyAgent().name == "fast-puppy"

    def test_load_agent_resolves_legacy_id(self):
        from code_puppy.agents import agent_manager

        # A pre-rename session asking for "code-puppy" should resolve to the
        # renamed builtin agent rather than raising.
        agent = agent_manager.load_agent("code-puppy")
        assert agent.name == "fast-puppy"
