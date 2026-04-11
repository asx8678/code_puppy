"""Tests for code_puppy.utils.adaptive_render."""

import json

import pytest  # noqa: F401 — imported for fixture discovery consistency

from code_puppy.utils.adaptive_render import (
    DelimitedTable,  # noqa: F401 — re-exported for isinstance checks in tests
    PayloadKind,
    classify_payload,
    collect_record_columns,
    detect_delimited_table,
    normalize_escaped_whitespace,
    python_repr_to_json,
)


# ---------------------------------------------------------------------------
# python_repr_to_json
# ---------------------------------------------------------------------------


class TestPythonReprToJson:
    def test_simple_dict(self):
        result = python_repr_to_json("{'a': 1, 'b': 2}")
        assert result is not None
        assert json.loads(result) == {"a": 1, "b": 2}

    def test_dict_with_none(self):
        result = python_repr_to_json("{'a': None}")
        assert result is not None
        assert json.loads(result) == {"a": None}

    def test_dict_with_bools(self):
        result = python_repr_to_json("{'a': True, 'b': False}")
        assert result is not None
        assert json.loads(result) == {"a": True, "b": False}

    def test_nested_dict(self):
        result = python_repr_to_json("{'a': {'b': 'c'}}")
        assert result is not None
        assert json.loads(result) == {"a": {"b": "c"}}

    def test_list_of_dicts(self):
        result = python_repr_to_json("[{'a': 1}, {'a': 2}]")
        assert result is not None
        assert json.loads(result) == [{"a": 1}, {"a": 2}]

    def test_tuple_becomes_array(self):
        result = python_repr_to_json("('a', 'b', 'c')")
        assert result is not None
        assert json.loads(result) == ["a", "b", "c"]

    def test_already_valid_json_passthrough(self):
        result = python_repr_to_json('{"a": 1}')
        assert result is not None
        assert json.loads(result) == {"a": 1}

    def test_non_container_returns_none(self):
        assert python_repr_to_json("hello world") is None
        assert python_repr_to_json("42") is None

    def test_empty_string(self):
        assert python_repr_to_json("") is None
        assert python_repr_to_json("   ") is None

    def test_non_string_input(self):
        assert python_repr_to_json(None) is None  # type: ignore[arg-type]
        assert python_repr_to_json(42) is None  # type: ignore[arg-type]

    def test_malformed_returns_none(self):
        assert python_repr_to_json("{'a': 1, 'b':}") is None


# ---------------------------------------------------------------------------
# detect_delimited_table
# ---------------------------------------------------------------------------


class TestDetectDelimitedTable:
    def test_csv_in_text(self):
        text = "Some prose\nname,age,city\nAlice,30,NYC\nBob,25,LA\nBye"
        result = detect_delimited_table(text)
        assert result is not None
        assert result.delimiter == ","
        assert result.header == ["name", "age", "city"]
        assert result.rows == [["Alice", "30", "NYC"], ["Bob", "25", "LA"]]

    def test_tsv(self):
        text = "a\tb\tc\n1\t2\t3\n4\t5\t6"
        result = detect_delimited_table(text)
        assert result is not None
        assert result.delimiter == "\t"

    def test_pipe_table(self):
        text = "| name | age |\n| alice | 30 |\n| bob | 25 |"
        result = detect_delimited_table(text)
        assert result is not None
        assert result.delimiter == "|"
        assert result.header == ["name", "age"]

    def test_too_few_rows(self):
        text = "a,b\n1,2"
        assert detect_delimited_table(text) is None

    def test_inconsistent_columns_rejected(self):
        text = "a,b,c\n1,2\n3,4,5,6"
        assert detect_delimited_table(text) is None

    def test_single_column_rejected(self):
        text = "one\ntwo\nthree\nfour"
        assert detect_delimited_table(text) is None

    def test_empty_input(self):
        assert detect_delimited_table("") is None
        assert detect_delimited_table("   ") is None

    def test_non_string_input(self):
        assert detect_delimited_table(None) is None  # type: ignore[arg-type]

    def test_custom_min_rows(self):
        text = "a,b\n1,2\n3,4"
        result = detect_delimited_table(text, min_rows=3)
        assert result is not None


