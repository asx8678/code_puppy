"""Comprehensive tests for the capability registry system.

Covers:
- Capability definition and idempotency
- Provider registration with priority ordering
- Loading items from all providers
- Deduplication (highest-priority wins on key conflict)
- No-dedup when key_fn returns None
- Provider filtering (include / exclude)
- Warning collection
- Cache behaviour and invalidation
- list_capabilities / get_capability_info
- Error handling for unknown capability IDs
- Async provider support
- Thread safety
- Empty-provider edge cases
- CapabilityResult structure and contributing_providers
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import patch

import pytest

from code_puppy.capability.registry import (
    _cache,
    _capabilities,
    define_capability,
    get_capability_info,
    invalidate_cache,
    list_capabilities,
    load_capability,
    register_provider,
)
from code_puppy.capability.types import (
    Capability,
    CapabilityResult,
    LoadContext,
    LoadResult,
    Provider,
    SourceMeta,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_ctx(cwd: str = "/project", home: str = "/home/user") -> LoadContext:
    return LoadContext(cwd=cwd, home=home)


class _SimpleProvider:
    """A minimal sync provider for testing."""

    def __init__(
        self,
        id: str,
        items: list[Any],
        priority: int = 50,
        warnings: list[str] | None = None,
    ) -> None:
        self.id = id
        self.display_name = id.replace("_", " ").title()
        self.description = f"Provider {id}"
        self.priority = priority
        self._items = items
        self._warnings = warnings or []

    def load(self, ctx: LoadContext) -> LoadResult:
        return LoadResult(items=list(self._items), warnings=list(self._warnings))


class _AsyncProvider:
    """An async provider for testing."""

    def __init__(self, id: str, items: list[Any], priority: int = 50) -> None:
        self.id = id
        self.display_name = id
        self.description = id
        self.priority = priority
        self._items = items

    async def load(self, ctx: LoadContext) -> LoadResult:
        await asyncio.sleep(0)  # yield to event loop
        return LoadResult(items=list(self._items))


class _ErrorProvider:
    """A provider whose load() always raises."""

    id = "error_provider"
    display_name = "Error Provider"
    description = "Always fails"
    priority = 10

    def load(self, ctx: LoadContext) -> LoadResult:
        raise RuntimeError("Boom!")


def _cap_id(suffix: str) -> str:
    """Generate a unique capability ID for test isolation."""
    import uuid

    return f"test_{suffix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate each test: remove capabilities added during the test."""
    before = set(_capabilities.keys())
    before_cache = dict(_cache)
    yield
    # Remove capabilities created by this test
    for key in list(_capabilities.keys()):
        if key not in before:
            del _capabilities[key]
    # Restore cache state
    _cache.clear()
    _cache.update(before_cache)


# ---------------------------------------------------------------------------
# define_capability
# ---------------------------------------------------------------------------


class TestDefineCapability:
    def test_creates_and_returns_capability(self):
        cap_id = _cap_id("create")
        cap = define_capability(cap_id, "Test Cap", "A test capability")
        assert isinstance(cap, Capability)
        assert cap.id == cap_id
        assert cap.display_name == "Test Cap"
        assert cap.description == "A test capability"
        assert cap.providers == []

    def test_idempotent_returns_existing(self):
        cap_id = _cap_id("idem")
        cap1 = define_capability(cap_id, "Cap", "desc")
        cap2 = define_capability(cap_id, "Different Name", "different desc")
        # Second call returns original unchanged
        assert cap1 is cap2
        assert cap2.display_name == "Cap"

    def test_key_fn_defaults_to_no_dedup(self):
        cap_id = _cap_id("keyfn")
        cap = define_capability(cap_id, "Cap", "desc")
        # Default key_fn returns None (no dedup)
        assert cap.key_fn({"anything": "here"}) is None

    def test_custom_key_fn_stored(self):
        cap_id = _cap_id("customkey")
        key_fn = lambda item: item.get("id") if isinstance(item, dict) else None
        cap = define_capability(cap_id, "Cap", "desc", key_fn=key_fn)
        assert cap.key_fn({"id": "abc"}) == "abc"
        assert cap.key_fn({"no_id": True}) is None


# ---------------------------------------------------------------------------
# register_provider
# ---------------------------------------------------------------------------


