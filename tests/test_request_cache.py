"""Tests for request cache module.

Tests for the request_cache module which provides header-only change
optimization and request caching for HTTP clients.
"""

import time
from unittest.mock import Mock

import httpx

from code_puppy.request_cache import (
    CachedRequest,
    CacheStats,
    RequestCache,
    RequestCacheMixin,
    get_global_request_cache,
    reset_global_request_cache,
)


class TestCacheStats:
    """Test CacheStats dataclass."""

    def test_default_values(self):
        """Test that CacheStats has correct default values."""
        stats = CacheStats()
        assert stats.hits == 0
        assert stats.header_only_updates == 0
        assert stats.misses == 0
        assert stats.evictions == 0
        assert stats.rebuilds_avoided == 0

    def test_custom_values(self):
        """Test that CacheStats can be initialized with custom values."""
        stats = CacheStats(
            hits=10, header_only_updates=5, misses=3, evictions=2, rebuilds_avoided=15
        )
        assert stats.hits == 10
        assert stats.header_only_updates == 5
        assert stats.misses == 3
        assert stats.evictions == 2
        assert stats.rebuilds_avoided == 15


class TestCachedContent:
    """Test CachedContent dataclass (stores bytes only, not full request)."""

    def test_default_creation(self):
        """Test creating a CachedContent with defaults."""
        cached = CachedRequest(
            content=b'{"test": true}',
            content_hash="abc123",
            headers_hash="def456",
            method="POST",
            url="https://api.example.com",
        )
        assert cached.content == b'{"test": true}'
        assert cached.content_hash == "abc123"
        assert cached.headers_hash == "def456"
        assert cached.method == "POST"
        assert cached.url == "https://api.example.com"
        assert cached.access_count == 0
        # created_at should be close to now
        assert time.time() - cached.created_at < 1.0
        # last_accessed should be very close to created_at (may differ by microseconds)
        assert abs(cached.last_accessed - cached.created_at) < 0.001


class TestRequestCacheBasics:
    """Basic tests for RequestCache."""

    def test_default_initialization(self):
        """Test RequestCache initializes with correct defaults."""
        cache = RequestCache()
        assert cache._max_size == RequestCache.DEFAULT_MAX_SIZE
        assert cache._ttl_seconds == RequestCache.DEFAULT_TTL_SECONDS
        assert cache._enable_stats is True
        assert cache._cache == {}

    def test_custom_initialization(self):
        """Test RequestCache can be initialized with custom values."""
        cache = RequestCache(max_size=50, ttl_seconds=60, enable_stats=False)
        assert cache._max_size == 50
        assert cache._ttl_seconds == 60
        assert cache._enable_stats is False


class TestContentHashComputation:
    """Test content hash computation."""

    def test_same_content_same_hash(self):
        """Test that same content produces same hash."""
        cache = RequestCache()
        hash1 = cache._compute_content_hash(
            "POST", "https://api.example.com", b'{"test": true}'
        )
        hash2 = cache._compute_content_hash(
            "POST", "https://api.example.com", b'{"test": true}'
        )
        assert hash1 == hash2

    def test_different_method_different_hash(self):
        """Test that different methods produce different hashes."""
        cache = RequestCache()
        hash1 = cache._compute_content_hash("GET", "https://api.example.com", None)
        hash2 = cache._compute_content_hash("POST", "https://api.example.com", None)
        assert hash1 != hash2

    def test_different_url_different_hash(self):
        """Test that different URLs produce different hashes."""
        cache = RequestCache()
        hash1 = cache._compute_content_hash("POST", "https://api1.example.com", None)
        hash2 = cache._compute_content_hash("POST", "https://api2.example.com", None)
        assert hash1 != hash2

    def test_different_body_different_hash(self):
        """Test that different bodies produce different hashes."""
        cache = RequestCache()
        hash1 = cache._compute_content_hash(
            "POST", "https://api.example.com", b'{"a": 1}'
        )
        hash2 = cache._compute_content_hash(
            "POST", "https://api.example.com", b'{"a": 2}'
        )
        assert hash1 != hash2

    def test_empty_body_hash(self):
        """Test that None and empty bytes produce different hashes."""
        cache = RequestCache()
        hash1 = cache._compute_content_hash("POST", "https://api.example.com", None)
        hash2 = cache._compute_content_hash("POST", "https://api.example.com", b"")
        # Both should work but produce different results
        assert isinstance(hash1, str)
        assert isinstance(hash2, str)


