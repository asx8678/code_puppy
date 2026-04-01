"""Comprehensive tests for code_puppy.utils.ring_buffer.RingBuffer.

Covers:
- Basic push / pop / shift / unshift
- Overflow / eviction behaviour (push and unshift)
- Negative indexing via at() and __getitem__
- Iterator behaviour (__iter__, __len__, __bool__)
- Empty buffer edge cases
- Capacity-1 edge cases
- to_list() after wrap-around
- __getitem__ with integer indices and slices
- peek / peek_back
- clear()
- __repr__
- is_full / is_empty properties
- Invalid capacity raises ValueError
"""

import pytest

from code_puppy.utils import RingBuffer
from code_puppy.utils.ring_buffer import RingBuffer as RingBufferDirect


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_basic_creation(self):
        buf: RingBuffer[int] = RingBuffer(5)
        assert buf.capacity == 5
        assert len(buf) == 0
        assert buf.is_empty
        assert not buf.is_full

    def test_capacity_one(self):
        buf: RingBuffer[str] = RingBuffer(1)
        assert buf.capacity == 1
        assert len(buf) == 0

    def test_invalid_capacity_zero(self):
        with pytest.raises(ValueError):
            RingBuffer(0)

    def test_invalid_capacity_negative(self):
        with pytest.raises(ValueError):
            RingBuffer(-3)

    def test_import_from_package_init(self):
        """Ensure the package __init__ re-exports RingBuffer."""
        assert RingBuffer is RingBufferDirect


# ---------------------------------------------------------------------------
# push / pop (tail operations)
# ---------------------------------------------------------------------------