class TestRegisterProvider:
    def test_register_adds_provider(self):
        cap_id = _cap_id("reg")
        define_capability(cap_id, "Cap", "desc")
        provider = _SimpleProvider("p1", [])
        register_provider(cap_id, provider)
        info = get_capability_info(cap_id)
        assert info is not None
        provider_ids = [p["id"] for p in info["providers"]]
        assert "p1" in provider_ids

    def test_providers_ordered_by_priority_descending(self):
        cap_id = _cap_id("priority")
        define_capability(cap_id, "Cap", "desc")
        low = _SimpleProvider("low", [], priority=10)
        high = _SimpleProvider("high", [], priority=100)
        mid = _SimpleProvider("mid", [], priority=50)

        register_provider(cap_id, low)
        register_provider(cap_id, mid)
        register_provider(cap_id, high)

        info = get_capability_info(cap_id)
        assert info is not None
        ordered_ids = [p["id"] for p in info["providers"]]
        assert ordered_ids == ["high", "mid", "low"]

    def test_same_priority_preserves_insertion_order(self):
        cap_id = _cap_id("samepri")
        define_capability(cap_id, "Cap", "desc")
        a = _SimpleProvider("a", [], priority=50)
        b = _SimpleProvider("b", [], priority=50)
        register_provider(cap_id, a)
        register_provider(cap_id, b)

        info = get_capability_info(cap_id)
        assert info is not None
        ordered_ids = [p["id"] for p in info["providers"]]
        assert ordered_ids == ["a", "b"]

    def test_unknown_capability_raises_key_error(self):
        with pytest.raises(KeyError, match="not defined"):
            register_provider("nonexistent_cap_xyz", _SimpleProvider("p", []))

    def test_register_invalidates_cache(self):
        cap_id = _cap_id("cache_inv")
        define_capability(cap_id, "Cap", "desc", key_fn=lambda x: None)
        ctx = _make_ctx()
        # Populate cache manually
        from code_puppy.capability.registry import _cache

        _cache[(cap_id, ctx)] = CapabilityResult([], [], [], [])
        register_provider(cap_id, _SimpleProvider("p1", []))
        assert (cap_id, ctx) not in _cache


# ---------------------------------------------------------------------------
# load_capability – basic
# ---------------------------------------------------------------------------


