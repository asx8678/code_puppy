"""Tests for adaptive rendering in rich_renderer (bd code_puppy-6ig)."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

# Skip this entire module if the adaptive_render module isn't available
pytest.importorskip("code_puppy.utils.adaptive_render")

from code_puppy.messaging.rich_renderer import RichConsoleRenderer  # noqa: E402


class TestAdaptiveRendering:
    """Tests for adaptive payload rendering in RichConsoleRenderer."""

    def _make_renderer(self):
        """Create a minimal renderer instance for testing."""
        console = Console(file=StringIO(), width=120, record=True, force_terminal=False)
        # Construct using __new__ to bypass __init__ and avoid needing a bus
        renderer = RichConsoleRenderer.__new__(RichConsoleRenderer)
        renderer._console = console
        # Provide minimal mock attributes
        renderer._styles = {}  # Will use defaults
        renderer._spinners = {}
        return renderer, console

    def test_kv_dict_renders_as_table(self):
        """Test that a flat dict is rendered as a table."""
        renderer, console = self._make_renderer()
        with patch.object(renderer, "_adaptive_render_enabled", return_value=True):
            handled = renderer._render_structured_payload({"name": "alice", "age": 30})
        assert handled is True
        output = console.export_text()
        assert "name" in output
        assert "alice" in output

    def test_record_list_renders_as_table(self):
        """Test that a list of dicts is rendered as a table."""
        renderer, console = self._make_renderer()
        with patch.object(renderer, "_adaptive_render_enabled", return_value=True):
            handled = renderer._render_structured_payload(
                [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
            )
        assert handled is True

    def test_nested_dict_falls_through(self):
        """Test that nested dicts fall through to default rendering."""
        renderer, _ = self._make_renderer()
        with patch.object(renderer, "_adaptive_render_enabled", return_value=True):
            handled = renderer._render_structured_payload({"a": {"b": 1}})
        assert handled is False

    def test_python_repr_detected_and_rendered(self):
        """Test that Python dict repr is detected and rendered."""
        renderer, console = self._make_renderer()
        with patch.object(renderer, "_adaptive_render_enabled", return_value=True):
            handled = renderer._try_render_python_repr("{'name': 'bob', 'age': 25}")
        assert handled is True

    def test_python_list_repr_detected(self):
        """Test that Python list repr is detected and rendered."""
        renderer, console = self._make_renderer()
        with patch.object(renderer, "_adaptive_render_enabled", return_value=True):
            handled = renderer._try_render_python_repr("[1, 2, 3, 'four']")
        assert handled is True

    def test_non_repr_not_handled(self):
        """Test that non-repr text is not handled."""
        renderer, _ = self._make_renderer()
        with patch.object(renderer, "_adaptive_render_enabled", return_value=True):
            handled = renderer._try_render_python_repr("hello world")
        assert handled is False

    def test_delimited_table_detected(self):
        """Test that CSV-like table is detected and rendered."""
        renderer, console = self._make_renderer()
        text = "a,b,c\n1,2,3\n4,5,6\n7,8,9"
        with patch.object(renderer, "_adaptive_render_enabled", return_value=True):
            handled = renderer._try_render_embedded_table(text)
        assert handled is True

    def test_feature_flag_off_returns_false(self):
        """Test that methods return False when feature flag is disabled."""
        renderer, _ = self._make_renderer()
        with patch.object(renderer, "_adaptive_render_enabled", return_value=False):
            assert renderer._render_structured_payload({"a": 1}) is False
            assert renderer._try_render_python_repr("{'a': 1}") is False
            assert renderer._try_render_embedded_table("a,b\n1,2\n3,4") is False

    def test_adaptive_preprocess_normalizes_whitespace(self):
        """Test that escaped whitespace is normalized."""
        renderer, _ = self._make_renderer()
        with patch.object(renderer, "_adaptive_render_enabled", return_value=True):
            result = renderer._adaptive_preprocess_text("line1\\nline2")
        assert result == "line1\nline2"

    def test_adaptive_preprocess_disabled_returns_original(self):
        """Test that preprocessing returns original when disabled."""
        renderer, _ = self._make_renderer()
        with patch.object(renderer, "_adaptive_render_enabled", return_value=False):
            result = renderer._adaptive_preprocess_text("line1\\nline2")
        assert result == "line1\\nline2"


class TestCollapsibleLongText:
    """Tests for collapsible long-text functionality."""

    def _make_renderer(self):
        """Create a minimal renderer instance for testing."""
        console = Console(file=StringIO(), width=120)
        renderer = RichConsoleRenderer.__new__(RichConsoleRenderer)
        renderer._console = console
        return renderer

    def test_short_text_not_collapsed(self):
        """Test that short text is not collapsed."""
        renderer = self._make_renderer()
        short = "hello world"
        with patch.object(renderer, "_adaptive_render_enabled", return_value=True):
            display, collapsed = renderer._maybe_collapse_long_text(short)
        assert collapsed is False
        assert display == short

    def test_long_text_collapsed(self):
        """Test that long text is collapsed to a preview."""
        renderer = self._make_renderer()
        # Generate text that exceeds COLLAPSE_THRESHOLD_CHARS (2000)
        long_text = "\n".join(
            [
                f"This is a longer line with more content to ensure we exceed threshold: line {i:05d}"
                for i in range(200)
            ]
        )
        assert len(long_text) > 2000, f"Text length {len(long_text)} should exceed 2000"
        with patch.object(renderer, "_adaptive_render_enabled", return_value=True):
            display, collapsed = renderer._maybe_collapse_long_text(
                long_text, session_id="test-session", msg_id="test-msg"
            )
        assert collapsed is True
        assert "more lines" in display
        assert len(display) < len(long_text)

    def test_feature_flag_off_no_collapse(self):
        """Test that long text is not collapsed when flag is off."""
        renderer = self._make_renderer()
        long_text = "x" * 5000
        with patch.object(renderer, "_adaptive_render_enabled", return_value=False):
            display, collapsed = renderer._maybe_collapse_long_text(long_text)
        assert collapsed is False
        assert display == long_text

    def test_long_text_under_threshold_not_collapsed(self):
        """Test text exactly at threshold is not collapsed."""
        renderer = self._make_renderer()
        # Create text just under threshold
        under_threshold = "x" * (renderer._COLLAPSE_THRESHOLD_CHARS - 1)
        with patch.object(renderer, "_adaptive_render_enabled", return_value=True):
            display, collapsed = renderer._maybe_collapse_long_text(under_threshold)
        assert collapsed is False

    def test_non_string_not_collapsed(self):
        """Test that non-strings are not collapsed."""
        renderer = self._make_renderer()
        with patch.object(renderer, "_adaptive_render_enabled", return_value=True):
            display, collapsed = renderer._maybe_collapse_long_text(12345)
        assert collapsed is False


class TestAdaptiveRenderEnabled:
    """Tests for the _adaptive_render_enabled method."""

    def _make_renderer(self):
        """Create a minimal renderer instance for testing."""
        console = Console(file=StringIO(), width=120)
        renderer = RichConsoleRenderer.__new__(RichConsoleRenderer)
        renderer._console = console
        return renderer

    def test_returns_false_when_module_unavailable(self):
        """Test that method returns False when adaptive_render not available."""
        renderer = self._make_renderer()
        with patch(
            "code_puppy.messaging.rich_renderer._ADAPTIVE_RENDER_AVAILABLE", False
        ):
            assert renderer._adaptive_render_enabled() is False

    def test_uses_config_when_available(self):
        """Test that method uses config flag when available."""
        renderer = self._make_renderer()
        with patch(
            "code_puppy.messaging.rich_renderer._ADAPTIVE_RENDER_AVAILABLE", True
        ):
            with patch(
                "code_puppy.config.get_adaptive_rendering_enabled", return_value=True
            ):
                assert renderer._adaptive_render_enabled() is True

    def test_returns_true_on_config_error(self):
        """Test that method fails open (True) when config raises exception."""
        renderer = self._make_renderer()
        with patch(
            "code_puppy.messaging.rich_renderer._ADAPTIVE_RENDER_AVAILABLE", True
        ):
            with patch(
                "code_puppy.config.get_adaptive_rendering_enabled",
                side_effect=RuntimeError("boom"),
            ):
                assert renderer._adaptive_render_enabled() is True
