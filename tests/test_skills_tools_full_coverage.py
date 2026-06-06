"""Full coverage tests for tools/skills_tools.py."""
from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.tools.skills_tools import (
    register_activate_skill,
    register_list_or_search_skills,
)

CFG = "code_puppy.plugins.agent_skills.config"
DISC = "code_puppy.plugins.agent_skills.discovery"
META = "code_puppy.plugins.agent_skills.metadata"


def _register_and_get(register_func):
    """Register tool on a mock agent and capture the inner function."""
    agent = MagicMock()
    captured = {}

    def tool_decorator(f):
        captured["fn"] = f
        return f

    agent.tool = tool_decorator
    register_func(agent)
    return captured["fn"]


def _make_skill(name="test", has_skill_md=True, path="/path"):
    skill = MagicMock()
    skill.name = name
    skill.has_skill_md = has_skill_md
    skill.path = path
    return skill


def _make_meta(name="test", description="A test skill", tags=None):
    meta = MagicMock()
    meta.name = name
    meta.description = description
    meta.path = "/path"
    meta.tags = tags if tags is not None else ["testing"]
    meta.version = "1.0"
    meta.author = "me"
    return meta


@contextlib.contextmanager
def _patches(**overrides):
    """Patch the common skills config/discovery/metadata surface.

    Pass keyword overrides as (target, kwargs) to add/replace patches, where
    kwargs is a dict like {"return_value": ...} or {"side_effect": ...}.
    """
    specs = {
        "enabled": (f"{CFG}.get_skills_enabled", {"return_value": True}),
        "disabled_skills": (f"{CFG}.get_disabled_skills", {"return_value": set()}),
        "dirs": (f"{CFG}.get_skill_directories", {"return_value": []}),
        "discover": (f"{DISC}.discover_skills", {"return_value": []}),
        "bus": ("code_puppy.tools.skills_tools.get_message_bus", {}),
    }
    specs.update(overrides)
    with contextlib.ExitStack() as stack:
        for target, kwargs in specs.values():
            if target is None:
                continue
            stack.enter_context(patch(target, **kwargs))
        yield


class TestActivateSkill:
    @pytest.mark.anyio
    async def test_disabled(self):
        fn = _register_and_get(register_activate_skill)
        with _patches(enabled=(f"{CFG}.get_skills_enabled", {"return_value": False})):
            result = await fn(MagicMock(), skill_name="test")
        assert result.error is not None
        assert "disabled" in result.error

    @pytest.mark.anyio
    async def test_discovery_error(self):
        fn = _register_and_get(register_activate_skill)
        with _patches(
            dirs=(f"{CFG}.get_skill_directories", {"side_effect": Exception("boom")}),
            discover=(f"{DISC}.discover_skills", {"side_effect": Exception("boom")}),
        ):
            result = await fn(MagicMock(), skill_name="test")
        assert result.error is not None

    @pytest.mark.anyio
    async def test_skill_not_found(self):
        fn = _register_and_get(register_activate_skill)
        with _patches():
            result = await fn(MagicMock(), skill_name="nonexistent")
        assert "not found" in result.error

    @pytest.mark.anyio
    async def test_content_load_failure(self):
        fn = _register_and_get(register_activate_skill)
        with _patches(
            discover=(f"{DISC}.discover_skills", {"return_value": [_make_skill()]}),
            content=(f"{META}.load_full_skill_content", {"return_value": None}),
        ):
            result = await fn(MagicMock(), skill_name="test")
        assert "Failed to load" in result.error

    @pytest.mark.anyio
    async def test_success(self):
        fn = _register_and_get(register_activate_skill)
        with _patches(
            discover=(f"{DISC}.discover_skills", {"return_value": [_make_skill()]}),
            content=(
                f"{META}.load_full_skill_content",
                {"return_value": "# Skill content"},
            ),
            resources=(f"{META}.get_skill_resources", {"return_value": []}),
        ):
            result = await fn(MagicMock(), skill_name="test")
        assert result.error is None
        assert result.content == "# Skill content"


class TestListOrSearchSkills:
    @pytest.mark.anyio
    async def test_disabled(self):
        fn = _register_and_get(register_list_or_search_skills)
        with _patches(enabled=(f"{CFG}.get_skills_enabled", {"return_value": False})):
            result = await fn(MagicMock())
        assert result.error is not None

    @pytest.mark.anyio
    async def test_discovery_error(self):
        fn = _register_and_get(register_list_or_search_skills)
        with _patches(
            dirs=(f"{CFG}.get_skill_directories", {"side_effect": Exception("boom")}),
        ):
            result = await fn(MagicMock())
        assert result.error is not None

    @pytest.mark.anyio
    async def test_list_all(self):
        fn = _register_and_get(register_list_or_search_skills)
        with _patches(
            discover=(f"{DISC}.discover_skills", {"return_value": [_make_skill()]}),
            meta=(f"{META}.parse_skill_metadata", {"return_value": _make_meta()}),
        ):
            result = await fn(MagicMock())
        assert result.error is None
        assert result.total_count == 1

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "query,meta_kwargs,expected_count",
        [
            ("weath", {"name": "weather", "description": "Get weather", "tags": []}, 1),
            ("auth", {"description": "Handles authentication", "tags": []}, 1),
            ("database", {"tags": ["database"]}, 1),
            ("zzzzz", {"tags": []}, 0),
        ],
        ids=["match_name", "match_description", "match_tag", "no_match"],
    )
    async def test_filter_by_query(self, query, meta_kwargs, expected_count):
        fn = _register_and_get(register_list_or_search_skills)
        meta = _make_meta(**meta_kwargs)
        with _patches(
            discover=(
                f"{DISC}.discover_skills",
                {"return_value": [_make_skill(name=meta.name)]},
            ),
            meta=(f"{META}.parse_skill_metadata", {"return_value": meta}),
        ):
            result = await fn(MagicMock(), query=query)
        assert result.total_count == expected_count

    @pytest.mark.anyio
    async def test_skip_disabled_and_no_skill_md(self):
        fn = _register_and_get(register_list_or_search_skills)
        with _patches(
            disabled_skills=(
                f"{CFG}.get_disabled_skills",
                {"return_value": {"disabled_one"}},
            ),
            discover=(
                f"{DISC}.discover_skills",
                {
                    "return_value": [
                        _make_skill(name="disabled_one"),
                        _make_skill(name="no_md", has_skill_md=False),
                    ]
                },
            ),
        ):
            result = await fn(MagicMock())
        assert result.total_count == 0

    @pytest.mark.anyio
    async def test_skip_none_metadata(self):
        fn = _register_and_get(register_list_or_search_skills)
        with _patches(
            discover=(f"{DISC}.discover_skills", {"return_value": [_make_skill()]}),
            meta=(f"{META}.parse_skill_metadata", {"return_value": None}),
        ):
            result = await fn(MagicMock())
        assert result.total_count == 0