class TestLoadCapabilityBasic:
    @pytest.mark.asyncio
    async def test_empty_providers_returns_empty_result(self):
        cap_id = _cap_id("empty")
        define_capability(cap_id, "Cap", "desc")
        result = await load_capability(cap_id, ctx=_make_ctx())
        assert isinstance(result, CapabilityResult)
        assert result.items == []
        assert result.all_items == []
        assert result.warnings == []
        assert result.contributing_providers == []

    @pytest.mark.asyncio
    async def test_single_provider_returns_items(self):
        cap_id = _cap_id("single")
        define_capability(cap_id, "Cap", "desc")
        items = [{"name": "alpha"}, {"name": "beta"}]
        register_provider(cap_id, _SimpleProvider("p1", items))
        result = await load_capability(cap_id, ctx=_make_ctx())
        assert result.items == items

    @pytest.mark.asyncio
    async def test_unknown_capability_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown capability"):
            await load_capability("totally_unknown_cap_xyz", ctx=_make_ctx())

    @pytest.mark.asyncio
    async def test_contributing_providers_populated(self):
        cap_id = _cap_id("contribs")
        define_capability(cap_id, "Cap", "desc")
        register_provider(cap_id, _SimpleProvider("p1", [{"name": "a"}]))
        register_provider(cap_id, _SimpleProvider("p2", [{"name": "b"}], priority=10))
        result = await load_capability(cap_id, ctx=_make_ctx())
        # Both contributed
        assert set(result.contributing_providers) == {"p1", "p2"}

    @pytest.mark.asyncio
    async def test_empty_provider_not_in_contributing(self):
        cap_id = _cap_id("empty_contrib")
        define_capability(cap_id, "Cap", "desc")
        register_provider(cap_id, _SimpleProvider("empty", []))
        register_provider(cap_id, _SimpleProvider("full", [{"name": "x"}], priority=10))
        result = await load_capability(cap_id, ctx=_make_ctx())
        assert "full" in result.contributing_providers
        assert "empty" not in result.contributing_providers


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    @pytest.mark.asyncio
    async def test_no_dedup_when_key_fn_returns_none(self):
        cap_id = _cap_id("nodedup")
        define_capability(cap_id, "Cap", "desc", key_fn=lambda _: None)
        p1 = _SimpleProvider("p1", [{"name": "x"}], priority=100)
        p2 = _SimpleProvider("p2", [{"name": "x"}], priority=50)
        register_provider(cap_id, p1)
        register_provider(cap_id, p2)
        result = await load_capability(cap_id, ctx=_make_ctx())
        # Both items present – no dedup
        assert len(result.items) == 2

    @pytest.mark.asyncio
    async def test_dedup_higher_priority_wins(self):
        cap_id = _cap_id("dedup_pri")
        key_fn = lambda m: m.get("name") if isinstance(m, dict) else None
        define_capability(cap_id, "Cap", "desc", key_fn=key_fn)
        high_item = {"name": "thing", "source": "high"}
        low_item = {"name": "thing", "source": "low"}
        p_high = _SimpleProvider("high", [high_item], priority=100)
        p_low = _SimpleProvider("low", [low_item], priority=10)
        register_provider(cap_id, p_high)
        register_provider(cap_id, p_low)
        result = await load_capability(cap_id, ctx=_make_ctx())
        # Deduplication: only one item with name "thing"
        things = [i for i in result.items if i.get("name") == "thing"]
        assert len(things) == 1
        assert things[0]["source"] == "high"

    @pytest.mark.asyncio
    async def test_all_items_includes_shadowed(self):
        cap_id = _cap_id("shadow")
        key_fn = lambda m: m.get("name") if isinstance(m, dict) else None
        define_capability(cap_id, "Cap", "desc", key_fn=key_fn)
        p1 = _SimpleProvider("p1", [{"name": "a", "v": 1}], priority=100)
        p2 = _SimpleProvider("p2", [{"name": "a", "v": 2}], priority=10)
        register_provider(cap_id, p1)
        register_provider(cap_id, p2)
        result = await load_capability(cap_id, ctx=_make_ctx())
        assert len(result.items) == 1  # deduplicated
        assert len(result.all_items) == 2  # both included

    @pytest.mark.asyncio
    async def test_different_keys_both_included(self):
        cap_id = _cap_id("diffkeys")
        key_fn = lambda m: m.get("name") if isinstance(m, dict) else None
        define_capability(cap_id, "Cap", "desc", key_fn=key_fn)
        p1 = _SimpleProvider("p1", [{"name": "alpha"}], priority=100)
        p2 = _SimpleProvider("p2", [{"name": "beta"}], priority=10)
        register_provider(cap_id, p1)
        register_provider(cap_id, p2)
        result = await load_capability(cap_id, ctx=_make_ctx())
        names = {i["name"] for i in result.items}
        assert names == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# Provider filtering
# ---------------------------------------------------------------------------


class TestProviderFiltering:
    @pytest.mark.asyncio
    async def test_include_specific_providers(self):
        cap_id = _cap_id("include")
        define_capability(cap_id, "Cap", "desc")
        register_provider(cap_id, _SimpleProvider("p1", [{"name": "from_p1"}]))
        register_provider(
            cap_id, _SimpleProvider("p2", [{"name": "from_p2"}], priority=10)
        )
        result = await load_capability(cap_id, ctx=_make_ctx(), providers=["p1"])
        names = {i["name"] for i in result.items}
        assert "from_p1" in names
        assert "from_p2" not in names

    @pytest.mark.asyncio
    async def test_exclude_specific_providers(self):
        cap_id = _cap_id("exclude")
        define_capability(cap_id, "Cap", "desc")
        register_provider(cap_id, _SimpleProvider("p1", [{"name": "from_p1"}]))
        register_provider(
            cap_id, _SimpleProvider("p2", [{"name": "from_p2"}], priority=10)
        )
        result = await load_capability(
            cap_id, ctx=_make_ctx(), exclude_providers=["p2"]
        )
        names = {i["name"] for i in result.items}
        assert "from_p1" in names
        assert "from_p2" not in names

    @pytest.mark.asyncio
    async def test_include_and_exclude_together(self):
        cap_id = _cap_id("incexc")
        define_capability(cap_id, "Cap", "desc")
        register_provider(cap_id, _SimpleProvider("p1", [{"name": "1"}], priority=100))
        register_provider(cap_id, _SimpleProvider("p2", [{"name": "2"}], priority=80))
        register_provider(cap_id, _SimpleProvider("p3", [{"name": "3"}], priority=60))
        # Include p1, p2 but exclude p2 → only p1 remains
        result = await load_capability(
            cap_id, ctx=_make_ctx(), providers=["p1", "p2"], exclude_providers=["p2"]
        )
        names = {i["name"] for i in result.items}
        assert names == {"1"}

    @pytest.mark.asyncio
    async def test_empty_include_list_returns_nothing(self):
        cap_id = _cap_id("emptyinc")
        define_capability(cap_id, "Cap", "desc")
        register_provider(cap_id, _SimpleProvider("p1", [{"name": "x"}]))
        result = await load_capability(cap_id, ctx=_make_ctx(), providers=[])
        assert result.items == []

    @pytest.mark.asyncio
    async def test_filtered_result_not_cached(self):
        """Filtered results should bypass the cache."""
        cap_id = _cap_id("filtercache")
        define_capability(cap_id, "Cap", "desc")
        register_provider(cap_id, _SimpleProvider("p1", [{"name": "a"}]))
        ctx = _make_ctx()
        # Load filtered
        await load_capability(cap_id, ctx=ctx, providers=["p1"])
        # Cache should not contain this key
        assert (cap_id, ctx) not in _cache


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


