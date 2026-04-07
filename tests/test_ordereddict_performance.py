"""Performance test demonstrating O(1) removal with OrderedDict.

This test validates that the OrderedDict-based StagedChangesSandbox
provides O(1) removal complexity compared to the old O(n) list-based approach.
"""

import time
from code_puppy.staged_changes import StagedChangesSandbox


def test_removal_performance():
    """Test that removal is O(1) regardless of collection size."""
    print("Testing O(1) removal performance with OrderedDict...")
    
    # Test with different collection sizes
    sizes = [100, 500, 1000, 2000]
    removal_times = []
    
    for size in sizes:
        sandbox = StagedChangesSandbox()
        
        # Add many changes
        change_ids = []
        for i in range(size):
            change = sandbox.add_create(f"/tmp/test_{i}.py", f"content {i}")
            change_ids.append(change.change_id)
        
        # Measure removal time (remove from middle to avoid best-case scenarios)
        middle_idx = size // 2
        change_id_to_remove = change_ids[middle_idx]
        
        start = time.perf_counter()
        result = sandbox.remove_change(change_id_to_remove)
        elapsed = time.perf_counter() - start
        
        assert result, f"Removal should succeed for size {size}"
        assert sandbox.count() == size - 1, f"Count should be {size-1} after removal"
        
        removal_times.append((size, elapsed))
        print(f"  Size {size:4d}: {elapsed*1000000:.2f} µs")
    
    # Verify O(1) behavior: time should not significantly increase with size
    # Allow for some variance due to system load
    if len(removal_times) >= 2:
        first_time = removal_times[0][1]
        last_time = removal_times[-1][1]
        
        # O(1) means time stays relatively constant even as size increases 20x
        ratio = last_time / first_time if first_time > 0 else 1
        print(f"\nTime ratio (largest/smallest): {ratio:.2f}x")
        print(f"  (O(1) should be roughly constant, O(n) would be ~20x)")
        
        # The ratio should be well under 10x for O(1) behavior
        assert ratio < 10, f"Removal appears to be O(n), ratio was {ratio:.2f}x"
        print("  ✓ Removal exhibits O(1) behavior!")


def test_insertion_order_preserved():
    """Test that OrderedDict maintains insertion order during iteration."""
    print("\nTesting insertion order preservation...")
    
    sandbox = StagedChangesSandbox()
    
    # Add changes in a specific order
    order = ["third", "first", "second", "fourth"]
    change_ids = []
    for name in order:
        change = sandbox.add_create(f"/tmp/{name}.py", "content")
        change_ids.append(change.change_id)
    
    # Get changes and verify order is preserved
    changes = sandbox.get_staged_changes()
    retrieved_order = [c.file_path for c in changes]
    expected_order = [f"/tmp/{name}.py" for name in order]
    
    assert retrieved_order == expected_order, \
        f"Order not preserved! Expected {expected_order}, got {retrieved_order}"
    print("  ✓ Insertion order preserved correctly!")


def test_api_compatibility():
    """Test that all public APIs work as expected."""
    print("\nTesting API compatibility...")
    
    sandbox = StagedChangesSandbox()
    
    # All add methods work
    c1 = sandbox.add_create("/tmp/a.py", "content")
    c2 = sandbox.add_replace("/tmp/b.py", "old", "new")
    c3 = sandbox.add_delete_snippet("/tmp/c.py", "snippet")
    
    assert sandbox.count() == 3
    
    # get_staged_changes returns list
    changes = sandbox.get_staged_changes()
    assert isinstance(changes, list)
    assert len(changes) == 3
    
    # get_changes_for_file works
    file_changes = sandbox.get_changes_for_file("/tmp/a.py")
    assert len(file_changes) == 1
    
    # remove_change works
    assert sandbox.remove_change(c1.change_id) == True
    assert sandbox.count() == 2
    
    # remove_change returns False for non-existent
    assert sandbox.remove_change("nonexistent") == False
    
    # clear works
    sandbox.clear()
    assert sandbox.count() == 0
    assert sandbox.is_empty()
    
    print("  ✓ All APIs work correctly!")


if __name__ == "__main__":
    test_removal_performance()
    test_insertion_order_preserved()
    test_api_compatibility()
    print("\n" + "="*50)
    print("All performance tests passed!")
    print("OrderedDict provides O(1) removal while preserving order.")
    print("="*50)