# ---------------------------------------------------------------------------
# classify_payload
# ---------------------------------------------------------------------------


class TestClassifyPayload:
    def test_none(self):
        assert classify_payload(None) == PayloadKind.EMPTY

    def test_empty_string(self):
        assert classify_payload("") == PayloadKind.EMPTY

    def test_empty_dict(self):
        assert classify_payload({}) == PayloadKind.EMPTY

    def test_empty_list(self):
        assert classify_payload([]) == PayloadKind.EMPTY

    def test_scalar_int(self):
        assert classify_payload(42) == PayloadKind.SCALAR

    def test_scalar_float(self):
        assert classify_payload(3.14) == PayloadKind.SCALAR

    def test_scalar_bool_true(self):
        assert classify_payload(True) == PayloadKind.SCALAR

    def test_scalar_bool_false(self):
        assert classify_payload(False) == PayloadKind.SCALAR

    def test_non_empty_string(self):
        assert classify_payload("hello") == PayloadKind.STRING

    def test_kv_dict_all_scalars(self):
        assert classify_payload({"a": 1, "b": "x", "c": True}) == PayloadKind.KV_DICT

    def test_kv_dict_with_none(self):
        assert classify_payload({"a": 1, "b": None}) == PayloadKind.KV_DICT

    def test_nested_dict(self):
        assert classify_payload({"a": {"b": 1}}) == PayloadKind.NESTED

    def test_record_list(self):
        assert classify_payload([{"a": 1}, {"a": 2, "b": 3}]) == PayloadKind.RECORD_LIST

    def test_mixed_list_scalars(self):
        assert classify_payload([1, 2, 3]) == PayloadKind.MIXED_LIST

    def test_mixed_list_dict_and_string(self):
        assert classify_payload([{"a": 1}, "string"]) == PayloadKind.MIXED_LIST

    def test_tuple_as_list(self):
        assert classify_payload((1, 2, 3)) == PayloadKind.MIXED_LIST


# ---------------------------------------------------------------------------
# collect_record_columns
# ---------------------------------------------------------------------------


class TestCollectRecordColumns:
    def test_homogeneous(self):
        rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        assert collect_record_columns(rows) == ["a", "b"]

    def test_heterogeneous_first_seen_order(self):
        rows = [{"a": 1, "b": 2}, {"b": 3, "c": 4}, {"c": 5, "d": 6}]
        assert collect_record_columns(rows) == ["a", "b", "c", "d"]

    def test_empty_list(self):
        assert collect_record_columns([]) == []

    def test_filters_non_dicts(self):
        rows = [{"a": 1}, "not a dict", {"b": 2}]  # type: ignore[list-item]
        assert collect_record_columns(rows) == ["a", "b"]


# ---------------------------------------------------------------------------
# normalize_escaped_whitespace
# ---------------------------------------------------------------------------


class TestNormalizeEscapedWhitespace:
    def test_literal_newline(self):
        assert normalize_escaped_whitespace("line1\\nline2") == "line1\nline2"

    def test_literal_tab(self):
        assert normalize_escaped_whitespace("a\\tb") == "a\tb"

    def test_mixed(self):
        result = normalize_escaped_whitespace("a\\nb\\tc")
        assert result == "a\nb\tc"

    def test_real_newline_untouched(self):
        assert normalize_escaped_whitespace("a\nb") == "a\nb"

    def test_empty(self):
        assert normalize_escaped_whitespace("") == ""

    def test_non_string_passthrough(self):
        assert normalize_escaped_whitespace(None) is None  # type: ignore[arg-type]