class TestWarnings:
    @pytest.mark.asyncio
    async def test_warnings_collected_from_all_providers(self):
        cap_id = _cap_id("warn")
        define_capability(cap_id, "Cap", "desc")
        p1 = _SimpleProvider("p1", [], warnings=["warn from p1"])
        p2 = _SimpleProvider("p2", [], priority=10, warnings=["warn from p2"])
        register_provider(cap_id, p1)
        register_provider(cap_id, p2)
        result = await load_capability(cap_id, ctx=_make_ctx())
        assert "warn from p1" in result.warnings
        assert "warn from p2" in result.warnings

    @pytest.mark.asyncio
    async def test_no_warnings_when_none_emitted(self):
        cap_id = _cap_id("nowarn")
        define_capability(cap_id, "Cap", "desc")
        register_provider(cap_id, _SimpleProvider("p1", [{"name": "x"}]))
        result = await load_capability(cap_id, ctx=_make_ctx())
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


class TestCache:
    @pytest.mark.asyncio
    async def test_result_cached_after_first_load(self):
        cap_id = _cap_id("cachestore")
        define_capability(cap_id, "Cap", "desc")
        register_provider(cap_id, _SimpleProvider("p1", [{"name": "x"}]))
        ctx = _make_ctx()
        result1 = await load_capability(cap_id, ctx=ctx)
        assert (cap_id, ctx) in _cache
        result2 = await load_capability(cap_id, ctx=ctx)
        assert result1 is result2  # same object – cache hit

    @pytest.mark.asyncio
    async def test_invalidate_cache_clears_entries(self):
        cap_id = _cap_id("cacheclr")
        define_capability(cap_id, "Cap", "desc")
        register_provider(cap_id, _SimpleProvider("p1", [{"name": "x"}]))
        ctx = _make_ctx()
        await load_capability(cap_id, ctx=ctx)
        assert (cap_id, ctx) in _cache
        invalidate_cache()
        assert (cap_id, ctx) not in _cache

    @pytest.mark.asyncio
    async def test_different_contexts_cached_separately(self):
        cap_id = _cap_id("ctxcache")
        define_capability(cap_id, "Cap", "desc")
        register_provider(cap_id, _SimpleProvider("p1", [{"name": "x"}]))
        ctx_a = _make_ctx(cwd="/a")
        ctx_b = _make_ctx(cwd="/b")
        await load_capability(cap_id, ctx=ctx_a)
        await load_capability(cap_id, ctx=ctx_b)
        assert (cap_id, ctx_a) in _cache
        assert (cap_id, ctx_b) in _cache


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


