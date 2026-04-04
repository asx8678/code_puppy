"""Tests for the badge palette reduction to 3 semantic categories.

This test verifies the simplified banner color system:
- Agent output (steel_blue): agent_response, agent_reasoning, subagent_response, invoke_agent
- Mutations (dark_goldenrod): create_file, edit_file, replace_in_file, delete_snippet
- Tool ops (grey50): read_file, grep, directory_listing, shell_command, thinking
"""

import pytest

from code_puppy.config import DEFAULT_BANNER_COLORS, get_banner_color
from code_puppy.messaging.rich_renderer import BANNER_TIERS


class TestBadgePalette:
    """Test the simplified 3-color semantic palette."""

    def test_agent_output_banners_use_steel_blue(self):
        """Agent output category should use steel_blue."""
        agent_banners = [
            "agent_response",
            "agent_reasoning",
            "subagent_response",
            "invoke_agent",
        ]
        for banner in agent_banners:
            assert DEFAULT_BANNER_COLORS.get(banner) == "steel_blue", (
                f"{banner} should be steel_blue"
            )

    def test_mutation_banners_use_dark_goldenrod(self):
        """Mutation category should use dark_goldenrod."""
        mutation_banners = [
            "create_file",
            "edit_file",
            "replace_in_file",
            "delete_snippet",
        ]
        for banner in mutation_banners:
            assert DEFAULT_BANNER_COLORS.get(banner) == "dark_goldenrod", (
                f"{banner} should be dark_goldenrod"
            )

    def test_tool_ops_banners_use_grey50(self):
        """Tool ops category should use grey50."""
        tool_banners = [
            "read_file",
            "grep",
            "directory_listing",
            "shell_command",
            "thinking",
        ]
        for banner in tool_banners:
            assert DEFAULT_BANNER_COLORS.get(banner) == "grey50", (
                f"{banner} should be grey50"
            )

    def test_palette_has_exactly_13_banners(self):
        """The simplified palette should have exactly 13 banners."""
        assert len(DEFAULT_BANNER_COLORS) == 13, (
            f"Expected 13 banners, got {len(DEFAULT_BANNER_COLORS)}"
        )

    def test_only_three_distinct_colors_used(self):
        """Only 3 distinct colors should be used in the palette."""
        unique_colors = set(DEFAULT_BANNER_COLORS.values())
        assert len(unique_colors) == 3, (
            f"Expected 3 unique colors, got {len(unique_colors)}: {unique_colors}"
        )
        assert unique_colors == {"steel_blue", "dark_goldenrod", "grey50"}

    def test_thinking_is_in_tier_3(self):
        """Thinking banner should be in tier 3 (dimmed/minimal)."""
        assert BANNER_TIERS.get("thinking") == 3, (
            "thinking should be tier 3 (dimmed)"
        )

    def test_agent_banners_are_tier_1(self):
        """Agent output banners should be tier 1 (colored box)."""
        agent_banners = [
            "agent_response",
            "agent_reasoning",
            "subagent_response",
            "invoke_agent",
        ]
        for banner in agent_banners:
            assert BANNER_TIERS.get(banner) == 1, (
                f"{banner} should be tier 1 (colored box)"
            )

    def test_tool_ops_banners_are_tier_2_or_3(self):
        """Tool ops banners should be tier 2 or 3 (not tier 1)."""
        tool_banners = [
            "read_file",
            "grep",
            "directory_listing",
            "shell_command",
            "thinking",
        ]
        for banner in tool_banners:
            tier = BANNER_TIERS.get(banner)
            assert tier in [2, 3], (
                f"{banner} should be tier 2 or 3, got {tier}"
            )

    def test_mutation_banners_are_tier_2(self):
        """Mutation banners should be tier 2 (colored text, no box)."""
        mutation_banners = [
            "create_file",
            "edit_file",
            "replace_in_file",
        ]
        for banner in mutation_banners:
            assert BANNER_TIERS.get(banner) == 2, (
                f"{banner} should be tier 2 (colored text, no box)"
            )

    def test_get_banner_color_uses_defaults(self, monkeypatch):
        """get_banner_color should return the default color when not customized."""
        # Mock get_value to return None (no user customization)
        monkeypatch.setattr("code_puppy.config.get_value", lambda key: None)

        assert get_banner_color("agent_response") == "steel_blue"
        assert get_banner_color("create_file") == "dark_goldenrod"
        assert get_banner_color("read_file") == "grey50"
        assert get_banner_color("thinking") == "grey50"

    def test_get_banner_color_respects_user_customization(self, monkeypatch):
        """User customizations via /set should override defaults."""
        # Mock a user customization
        def mock_get_value(key):
            if key == "banner_color_agent_response":
                return "purple"
            return None

        monkeypatch.setattr("code_puppy.config.get_value", mock_get_value)

        assert get_banner_color("agent_response") == "purple"
        # Other banners still use defaults
        assert get_banner_color("create_file") == "dark_goldenrod"