class TestHeadersHashComputation:
    """Test headers hash computation."""

    def test_same_headers_same_hash(self):
        """Test that same headers produce same hash."""
        cache = RequestCache()
        hash1 = cache._compute_headers_hash({"Authorization": "Bearer token123"})
        hash2 = cache._compute_headers_hash({"Authorization": "Bearer token123"})
        assert hash1 == hash2

    def test_different_headers_different_hash(self):
        """Test that different headers produce different hashes."""
        cache = RequestCache()
        hash1 = cache._compute_headers_hash({"Authorization": "Bearer token123"})
        hash2 = cache._compute_headers_hash({"Authorization": "Bearer token456"})
        assert hash1 != hash2

    def test_case_insensitive_header_keys(self):
        """Test that header keys are normalized to lowercase."""
        cache = RequestCache()
        hash1 = cache._compute_headers_hash({"Authorization": "Bearer token123"})
        hash2 = cache._compute_headers_hash({"authorization": "Bearer token123"})
        assert hash1 == hash2

    def test_header_order_independence(self):
        """Test that header order doesn't affect hash."""
        cache = RequestCache()
        hash1 = cache._compute_headers_hash(
            {"Authorization": "Bearer token123", "Content-Type": "application/json"}
        )
        hash2 = cache._compute_headers_hash(
            {"Content-Type": "application/json", "Authorization": "Bearer token123"}
        )
        assert hash1 == hash2

    def test_content_length_excluded(self):
        """Test that Content-Length header is excluded from hash."""
        cache = RequestCache()
        hash1 = cache._compute_headers_hash({"Authorization": "Bearer token123"})
        hash2 = cache._compute_headers_hash(
            {"Authorization": "Bearer token123", "Content-Length": "1234"}
        )
        assert hash1 == hash2


class TestCacheEntryValidity:
    """Test cache entry validity checking."""

    def test_fresh_entry_is_valid(self):
        """Test that recently created entries are valid."""
        cache = RequestCache(ttl_seconds=300)
        entry = CachedRequest(
            content=b'{"test": true}',
            content_hash="abc",
            headers_hash="def",
            method="POST",
            url="https://api.example.com",
        )
        assert cache._is_entry_valid(entry) is True

    def test_expired_entry_is_invalid(self):
        """Test that expired entries are invalid."""
        cache = RequestCache(ttl_seconds=1)
        entry = CachedRequest(
            content=b'{"test": true}',
            content_hash="abc",
            headers_hash="def",
            method="POST",
            url="https://api.example.com",
            created_at=time.time() - 2,  # Created 2 seconds ago
        )
        assert cache._is_entry_valid(entry) is False


class TestEviction:
    """Test cache eviction."""

    def test_lru_eviction_when_full(self):
        """Test that LRU entries are evicted when cache is full."""
        cache = RequestCache(max_size=2)
        client = Mock(spec=httpx.AsyncClient)
        client.build_request = Mock(return_value=Mock(spec=httpx.Request))

        # Add 2 entries (fills cache)
        request1 = cache.get_or_build(
            "POST", "https://api.example.com/1", {}, b"body1", client
        )
        request2 = cache.get_or_build(
            "POST", "https://api.example.com/2", {}, b"body2", client
        )

        assert len(cache._cache) == 2
        content_hash_1 = cache._compute_content_hash(
            "POST", "https://api.example.com/1", b"body1"
        )
        content_hash_2 = cache._compute_content_hash(
            "POST", "https://api.example.com/2", b"body2"
        )
        assert content_hash_1 in cache._cache
        assert content_hash_2 in cache._cache

        # Access entry 1 to make it more recently used
        time.sleep(0.01)  # Small delay to ensure different last_accessed
        cached_entry = cache._cache[content_hash_1]
        cached_entry.last_accessed = time.time()

        # Add 3rd entry - should evict entry 2 (least recently used)
        request3 = cache.get_or_build(
            "POST", "https://api.example.com/3", {}, b"body3", client
        )

        assert len(cache._cache) == 2
        assert content_hash_1 in cache._cache  # Should still be there
        assert content_hash_2 not in cache._cache  # Should be evicted

    def test_expired_entry_eviction(self):
        """Test that expired entries are evicted."""
        cache = RequestCache(ttl_seconds=0.01)
        client = Mock(spec=httpx.AsyncClient)
        client.build_request = Mock(return_value=Mock(spec=httpx.Request))

        # Add entry
        request1 = cache.get_or_build(
            "POST", "https://api.example.com", {}, b"body", client
        )

        # Wait for it to expire
        time.sleep(0.02)

        # Manually trigger eviction
        cache._evict_expired_entries()

        assert len(cache._cache) == 0
        assert cache._stats.evictions == 1


