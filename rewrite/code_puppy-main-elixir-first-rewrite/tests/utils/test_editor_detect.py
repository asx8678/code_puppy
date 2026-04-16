import os
from unittest.mock import patch


from code_puppy.utils.editor_detect import (
    MAX_EDITOR_OPTS,
    detect_editors,
    pick_default_editor,
    _preferred_commands_from_env,
)


def _fake_which_factory(available: set[str]):
    """Return a function that mimics shutil.which for a given set of available commands."""
    def fake_which(cmd):
        return f"/usr/bin/{cmd}" if cmd in available else None
    return fake_which


def test_no_editors_available():
    with patch("code_puppy.utils.editor_detect._which", _fake_which_factory(set())):
        with patch.dict(os.environ, {"VISUAL": "", "EDITOR": ""}, clear=False):
            assert detect_editors() == []


def test_single_editor_detected():
    with patch("code_puppy.utils.editor_detect._which", _fake_which_factory({"nano"})):
        with patch.dict(os.environ, {"VISUAL": "", "EDITOR": ""}, clear=False):
            result = detect_editors()
    assert len(result) == 1
    assert result[0].command == "nano"


def test_visual_env_promotes_editor():
    """$VISUAL should push the named editor to the top."""
    with patch("code_puppy.utils.editor_detect._which", _fake_which_factory({"code", "vim", "nano"})):
        with patch.dict(os.environ, {"VISUAL": "vim", "EDITOR": ""}, clear=False):
            result = detect_editors()
    assert result[0].command == "vim"  # promoted to front


def test_editor_env_promotes_editor():
    with patch("code_puppy.utils.editor_detect._which", _fake_which_factory({"code", "nano"})):
        with patch.dict(os.environ, {"VISUAL": "", "EDITOR": "nano"}, clear=False):
            result = detect_editors()
    assert result[0].command == "nano"


def test_jb_suppresses_individual_jetbrains():
    """When jb is on PATH, individual IDE launchers should be hidden."""
    available = {"jb", "goland", "pycharm", "code"}
    with patch("code_puppy.utils.editor_detect._which", _fake_which_factory(available)):
        with patch.dict(os.environ, {"VISUAL": "", "EDITOR": ""}, clear=False):
            result = detect_editors()
    cmds = [c.command for c in result]
    assert "jb" in cmds
    assert "goland" not in cmds
    assert "pycharm" not in cmds
    assert "code" in cmds  # non-JetBrains editors unaffected


def test_jb_does_not_suppress_preferred_jetbrains():
    """If $VISUAL names a specific JetBrains IDE, keep it even when jb is present."""
    available = {"jb", "goland", "pycharm"}
    with patch("code_puppy.utils.editor_detect._which", _fake_which_factory(available)):
        with patch.dict(os.environ, {"VISUAL": "goland", "EDITOR": ""}, clear=False):
            result = detect_editors()
    cmds = [c.command for c in result]
    assert "goland" in cmds  # kept because preferred
    assert "pycharm" not in cmds  # still suppressed
    assert result[0].command == "goland"  # promoted


def test_cap_max_opts():
    # All 25 editors available
    all_cmds = {"code", "cursor", "zed", "nvim", "vim", "nano", "hx", "micro",
                "subl", "mate", "kak", "emacs", "kate"}
    with patch("code_puppy.utils.editor_detect._which", _fake_which_factory(all_cmds)):
        with patch.dict(os.environ, {"VISUAL": "", "EDITOR": ""}, clear=False):
            result = detect_editors()
    assert len(result) <= MAX_EDITOR_OPTS


def test_custom_editor_from_env():
    """$EDITOR naming a command not in our static table should still be added."""
    with patch("code_puppy.utils.editor_detect._which", _fake_which_factory({"myed"})):
        with patch.dict(os.environ, {"VISUAL": "", "EDITOR": "myed"}, clear=False):
            result = detect_editors()
    cmds = [c.command for c in result]
    assert "myed" in cmds


def test_pick_default_editor_returns_first():
    with patch("code_puppy.utils.editor_detect._which", _fake_which_factory({"code", "vim"})):
        with patch.dict(os.environ, {"VISUAL": "", "EDITOR": ""}, clear=False):
            default = pick_default_editor()
    assert default is not None
    assert default.command == "code"  # first in static table


def test_pick_default_editor_none_when_empty():
    with patch("code_puppy.utils.editor_detect._which", _fake_which_factory(set())):
        with patch.dict(os.environ, {"VISUAL": "", "EDITOR": ""}, clear=False):
            default = pick_default_editor()
    assert default is None


def test_preferred_commands_strips_path_and_flags():
    with patch.dict(os.environ, {"VISUAL": "/usr/local/bin/vim -Nu ~/.vimrc", "EDITOR": ""}, clear=False):
        assert _preferred_commands_from_env() == {"vim"}