class TestPushPop:
    def test_push_returns_none_when_not_full(self):
        buf: RingBuffer[int] = RingBuffer(3)
        assert buf.push(1) is None
        assert buf.push(2) is None
        assert buf.push(3) is None

    def test_push_evicts_oldest_when_full(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(1)
        buf.push(2)
        buf.push(3)
        evicted = buf.push(4)
        assert evicted == 1
        assert list(buf) == [2, 3, 4]

    def test_push_eviction_chain(self):
        buf: RingBuffer[int] = RingBuffer(2)
        buf.push(10)
        buf.push(20)
        assert buf.push(30) == 10
        assert buf.push(40) == 20
        assert list(buf) == [30, 40]

    def test_pop_returns_none_on_empty(self):
        buf: RingBuffer[int] = RingBuffer(3)
        assert buf.pop() is None

    def test_pop_returns_newest(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(1)
        buf.push(2)
        buf.push(3)
        assert buf.pop() == 3
        assert len(buf) == 2
        assert list(buf) == [1, 2]

    def test_pop_empties_buffer(self):
        buf: RingBuffer[int] = RingBuffer(2)
        buf.push(5)
        buf.pop()
        assert buf.is_empty
        assert not bool(buf)

    def test_push_then_pop_roundtrip(self):
        buf: RingBuffer[str] = RingBuffer(4)
        for word in ("a", "b", "c", "d"):
            buf.push(word)
        result = []
        while buf:
            result.append(buf.pop())
        assert result == ["d", "c", "b", "a"]


# ---------------------------------------------------------------------------
# shift / unshift (head operations)
# ---------------------------------------------------------------------------


class TestShiftUnshift:
    def test_shift_returns_none_on_empty(self):
        buf: RingBuffer[int] = RingBuffer(3)
        assert buf.shift() is None

    def test_shift_returns_oldest(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(10)
        buf.push(20)
        buf.push(30)
        assert buf.shift() == 10
        assert len(buf) == 2
        assert list(buf) == [20, 30]

    def test_shift_empties_buffer(self):
        buf: RingBuffer[int] = RingBuffer(1)
        buf.push(99)
        assert buf.shift() == 99
        assert buf.is_empty

    def test_unshift_returns_none_when_not_full(self):
        buf: RingBuffer[int] = RingBuffer(3)
        assert buf.unshift(1) is None
        assert buf.unshift(0) is None
        assert list(buf) == [0, 1]

    def test_unshift_evicts_newest_when_full(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(1)
        buf.push(2)
        buf.push(3)
        evicted = buf.unshift(0)
        assert evicted == 3
        assert list(buf) == [0, 1, 2]

    def test_unshift_into_empty(self):
        buf: RingBuffer[str] = RingBuffer(3)
        buf.unshift("x")
        assert list(buf) == ["x"]

    def test_unshift_then_shift_roundtrip(self):
        buf: RingBuffer[int] = RingBuffer(4)
        for v in (1, 2, 3, 4):
            buf.unshift(v)
        # Buffer should be [4, 3, 2, 1] (most recently unshifted is oldest)
        result = []
        while buf:
            result.append(buf.shift())
        assert result == [4, 3, 2, 1]


# ---------------------------------------------------------------------------
# at() / negative indexing
# ---------------------------------------------------------------------------


class TestAt:
    def test_at_zero_is_first(self):
        buf: RingBuffer[int] = RingBuffer(5)
        buf.push(10)
        buf.push(20)
        buf.push(30)
        assert buf.at(0) == 10

    def test_at_last_positive(self):
        buf: RingBuffer[int] = RingBuffer(5)
        buf.push(10)
        buf.push(20)
        buf.push(30)
        assert buf.at(2) == 30

    def test_at_negative_one_is_last(self):
        buf: RingBuffer[int] = RingBuffer(5)
        for v in (1, 2, 3):
            buf.push(v)
        assert buf.at(-1) == 3

    def test_at_negative_two(self):
        buf: RingBuffer[int] = RingBuffer(5)
        for v in (1, 2, 3):
            buf.push(v)
        assert buf.at(-2) == 2

    def test_at_out_of_range_positive(self):
        buf: RingBuffer[int] = RingBuffer(5)
        buf.push(1)
        assert buf.at(5) is None

    def test_at_out_of_range_negative(self):
        buf: RingBuffer[int] = RingBuffer(5)
        buf.push(1)
        assert buf.at(-2) is None

    def test_at_empty(self):
        buf: RingBuffer[int] = RingBuffer(3)
        assert buf.at(0) is None
        assert buf.at(-1) is None

    def test_at_after_wrap_around(self):
        """at() should work correctly after head wraps past capacity."""
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(1)
        buf.push(2)
        buf.push(3)
        buf.push(4)  # evicts 1 → buf = [2, 3, 4]
        assert buf.at(0) == 2
        assert buf.at(1) == 3
        assert buf.at(2) == 4
        assert buf.at(-1) == 4


# ---------------------------------------------------------------------------
# peek / peek_back
# ---------------------------------------------------------------------------


class TestPeek:
    def test_peek_returns_first(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(7)
        buf.push(8)
        assert buf.peek() == 7

    def test_peek_back_returns_last(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(7)
        buf.push(8)
        assert buf.peek_back() == 8

    def test_peek_empty(self):
        buf: RingBuffer[int] = RingBuffer(3)
        assert buf.peek() is None

    def test_peek_back_empty(self):
        buf: RingBuffer[int] = RingBuffer(3)
        assert buf.peek_back() is None

    def test_peek_does_not_remove(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(42)
        buf.peek()
        assert len(buf) == 1

    def test_peek_back_does_not_remove(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(42)
        buf.peek_back()
        assert len(buf) == 1


# ---------------------------------------------------------------------------
# Iterator / length / bool
# ---------------------------------------------------------------------------


class TestIterAndBool:
    def test_iter_empty(self):
        buf: RingBuffer[int] = RingBuffer(3)
        assert list(buf) == []

    def test_iter_partial(self):
        buf: RingBuffer[int] = RingBuffer(5)
        for v in (10, 20, 30):
            buf.push(v)
        assert list(buf) == [10, 20, 30]

    def test_iter_after_overflow(self):
        buf: RingBuffer[int] = RingBuffer(3)
        for v in (1, 2, 3, 4, 5):
            buf.push(v)
        assert list(buf) == [3, 4, 5]

    def test_len_empty(self):
        buf: RingBuffer[int] = RingBuffer(4)
        assert len(buf) == 0

    def test_len_partial(self):
        buf: RingBuffer[int] = RingBuffer(4)
        buf.push(1)
        buf.push(2)
        assert len(buf) == 2

    def test_len_full(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(1)
        buf.push(2)
        buf.push(3)
        assert len(buf) == 3

    def test_bool_empty_is_false(self):
        buf: RingBuffer[int] = RingBuffer(3)
        assert not buf
        assert bool(buf) is False

    def test_bool_nonempty_is_true(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(1)
        assert buf
        assert bool(buf) is True

    def test_bool_after_pop_to_empty(self):
        buf: RingBuffer[int] = RingBuffer(1)
        buf.push(99)
        buf.pop()
        assert not buf


# ---------------------------------------------------------------------------
# __getitem__ (integer + slice)
# ---------------------------------------------------------------------------


class TestGetItem:
    def test_getitem_int(self):
        buf: RingBuffer[int] = RingBuffer(4)
        for v in (10, 20, 30):
            buf.push(v)
        assert buf[0] == 10
        assert buf[2] == 30

    def test_getitem_negative(self):
        buf: RingBuffer[int] = RingBuffer(4)
        for v in (10, 20, 30):
            buf.push(v)
        assert buf[-1] == 30
        assert buf[-3] == 10

    def test_getitem_out_of_range_returns_none(self):
        buf: RingBuffer[int] = RingBuffer(4)
        buf.push(1)
        assert buf[10] is None

    def test_getitem_slice_basic(self):
        buf: RingBuffer[int] = RingBuffer(5)
        for v in range(5):
            buf.push(v)
        assert buf[1:3] == [1, 2]

    def test_getitem_slice_all(self):
        buf: RingBuffer[int] = RingBuffer(4)
        for v in (7, 8, 9):
            buf.push(v)
        assert buf[:] == [7, 8, 9]

    def test_getitem_slice_empty(self):
        buf: RingBuffer[int] = RingBuffer(4)
        assert buf[:] == []

    def test_getitem_slice_step(self):
        buf: RingBuffer[int] = RingBuffer(6)
        for v in range(6):
            buf.push(v)
        assert buf[::2] == [0, 2, 4]

    def test_getitem_slice_negative_step(self):
        buf: RingBuffer[int] = RingBuffer(5)
        for v in (1, 2, 3, 4, 5):
            buf.push(v)
        assert buf[::-1] == [5, 4, 3, 2, 1]


# ---------------------------------------------------------------------------
# to_list()
# ---------------------------------------------------------------------------


class TestToList:
    def test_to_list_empty(self):
        buf: RingBuffer[int] = RingBuffer(3)
        assert buf.to_list() == []

    def test_to_list_partial(self):
        buf: RingBuffer[int] = RingBuffer(5)
        buf.push(1)
        buf.push(2)
        assert buf.to_list() == [1, 2]

    def test_to_list_after_wrap(self):
        buf: RingBuffer[int] = RingBuffer(3)
        for v in (1, 2, 3, 4):
            buf.push(v)
        assert buf.to_list() == [2, 3, 4]

    def test_to_list_is_snapshot(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(1)
        snapshot = buf.to_list()
        buf.push(2)
        # snapshot should not change
        assert snapshot == [1]

    def test_to_list_after_shifts(self):
        buf: RingBuffer[int] = RingBuffer(4)
        for v in (1, 2, 3, 4):
            buf.push(v)
        buf.shift()  # remove 1
        buf.shift()  # remove 2
        assert buf.to_list() == [3, 4]


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_empty(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.clear()  # should not raise
        assert len(buf) == 0

    def test_clear_nonempty(self):
        buf: RingBuffer[int] = RingBuffer(3)
        for v in (1, 2, 3):
            buf.push(v)
        buf.clear()
        assert len(buf) == 0
        assert buf.is_empty
        assert list(buf) == []

    def test_clear_allows_reuse(self):
        buf: RingBuffer[int] = RingBuffer(2)
        buf.push(1)
        buf.push(2)
        buf.clear()
        buf.push(10)
        buf.push(20)
        assert list(buf) == [10, 20]


# ---------------------------------------------------------------------------
# is_full / is_empty
# ---------------------------------------------------------------------------


class TestProperties:
    def test_is_empty_true_at_start(self):
        buf: RingBuffer[int] = RingBuffer(3)
        assert buf.is_empty

    def test_is_empty_false_after_push(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(1)
        assert not buf.is_empty

    def test_is_full_false_at_start(self):
        buf: RingBuffer[int] = RingBuffer(3)
        assert not buf.is_full

    def test_is_full_true_when_at_capacity(self):
        buf: RingBuffer[int] = RingBuffer(2)
        buf.push(1)
        buf.push(2)
        assert buf.is_full

    def test_is_full_false_after_pop(self):
        buf: RingBuffer[int] = RingBuffer(2)
        buf.push(1)
        buf.push(2)
        buf.pop()
        assert not buf.is_full


# ---------------------------------------------------------------------------
# Capacity-1 edge cases
# ---------------------------------------------------------------------------


class TestCapacityOne:
    def test_push_evicts_self(self):
        buf: RingBuffer[int] = RingBuffer(1)
        buf.push(1)
        evicted = buf.push(2)
        assert evicted == 1
        assert list(buf) == [2]

    def test_pop_empty(self):
        buf: RingBuffer[int] = RingBuffer(1)
        assert buf.pop() is None

    def test_shift_then_push(self):
        buf: RingBuffer[int] = RingBuffer(1)
        buf.push(5)
        assert buf.shift() == 5
        assert buf.is_empty
        buf.push(6)
        assert list(buf) == [6]

    def test_unshift_evicts_self(self):
        buf: RingBuffer[int] = RingBuffer(1)
        buf.push(10)
        evicted = buf.unshift(20)
        assert evicted == 10
        assert list(buf) == [20]

    def test_peek_peek_back_same(self):
        buf: RingBuffer[int] = RingBuffer(1)
        buf.push(42)
        assert buf.peek() == buf.peek_back() == 42


# ---------------------------------------------------------------------------
# Mixed push/pop/shift/unshift sequences
# ---------------------------------------------------------------------------


class TestMixedOperations:
    def test_push_shift_interleaved(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(1)
        buf.push(2)
        assert buf.shift() == 1
        buf.push(3)
        buf.push(4)
        assert list(buf) == [2, 3, 4]

    def test_push_pop_shift_unshift(self):
        buf: RingBuffer[str] = RingBuffer(4)
        buf.push("b")
        buf.push("c")
        buf.unshift("a")  # [a, b, c]
        buf.push("d")     # [a, b, c, d] – full
        assert buf.shift() == "a"
        assert buf.pop() == "d"
        assert list(buf) == ["b", "c"]

    def test_at_consistent_with_list_after_wraps(self):
        buf: RingBuffer[int] = RingBuffer(4)
        for v in range(8):  # wrap multiple times
            buf.push(v)
        expected = list(buf)
        for i, val in enumerate(expected):
            assert buf.at(i) == val

    def test_negative_at_consistent(self):
        buf: RingBuffer[int] = RingBuffer(5)
        for v in (10, 20, 30, 40, 50):
            buf.push(v)
        items = list(buf)
        for i in range(-1, -len(items) - 1, -1):
            assert buf.at(i) == items[i]


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------


class TestRepr:
    def test_repr_empty(self):
        buf: RingBuffer[int] = RingBuffer(3)
        r = repr(buf)
        assert "RingBuffer" in r
        assert "capacity=3" in r
        assert "size=0" in r

    def test_repr_with_items(self):
        buf: RingBuffer[int] = RingBuffer(3)
        buf.push(1)
        buf.push(2)
        r = repr(buf)
        assert "size=2" in r
        assert "1" in r
        assert "2" in r