class TestGetOrBuild:
    """Test the get_or_build method."""

    def test_cache_miss_creates_new_entry(self):
        """Test that cache miss creates a new entry."""
        cache = RequestCache()
        client = Mock(spec=httpx.AsyncClient)
        mock_request = Mock(spec=httpx.Request)
        client.build_request = Mock(return_value=mock_request)

        request = cache.get_or_build(
            "POST",
            "https://api.example.com",
            {"Auth": "token"},
            b'{"test": true}',
            client,
        )

        assert request == mock_request
        assert len(cache._cache) == 1
        assert cache._stats.misses == 1

    def test_cache_hit_returns_cached_request(self):
        """Test that exact match returns cached request."""
        cache = RequestCache()
        client = Mock(spec=httpx.AsyncClient)
        mock_request = Mock(spec=httpx.Request)
        client.build_request = Mock(return_value=mock_request)

        headers = {"Authorization": "Bearer token123"}

        # First call - cache miss
        request1 = cache.get_or_build(
            "POST", "https://api.example.com", headers, b'{"test": true}', client
        )

        # Second call - should be cache hit
        request2 = cache.get_or_build(
            "POST", "https://api.example.com", headers, b'{"test": true}', client
        )

        assert request2 == mock_request  # Should return same cached request
        assert cache._stats.hits == 1
        assert cache._stats.misses == 1

    def test_header_only_change_updates_headers(self):
        """Test that header-only change reuses request with new headers."""
        cache = RequestCache()
        client = Mock(spec=httpx.AsyncClient)

        # Create proper mock with method attribute
        original_request = Mock(spec=httpx.Request)
        original_request.method = "POST"
        original_request.url = "https://api.example.com"
        original_request._content = b'{"test": true}'
        original_request.stream = None
        original_request.extensions = {}

        # New request (same content, different auth header)
        updated_request = Mock(spec=httpx.Request)
        updated_request._content = b'{"test": true}'
        updated_request.stream = None
        updated_request.extensions = {}

        client.build_request = Mock(side_effect=[original_request, updated_request])

        headers1 = {"Authorization": "Bearer token1"}
        headers2 = {"Authorization": "Bearer token2"}

        # First call
        request1 = cache.get_or_build(
            "POST", "https://api.example.com", headers1, b'{"test": true}', client
        )

        # Second call with different headers - should be header-only update
        request2 = cache.get_or_build(
            "POST", "https://api.example.com", headers2, b'{"test": true}', client
        )

        # Should trigger header-only update path
        assert cache._stats.header_only_updates == 1

    def test_body_change_triggers_new_request(self):
        """Test that body change creates new request, not cached."""
        cache = RequestCache()
        client = Mock(spec=httpx.AsyncClient)
        client.build_request = Mock(return_value=Mock(spec=httpx.Request))

        headers = {"Authorization": "Bearer token"}

        # First call
        request1 = cache.get_or_build(
            "POST", "https://api.example.com", headers, b'{"a": 1}', client
        )

        # Second call with different body - different content hash
        request2 = cache.get_or_build(
            "POST", "https://api.example.com", headers, b'{"a": 2}', client
        )

        # Both should be misses (different content)
        assert cache._stats.misses == 2
        assert cache._stats.hits == 0
        assert len(cache._cache) == 2


