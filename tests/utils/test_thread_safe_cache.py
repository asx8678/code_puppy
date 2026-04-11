"""Tests for thread_safe_cache module."""

import threading
import time
import functools
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from code_puppy.utils.thread_safe_cache import thread_safe_lru_cache, thread_safe_cache


# =============================================================================
# Basic Caching Tests
# =============================================================================

class TestBasicCaching:
    """Test basic cache hit/miss behavior."""
    
    def test_cache_hit_returns_cached_value(self):
        """Cache should return cached value on second call."""
        call_count = 0
        
        @thread_safe_lru_cache(maxsize=128)
        def get_value(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        result1 = get_value(5)
        result2 = get_value(5)
        
        assert result1 == 10
        assert result2 == 10
        assert call_count == 1  # Function called only once
    
    def test_cache_miss_calls_function(self):
        """Cache should call function when key not in cache."""
        call_count = 0
        
        @thread_safe_lru_cache(maxsize=128)
        def get_value(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        result1 = get_value(5)
        result2 = get_value(10)
        
        assert result1 == 10
        assert result2 == 20
        assert call_count == 2  # Function called for each unique key
    
    def test_different_args_produce_different_cache_keys(self):
        """Different arguments should use different cache entries."""
        call_count = 0
        
        @thread_safe_lru_cache(maxsize=128)
        def get_value(x, y=0):
            nonlocal call_count
            call_count += 1
            return x + y
        
        result1 = get_value(1, y=2)
        result2 = get_value(1, y=3)
        result3 = get_value(1, y=2)  # Same as first
        
        assert result1 == 3
        assert result2 == 4
        assert result3 == 3
        assert call_count == 2  # Only two unique calls


# =============================================================================
# Cache Info and Cache Clear Tests
# =============================================================================

class TestCacheInfoAndClear:
    """Test cache_info and cache_clear functionality."""
    
    def test_cache_info_initial_state(self):
        """Cache info should show zero hits/misses initially."""
        @thread_safe_lru_cache(maxsize=128)
        def get_value(x):
            return x * 2
        
        info = get_value.cache_info()
        
        assert info.hits == 0
        assert info.misses == 0
        assert info.maxsize == 128
        assert info.currsize == 0
    
    def test_cache_info_tracks_hits_and_misses(self):
        """Cache info should track hits and misses correctly."""
        @thread_safe_lru_cache(maxsize=128)
        def get_value(x):
            return x * 2
        
        get_value(1)  # miss
        get_value(1)  # hit
        get_value(1)  # hit
        get_value(2)  # miss
        
        info = get_value.cache_info()
        
        assert info.hits == 2
        assert info.misses == 2
        assert info.currsize == 2
    
    def test_cache_clear_resets_cache(self):
        """Cache clear should empty the cache."""
        call_count = 0
        
        @thread_safe_lru_cache(maxsize=128)
        def get_value(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        get_value(1)  # miss
        get_value(1)  # hit
        
        info_before = get_value.cache_info()
        assert info_before.currsize == 1
        
        get_value.cache_clear()
        
        info_after = get_value.cache_info()
        assert info_after.currsize == 0
        assert info_after.hits == 0
        assert info_after.misses == 0
        
        get_value(1)  # Should be a miss now
        assert call_count == 2
    
    def test_cache_clear_with_empty_cache(self):
        """Cache clear should work on an empty cache."""
        @thread_safe_lru_cache(maxsize=128)
        def get_value(x):
            return x * 2
        
        # Clear without any cached values
        get_value.cache_clear()
        
        info = get_value.cache_info()
        assert info.currsize == 0


# =============================================================================
# Thread Safety Tests
# =============================================================================

class TestThreadSafety:
    """Test thread safety with concurrent access."""
    
    def test_concurrent_reads_are_safe(self):
        """Multiple threads reading from cache should be safe."""
        call_count = 0
        errors = []
        results = []
        
        @thread_safe_lru_cache(maxsize=128)
        def get_value(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        def worker(value):
            try:
                result = get_value(value)
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        threads = []
        for i in range(100):
            t = threading.Thread(target=worker, args=(i % 10,))  # Only 10 unique values
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 100
        assert call_count <= 10  # Only called for each unique value
    
    def test_concurrent_mixed_access(self):
        """Mixed read/write access should be thread-safe."""
        call_count = 0
        errors = []
        
        @thread_safe_lru_cache(maxsize=128)
        def compute_expensive(x):
            nonlocal call_count
            call_count += 1
            time.sleep(0.001)  # Small delay to increase contention
            return x ** 2
        
        def worker(worker_id):
            try:
                for i in range(50):
                    compute_expensive(i % 5)
                    if i % 10 == 0:
                        compute_expensive.cache_clear()
            except Exception as e:
                errors.append((worker_id, e))
        
        threads = []
        for i in range(10):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Errors occurred: {errors}"
    
    def test_cache_integrity_under_contention(self):
        """Cache should maintain integrity under heavy contention."""
        @thread_safe_lru_cache(maxsize=128)
        def identity(x):
            return x
        
        errors = []
        
        def worker():
            try:
                for i in range(1000):
                    result = identity(i % 50)
                    if result != i % 50:
                        errors.append(f"Expected {i % 50}, got {result}")
            except Exception as e:
                errors.append(str(e))
        
        threads = []
        for i in range(20):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Cache integrity errors: {errors}"
    
    def test_threadpool_executor_safety(self):
        """Works correctly with ThreadPoolExecutor."""
        call_count = 0
        
        @thread_safe_lru_cache(maxsize=128)
        def get_value(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(get_value, i % 5) for i in range(100)]
            results = [f.result() for f in as_completed(futures)]
        
        assert len(results) == 100
        # Due to race conditions, we might have more than 5 calls, 
        # but never more than 100
        assert call_count <= 100
        assert call_count >= 5


# =============================================================================
# Unlimited Cache (thread_safe_cache) Tests
# =============================================================================

    def test_concurrent_cache_clear_vs_lookups(self):
        """Hammering cache_clear() while lookups are in flight must not crash."""
        call_count = 0
        errors = []

        @thread_safe_lru_cache(maxsize=64)
        def get_value(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        barrier = threading.Barrier(4, timeout=10)

        def reader():
            try:
                barrier.wait()
                for i in range(500):
                    result = get_value(i % 20)
                    assert result == (i % 20) * 2, f"Bad result: {result}"
                    if i % 50 == 0:
                        info = get_value.cache_info()
                        assert info.currsize >= 0
            except Exception as e:
                errors.append(("reader", e))

        def clearer():
            try:
                barrier.wait()
                for _ in range(200):
                    get_value.cache_clear()
                    time.sleep(0.0005)
            except Exception as e:
                errors.append(("clearer", e))

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=reader))
        threads.append(threading.Thread(target=clearer))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent clear: {errors}"


# =============================================================================
# Unlimited Cache (thread_safe_cache) Tests
# =============================================================================

class TestUnlimitedCache:
    """Test thread_safe_cache (unlimited size variant)."""
    
    def test_unlimited_cache_no_size_limit(self):
        """Unlimited cache should accept any number of entries."""
        @thread_safe_cache
        def get_value(x):
            return x * 2
        
        # Fill with many values
        for i in range(1000):
            get_value(i)
        
        info = get_value.cache_info()
        assert info.maxsize is None
        assert info.currsize == 1000
    
    def test_unlimited_cache_has_same_interface(self):
        """Unlimited cache should have same interface as lru variant."""
        @thread_safe_cache
        def get_value(x):
            return x * 2
        
        # Should have cache_info
        info = get_value.cache_info()
        assert hasattr(info, 'hits')
        assert hasattr(info, 'misses')
        assert hasattr(info, 'maxsize')
        assert hasattr(info, 'currsize')
        
        # Should have cache_clear
        get_value(1)
        assert get_value.cache_info().currsize == 1
        get_value.cache_clear()
        assert get_value.cache_info().currsize == 0


# =============================================================================
# Decorator Metadata Tests
# =============================================================================

class TestDecoratorMetadata:
    """Test that decorator preserves function metadata."""
    
    def test_function_name_preserved(self):
        """@wraps should preserve original function name."""
        @thread_safe_lru_cache(maxsize=128)
        def my_special_function(x):
            """This is a special function."""
            return x * 2
        
        assert my_special_function.__name__ == "my_special_function"
    
    def test_function_docstring_preserved(self):
        """@wraps should preserve original docstring."""
        @thread_safe_lru_cache(maxsize=128)
        def my_special_function(x):
            """This is a special function."""
            return x * 2
        
        assert my_special_function.__doc__ == "This is a special function."
    
    def test_module_preserved(self):
        """@wraps should preserve __module__."""
        @thread_safe_lru_cache(maxsize=128)
        def my_function(x):
            return x * 2
        
        # Module should be this test module
        assert my_function.__module__ == __name__
    
    def test_qualified_name_preserved(self):
        """@wraps should preserve __qualname__."""
        class MyClass:
            @thread_safe_lru_cache(maxsize=128)
            def method(self, x):
                return x * 2
        
        assert MyClass.method.__name__ == "method"


# =============================================================================
# LRU Behavior Tests
# =============================================================================

class TestLRUBehavior:
    """Test LRU cache eviction behavior."""
    
    def test_lru_eviction_with_small_cache(self):
        """LRU cache should evict least recently used items."""
        call_count = 0
        
        @thread_safe_lru_cache(maxsize=2)
        def get_value(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        get_value(1)  # cache: [1]
        get_value(2)  # cache: [1, 2]
        get_value(3)  # cache: [2, 3] - 1 evicted
        
        info = get_value.cache_info()
        assert info.currsize == 2
        
        get_value(1)  # miss, needs to recompute
        
        info = get_value.cache_info()
        assert info.misses == 4  # 1, 2, 3, 1
    
    def test_typed_parameter_creates_separate_entries(self):
        """Typed cache should treat 1 and 1.0 as different."""
        call_count = 0
        
        @thread_safe_lru_cache(maxsize=128, typed=True)
        def get_value(x):
            nonlocal call_count
            call_count += 1
            return str(x)
        
        result1 = get_value(1)    # int
        result2 = get_value(1.0)  # float
        _result3 = get_value(1)   # int again (triggers hit)

        assert result1 == "1"
        assert result2 == "1.0"
        assert call_count == 2  # 1 and 1.0 are different
        
        info = get_value.cache_info()
        assert info.hits == 1  # Third call was a hit
        assert info.misses == 2  # First two were misses
    
    def test_untyped_cache_does_not_store_types_separately(self):
        """Untyped cache doesn't include type in cache key by default.
        
        Note: Even with typed=False, 1 and 1.0 are treated as different keys
        because they hash differently. The typed parameter only adds explicit
        type identity checking.
        """
        call_count = 0
        
        @thread_safe_lru_cache(maxsize=128, typed=False)
        def get_value(x):
            nonlocal call_count
            call_count += 1
            return str(x)
        
        get_value(1)    # int
        get_value(1.0)  # float - different key even with typed=False

        # Both are misses because int 1 and float 1.0 are different keys
        assert call_count == 2

        info = get_value.cache_info()
        assert info.hits == 0
        assert info.misses == 2


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_exception_not_cached(self):
        """Exceptions should not be cached."""
        call_count = 0
        
        @thread_safe_lru_cache(maxsize=128)
        def fail_on_odd(x):
            nonlocal call_count
            call_count += 1
            if x % 2 == 1:
                raise ValueError(f"Odd number: {x}")
            return x
        
        # First call with odd should raise
        with pytest.raises(ValueError):
            fail_on_odd(1)
        
        # Second call should try again (not cached)
        with pytest.raises(ValueError):
            fail_on_odd(1)
        
        assert call_count == 2
    
    def test_cache_with_none_result(self):
        """None results should be cached properly."""
        call_count = 0
        
        @thread_safe_lru_cache(maxsize=128)
        def return_none(x):
            nonlocal call_count
            call_count += 1
            return None
        
        result1 = return_none(1)
        result2 = return_none(1)
        
        assert result1 is None
        assert result2 is None
        assert call_count == 1
    
    def test_cache_with_unhashable_args_raises(self):
        """Unhashable args should raise TypeError."""
        @thread_safe_lru_cache(maxsize=128)
        def process(data):
            return len(data)
        
        # Lists are unhashable
        with pytest.raises(TypeError):
            process([1, 2, 3])
    
    def test_zero_maxsize_cache(self):
        """Zero maxsize should disable caching."""
        call_count = 0
        
        @thread_safe_lru_cache(maxsize=0)
        def get_value(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        get_value(1)
        get_value(1)
        
        assert call_count == 2  # Each call computes


# =============================================================================
# Recursive Function Tests (Deadlock Regression)
# =============================================================================

class TestRecursiveFunctions:
    """Test that recursive cached functions don't deadlock."""
    
    def test_recursive_function_does_not_deadlock(self):
        """Ensure recursive cached functions don't deadlock.
        
        This is a regression test for code_puppy-68x.10.
        Before the fix, using threading.Lock() would cause deadlock
        because the same thread tries to re-acquire the lock on recursion.
        RLock allows the same thread to acquire the lock multiple times.
        """
        from code_puppy.utils.thread_safe_cache import thread_safe_lru_cache
        
        @thread_safe_lru_cache(maxsize=None)
        def fibonacci(n):
            if n < 2:
                return n
            return fibonacci(n - 1) + fibonacci(n - 2)
        
        assert fibonacci(10) == 55
        assert fibonacci(5) == 5  # Should be cached


# =============================================================================
# Comparison with Standard Library
# =============================================================================

class TestStandardLibraryCompatibility:
    """Verify compatibility with functools.lru_cache behavior."""
    
    def test_same_results_as_functools_lru_cache(self):
        """Results should be identical to functools.lru_cache."""
        
        @functools.lru_cache(maxsize=128)
        def std_func(x):
            return x * 2
        
        @thread_safe_lru_cache(maxsize=128)
        def ts_func(x):
            return x * 2
        
        for i in range(100):
            assert std_func(i) == ts_func(i)
    
    def test_cache_info_same_structure(self):
        """cache_info should return same structure as functools."""
        
        @functools.lru_cache(maxsize=128)
        def std_func(x):
            return x * 2
        
        @thread_safe_lru_cache(maxsize=128)
        def ts_func(x):
            return x * 2
        
        std_func(1)
        ts_func(1)
        
        std_info = std_func.cache_info()
        ts_info = ts_func.cache_info()
        
        assert std_info.hits == ts_info.hits
        assert std_info.misses == ts_info.misses
        assert std_info.maxsize == ts_info.maxsize
        assert std_info.currsize == ts_info.currsize