class TestIntrospection:
    def test_list_capabilities_includes_defined(self):
        cap_id = _cap_id("listcaps")
        define_capability(cap_id, "My Cap", "desc")
        caps = list_capabilities()
        cap_ids = [c["id"] for c in caps]
        assert cap_id in cap_ids

    def test_list_capabilities_structure(self):
        cap_id = _cap_id("struct")
        define_capability(cap_id, "Structured Cap", "A cap for structure test")
        register_provider(cap_id, _SimpleProvider("prov", [], priority=42))
        caps = list_capabilities()
        entry = next(c for c in caps if c["id"] == cap_id)
        assert entry["display_name"] == "Structured Cap"
        assert entry["description"] == "A cap for structure test"
        assert entry["provider_count"] == 1
        assert len(entry["providers"]) == 1
        assert entry["providers"][0]["id"] == "prov"
        assert entry["providers"][0]["priority"] == 42

    def test_get_capability_info_returns_details(self):
        cap_id = _cap_id("info")
        define_capability(cap_id, "Info Cap", "Detailed info")
        register_provider(cap_id, _SimpleProvider("p1", [], priority=99))
        info = get_capability_info(cap_id)
        assert info is not None
        assert info["id"] == cap_id
        assert info["display_name"] == "Info Cap"
        assert info["description"] == "Detailed info"
        assert info["provider_count"] == 1
        provider_info = info["providers"][0]
        assert provider_info["id"] == "p1"
        assert provider_info["priority"] == 99

    def test_get_capability_info_unknown_returns_none(self):
        assert get_capability_info("definitely_not_a_real_cap_xyz") is None

    def test_list_capabilities_returns_all_registered(self):
        ids = [_cap_id(f"multi_{i}") for i in range(3)]
        for cid in ids:
            define_capability(cid, cid, cid)
        caps = list_capabilities()
        existing_ids = {c["id"] for c in caps}
        for cid in ids:
            assert cid in existing_ids


# ---------------------------------------------------------------------------
# Async provider support
# ---------------------------------------------------------------------------