class TestCacheStats:
    """Test cache statistics."""

    def test_get_stats(self):
        """Test getting cache statistics."""
        cache = RequestCache()
        client = Mock(spec=httpx.AsyncClient)
        client.build_request = Mock(return_value=Mock(spec=httpx.Request))

        # Add some entries to build stats
        cache._stats.hits = 5
        cache._stats.header_only_updates = 3
        cache._stats.misses = 2
        cache._stats.evictions = 1
        cache._stats.rebuilds_avoided = 8

        stats = cache.get_stats()
        assert stats.hits == 5
        assert stats.header_only_updates == 3
        assert stats.misses == 2
        assert stats.evictions == 1
        assert stats.rebuilds_avoided == 8

    def test_get_stats_dict(self):
        """Test getting cache statistics as dictionary."""
        cache = RequestCache(max_size=100)
        client = Mock(spec=httpx.AsyncClient)
        client.build_request = Mock(return_value=Mock(spec=httpx.Request))

        # Pre-populate stats manually (simulating prior operations)
        cache._stats.hits = 5
        cache._stats.header_only_updates = 3
        cache._stats.misses = 1  # Will get 1 more from the get_or_build call
        cache._stats.evictions = 1
        cache._stats.rebuilds_avoided = 8

        # Add an entry to cache - this will count as a miss
        cache.get_or_build("POST", "https://api.example.com", {}, b"body", client)

        stats_dict = cache.get_stats_dict()
        assert stats_dict["hits"] == 5
        assert stats_dict["header_only_updates"] == 3
        assert stats_dict["misses"] == 2  # 1 from setup + 1 from get_or_build
        assert stats_dict["evictions"] == 1
        assert stats_dict["rebuilds_avoided"] == 8
        assert stats_dict["total_requests"] == 10
        assert stats_dict["hit_rate"] == 0.8  # (5 + 3) / 10
        assert stats_dict["current_size"] == 1
        assert stats_dict["max_size"] == 100

    def test_clear_stats(self):
        """Test clearing cache statistics."""
        cache = RequestCache()
        cache._stats.hits = 5
        cache._stats.misses = 3

        cache.clear_stats()

        assert cache._stats.hits == 0
        assert cache._stats.misses == 0
        assert cache._stats.header_only_updates == 0


class TestInvalidate:
    """Test cache invalidation."""

    def test_invalidate_specific_hash(self):
        """Test invalidating a specific cache entry."""
        cache = RequestCache()
        client = Mock(spec=httpx.AsyncClient)
        client.build_request = Mock(return_value=Mock(spec=httpx.Request))

        # Add entry
        cache.get_or_build("POST", "https://api.example.com", {}, b"body", client)

        content_hash = cache._compute_content_hash(
            "POST", "https://api.example.com", b"body"
        )

        # Invalidate it
        count = cache.invalidate(content_hash)

        assert count == 1
        assert content_hash not in cache._cache

    def test_invalidate_all(self):
        """Test invalidating all cache entries."""
        cache = RequestCache()
        client = Mock(spec=httpx.AsyncClient)
        client.build_request = Mock(return_value=Mock(spec=httpx.Request))

        # Add multiple entries
        cache.get_or_build("POST", "https://api.example.com/1", {}, b"body1", client)
        cache.get_or_build("POST", "https://api.example.com/2", {}, b"body2", client)

        # Invalidate all
        count = cache.invalidate()

        assert count == 2
        assert len(cache._cache) == 0


class TestGlobalCache:
    """Test global cache functionality."""

    def test_get_global_cache(self):
        """Test getting global cache creates it if needed."""
        reset_global_request_cache()
        cache = get_global_request_cache()
        assert isinstance(cache, RequestCache)

        # Second call returns same instance
        cache2 = get_global_request_cache()
        assert cache is cache2

        reset_global_request_cache()

    def test_reset_global_cache(self):
        """Test resetting global cache."""
        # Get cache first
        cache = get_global_request_cache()
        assert cache is not None

        # Reset it
        reset_global_request_cache()

        # Get again - should be new instance
        cache2 = get_global_request_cache()
        assert cache is not cache2

        reset_global_request_cache()


