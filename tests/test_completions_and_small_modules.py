"""Tests for small modules coverage.

Covers missed lines in:
- model_switching.py
- markdown_patches.py
- error_logging.py
- motd.py
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── model_switching ─────────────────────────────────────────────────────


class TestModelSwitching:
    """Cover lines 14-15, 37-38, 44, 62-63."""

    def test_get_effective_agent_model_success(self):
        from code_puppy.model_switching import _get_effective_agent_model

        agent = MagicMock()
        agent.get_model_name.return_value = "gpt-4"
        assert _get_effective_agent_model(agent) == "gpt-4"

    def test_get_effective_agent_model_exception(self):
        from code_puppy.model_switching import _get_effective_agent_model

        agent = MagicMock()
        agent.get_model_name.side_effect = Exception("fail")
        assert _get_effective_agent_model(agent) is None

    def _run(self, model_name, agent=None):
        """Helper to call set_model_and_reload_agent with proper patches."""
        from code_puppy.model_switching import set_model_and_reload_agent

        warns = []
        infos = []

        def fake_warn(msg):
            warns.append(msg)

        def fake_info(msg):
            infos.append(msg)

        with patch("code_puppy.model_switching.set_model_name"):
            with patch("code_puppy.messaging.emit_warning", fake_warn):
                with patch("code_puppy.messaging.emit_info", fake_info):
                    with patch(
                        "code_puppy.agents.get_current_agent", return_value=agent
                    ):
                        set_model_and_reload_agent(model_name)

        return warns, infos

    def test_no_active_agent(self):
        warns, _ = self._run("model-x", agent=None)
        assert any("no active agent" in w.lower() for w in warns)

    def test_refresh_config_called(self):
        agent = MagicMock()
        agent.get_model_name.return_value = "model-x"
        self._run("model-x", agent=agent)
        agent.refresh_config.assert_called_once()
        agent.reload_code_generation_agent.assert_called_once()

    def test_refresh_config_exception_nonfatal(self):
        agent = MagicMock()
        agent.refresh_config.side_effect = Exception("oops")
        agent.get_model_name.return_value = "model-x"
        self._run("model-x", agent=agent)
        agent.reload_code_generation_agent.assert_called_once()

    def test_reload_exception(self):
        agent = MagicMock()
        agent.reload_code_generation_agent.side_effect = Exception("reload fail")
        agent.get_model_name.return_value = "model-x"
        warns, _ = self._run("model-x", agent=agent)
        assert any("reload failed" in w for w in warns)

    def test_pinned_model_warning(self):
        agent = MagicMock()
        agent.get_model_name.return_value = "pinned-model"
        agent.name = "test-agent"
        warns, _ = self._run("other-model", agent=agent)
        assert any("pinned" in w for w in warns)


# ── markdown_patches ────────────────────────────────────────────────────


class TestMarkdownPatches:
    """Cover lines 35-37, 51."""

    def test_left_justified_heading_h1(self):
        import io

        from rich.console import Console
        from rich.text import Text

        from code_puppy.messaging.markdown_patches import LeftJustifiedHeading

        heading = LeftJustifiedHeading.__new__(LeftJustifiedHeading)
        heading.tag = "h1"
        heading.text = Text("Hello")

        console = Console(file=io.StringIO(), width=80)
        # Render it
        results = list(heading.__rich_console__(console, console.options))
        assert len(results) > 0  # Should yield a Panel

    def test_left_justified_heading_h2(self):
        import io

        from rich.console import Console
        from rich.text import Text

        from code_puppy.messaging.markdown_patches import LeftJustifiedHeading

        heading = LeftJustifiedHeading.__new__(LeftJustifiedHeading)
        heading.tag = "h2"
        heading.text = Text("Sub")

        console = Console(file=io.StringIO(), width=80)
        results = list(heading.__rich_console__(console, console.options))
        assert len(results) == 2  # Text("") + text

    def test_patch_idempotent(self):
        """Line 51: second call is no-op."""
        from code_puppy.messaging import markdown_patches

        markdown_patches._patched = False
        markdown_patches.patch_markdown_headings()
        assert markdown_patches._patched is True
        markdown_patches.patch_markdown_headings()  # no-op
        assert markdown_patches._patched is True


# ── error_logging ───────────────────────────────────────────────────────


class TestErrorLoggingRotation:
    """Cover lines 29-32."""

    def test_rotate_log_when_too_large(self):
        from code_puppy.error_logging import MAX_LOG_SIZE, _rotate_log_if_needed

        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "errors.log")
            rotated_file = log_file + ".1"

            # Create a file larger than MAX_LOG_SIZE
            with open(log_file, "w") as f:
                f.write("x" * (MAX_LOG_SIZE + 1))

            with patch("code_puppy.error_logging.ERROR_LOG_FILE", log_file):
                _rotate_log_if_needed()
            assert os.path.exists(rotated_file)
            assert not os.path.exists(log_file)

    def test_rotate_log_oserror_caught(self):
        """Lines 31-32: OSError in rotation is silently caught."""
        from code_puppy.error_logging import _rotate_log_if_needed

        with patch("code_puppy.error_logging.os.path.exists", return_value=True):
            with patch(
                "code_puppy.error_logging.os.path.getsize",
                side_effect=OSError("disk error"),
            ):
                _rotate_log_if_needed()  # Should not raise


# ── motd ────────────────────────────────────────────────────────────────


class TestMotdGetContent:
    """Cover lines 41-44."""

    def test_get_motd_content_from_plugin(self):
        from code_puppy.command_line.motd import get_motd_content

        with patch(
            "code_puppy.callbacks.on_get_motd",
            return_value=[("plugin msg", "v1")],
        ):
            msg, ver = get_motd_content()
        assert msg == "plugin msg"
        assert ver == "v1"

    def test_get_motd_content_fallback(self):
        from code_puppy.command_line.motd import (
            MOTD_MESSAGE,
            MOTD_VERSION,
            get_motd_content,
        )

        with patch(
            "code_puppy.callbacks.on_get_motd",
            return_value=[None],
        ):
            msg, ver = get_motd_content()
        assert msg == MOTD_MESSAGE
        assert ver == MOTD_VERSION

    def test_get_motd_content_exception_fallback(self):
        from code_puppy.command_line.motd import (
            MOTD_MESSAGE,
            MOTD_VERSION,
            get_motd_content,
        )

        with patch(
            "code_puppy.callbacks.on_get_motd",
            side_effect=Exception("boom"),
        ):
            msg, ver = get_motd_content()
        assert msg == MOTD_MESSAGE
        assert ver == MOTD_VERSION