class TestAsyncProviders:
    @pytest.mark.asyncio
    async def test_async_provider_items_loaded(self):
        cap_id = _cap_id("async_prov")
        define_capability(cap_id, "Cap", "desc")
        register_provider(cap_id, _AsyncProvider("ap1", [{"name": "async_item"}]))
        result = await load_capability(cap_id, ctx=_make_ctx())
        assert any(i.get("name") == "async_item" for i in result.items)

    @pytest.mark.asyncio
    async def test_mixed_sync_async_providers(self):
        cap_id = _cap_id("mixed")
        key_fn = lambda m: m.get("name") if isinstance(m, dict) else None
        define_capability(cap_id, "Cap", "desc", key_fn=key_fn)
        sync_p = _SimpleProvider("sync", [{"name": "sync_item"}], priority=100)
        async_p = _AsyncProvider("async", [{"name": "async_item"}], priority=50)
        register_provider(cap_id, sync_p)
        register_provider(cap_id, async_p)
        result = await load_capability(cap_id, ctx=_make_ctx())
        names = {i["name"] for i in result.items}
        assert names == {"sync_item", "async_item"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_provider_error_does_not_propagate(self):
        cap_id = _cap_id("errprov")
        define_capability(cap_id, "Cap", "desc")
        register_provider(cap_id, _ErrorProvider())
        # Should not raise
        result = await load_capability(cap_id, ctx=_make_ctx())
        assert isinstance(result, CapabilityResult)
        assert result.items == []

    @pytest.mark.asyncio
    async def test_erroring_provider_does_not_block_others(self):
        cap_id = _cap_id("errblock")
        define_capability(cap_id, "Cap", "desc")
        err_p = _ErrorProvider()
        good_p = _SimpleProvider("good", [{"name": "ok"}], priority=200)
        register_provider(cap_id, err_p)
        register_provider(cap_id, good_p)
        result = await load_capability(cap_id, ctx=_make_ctx())
        assert any(i.get("name") == "ok" for i in result.items)

    @pytest.mark.asyncio
    async def test_load_unknown_capability_raises(self):
        with pytest.raises(KeyError):
            await load_capability("ghost_cap_never_defined_xyz")

    def test_register_provider_unknown_cap_raises(self):
        with pytest.raises(KeyError):
            register_provider("ghost_cap_xyz_2", _SimpleProvider("p", []))


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_define_and_register(self):
        """Multiple threads can define capabilities without corrupting state."""
        errors: list[Exception] = []
        cap_ids: list[str] = []

        def worker(i: int) -> None:
            try:
                cid = _cap_id(f"thread_{i}")
                cap_ids.append(cid)
                define_capability(cid, f"Cap {i}", "desc")
                register_provider(cid, _SimpleProvider(f"p_{i}", [{"val": i}]))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"

    @pytest.mark.asyncio
    async def test_concurrent_load_same_capability(self):
        """Concurrent async loads of the same capability are safe."""
        cap_id = _cap_id("concurrent_load")
        define_capability(cap_id, "Cap", "desc")
        register_provider(
            cap_id, _SimpleProvider("p1", [{"name": "item"}], priority=100)
        )
        ctx = _make_ctx()
        results = await asyncio.gather(
            *[load_capability(cap_id, ctx=ctx) for _ in range(10)]
        )
        assert all(len(r.items) == 1 for r in results)

    def test_define_capability_idempotent_under_threads(self):
        """define_capability is idempotent even when called concurrently."""
        cap_id = _cap_id("idem_thread")
        results: list[Capability] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                cap = define_capability(cap_id, "Cap", "desc")
                results.append(cap)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # All threads got the same object
        assert all(r is results[0] for r in results)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class TestTypes:
    def test_load_context_hashable(self):
        ctx = LoadContext(cwd="/proj", home="/home")
        assert hash(ctx) == hash(LoadContext(cwd="/proj", home="/home"))

    def test_load_context_equality(self):
        ctx1 = LoadContext(cwd="/a", home="/b")
        ctx2 = LoadContext(cwd="/a", home="/b")
        ctx3 = LoadContext(cwd="/x", home="/b")
        assert ctx1 == ctx2
        assert ctx1 != ctx3

    def test_source_meta_fields(self):
        sm = SourceMeta(
            provider="prov", provider_name="Prov", path="/some/path", level="user"
        )
        assert sm.provider == "prov"
        assert sm.level == "user"

    def test_load_result_defaults(self):
        lr = LoadResult(items=[1, 2, 3])
        assert lr.warnings == []

    def test_capability_result_structure(self):
        cr = CapabilityResult(
            items=[1],
            all_items=[1, 2],
            warnings=["w"],
            contributing_providers=["p1"],
        )
        assert cr.items == [1]
        assert cr.all_items == [1, 2]
        assert cr.warnings == ["w"]
        assert cr.contributing_providers == ["p1"]

    def test_provider_protocol_structural_check(self):
        """_SimpleProvider satisfies the Provider protocol."""
        p = _SimpleProvider("x", [])
        assert isinstance(p, Provider)


# ---------------------------------------------------------------------------
# Builtin capabilities
# ---------------------------------------------------------------------------


class TestBuiltinProviders:
    def test_builtin_capabilities_defined(self):
        """Importing the package defines models, rules, mcps capabilities."""
        import code_puppy.capability  # noqa: F401 – triggers builtin registration

        caps = {c["id"] for c in list_capabilities()}
        assert "models" in caps
        assert "rules" in caps
        assert "mcps" in caps

    @pytest.mark.asyncio
    async def test_builtin_capabilities_loadable(self):
        """Built-in capabilities can be loaded even with no providers."""
        from code_puppy.capability import load_capability as lc

        result = await lc("models", ctx=_make_ctx())
        assert isinstance(result, CapabilityResult)

    def test_models_key_fn(self):
        from code_puppy.capability.builtin_providers import models_capability

        assert models_capability.key_fn({"name": "gpt-4"}) == "gpt-4"
        assert models_capability.key_fn({"other": "field"}) is None
        assert models_capability.key_fn("not a dict") is None

    def test_rules_key_fn(self):
        from code_puppy.capability.builtin_providers import rules_capability

        assert rules_capability.key_fn({"name": "no_jargon"}) == "no_jargon"

    def test_mcps_key_fn(self):
        from code_puppy.capability.builtin_providers import mcps_capability

        assert mcps_capability.key_fn({"name": "filesystem"}) == "filesystem"
        assert mcps_capability.key_fn(None) is None


# ---------------------------------------------------------------------------
# Public __init__ surface
# ---------------------------------------------------------------------------


class TestPackageExports:
    def test_all_public_symbols_importable(self):
        from code_puppy.capability import (
            Capability,
            CapabilityResult,
            LoadContext,
            LoadResult,
            Provider,
            SourceMeta,
            define_capability,
            get_capability_info,
            invalidate_cache,
            list_capabilities,
            load_capability,
            register_provider,
        )

        assert callable(define_capability)
        assert callable(register_provider)
        assert callable(load_capability)
        assert callable(list_capabilities)
        assert callable(get_capability_info)
        assert callable(invalidate_cache)
        assert Capability is not None
        assert Provider is not None
        assert LoadContext is not None
        assert LoadResult is not None
        assert CapabilityResult is not None
        assert SourceMeta is not None