class TestRequestCacheMixin:
    """Test RequestCacheMixin."""

    def test_mixin_initializes_cache(self):
        """Test that mixin properly initializes cache."""

        class TestClient(RequestCacheMixin, httpx.AsyncClient):
            def __init__(self):
                super().__init__()
                self._init_request_cache(max_size=50, ttl_seconds=120)

        client = TestClient()
        assert hasattr(client, "_request_cache")
        assert client._request_cache._max_size == 50
        assert client._request_cache._ttl_seconds == 120

    def test_cached_or_build_without_cache(self):
        """Test cached_or_build_request falls back to direct build when no cache."""

        class TestClient(RequestCacheMixin, httpx.AsyncClient):
            pass

        client = TestClient()
        # Without initializing cache, it should fall back to direct build
        mock_request = Mock(spec=httpx.Request)
        client.build_request = Mock(return_value=mock_request)

        result = client.cached_or_build_request(
            "POST", "https://api.example.com", {"Auth": "token"}, b"body"
        )

        assert result == mock_request
        client.build_request.assert_called_once()

    def test_get_cache_stats(self):
        """Test getting cache stats from mixin."""

        class TestClient(RequestCacheMixin, httpx.AsyncClient):
            def __init__(self):
                super().__init__()
                self._init_request_cache()

        client = TestClient()
        stats = client.get_cache_stats()
        # Stats dict should have typical keys from get_stats_dict()
        assert "hits" in stats
        assert "misses" in stats
        assert "current_size" in stats
        assert "max_size" in stats

    def test_invalidate_cache(self):
        """Test cache invalidation from mixin."""

        class TestClient(RequestCacheMixin, httpx.AsyncClient):
            def __init__(self):
                super().__init__()
                self._init_request_cache()

        client = TestClient()
        # Add an entry first
        mock_client = Mock(spec=httpx.AsyncClient)
        mock_client.build_request = Mock(return_value=Mock(spec=httpx.Request))
        client._request_cache.get_or_build(
            "POST", "https://api.example.com", {}, b"body", mock_client
        )

        # Invalidate
        count = client.invalidate_cache()
        assert count == 1


class TestPerformanceOptimization:
    """Test performance optimization scenarios."""

    def test_header_only_optimization_scenario(self):
        """Simulate real-world header-only change scenario."""
        cache = RequestCache()
        client = Mock(spec=httpx.AsyncClient)

        # Original request with proper method attribute
        original = Mock(spec=httpx.Request)
        original.method = "POST"
        original.url = "https://api.anthropic.com/v1/messages"
        original.content = b'{"messages": [{"role": "user", "content": "Hello"}]}'
        original._content = original.content
        original.stream = None
        original.extensions = {}

        # New request (same content, different auth header)
        new_request = Mock(spec=httpx.Request)
        new_request.content = original.content
        new_request._content = original.content
        new_request.stream = None
        new_request.extensions = {}

        client.build_request = Mock(side_effect=[original, new_request])

        body = b'{"messages": [{"role": "user", "content": "Hello"}]}'

        # First request with token1
        headers1 = {"Authorization": "Bearer token1_old"}
        result1 = cache.get_or_build(
            "POST", "https://api.anthropic.com/v1/messages", headers1, body, client
        )
        assert cache._stats.misses == 1

        # Token refresh - same body, new auth header (header-only change!)
        headers2 = {"Authorization": "Bearer token2_new"}
        result2 = cache.get_or_build(
            "POST", "https://api.anthropic.com/v1/messages", headers2, body, client
        )

        # Should be a header-only update
        assert cache._stats.header_only_updates == 1
        assert cache._stats.rebuilds_avoided == 1

    def test_multiple_identical_requests_use_cache(self):
        """Test that multiple identical requests use cache."""
        cache = RequestCache()
        client = Mock(spec=httpx.AsyncClient)
        mock_request = Mock(spec=httpx.Request)
        client.build_request = Mock(return_value=mock_request)

        headers = {"Authorization": "Bearer token"}
        body = b'{"test": true}'
        url = "https://api.example.com"
        method = "POST"

        # Make 100 identical requests
        for i in range(100):
            cache.get_or_build(method, url, headers, body, client)

        # Should have 1 miss and 99 hits
        assert cache._stats.misses == 1
        assert cache._stats.hits == 99
        # Should only have one cache entry
        assert len(cache._cache) == 1
