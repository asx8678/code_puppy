"""Tests for llm_parsing utilities.

Tests the robust JSON extraction from LLM text outputs.
"""

import pytest
from code_puppy.utils.llm_parsing import extract_json_from_text


class TestExtractJsonFromText:
    """Test suite for extract_json_from_text function."""

    def test_plain_json_object(self):
        """Test parsing a plain JSON object."""
        result = extract_json_from_text('{"key": "value", "number": 42}')
        assert result == {"key": "value", "number": 42}

    def test_plain_json_array(self):
        """Test parsing a plain JSON array."""
        result = extract_json_from_text('[1, 2, 3, "four", 5.5]')
        assert result == [1, 2, 3, "four", 5.5]

    def test_fenced_json_with_json_annotation(self):
        """Test parsing JSON inside markdown fences with 'json' annotation."""
        text = '```json\n{"key": "value"}\n```'
        result = extract_json_from_text(text)
        assert result == {"key": "value"}

    def test_fenced_json_without_annotation(self):
        """Test parsing JSON inside plain markdown fences."""
        text = '```\n{"key": "value"}\n```'
        result = extract_json_from_text(text)
        assert result == {"key": "value"}

    def test_fenced_array_with_json_annotation(self):
        """Test parsing array inside markdown fences with 'json' annotation."""
        text = '```json\n[1, 2, 3]\n```'
        result = extract_json_from_text(text)
        assert result == [1, 2, 3]

    def test_fenced_array_without_annotation(self):
        """Test parsing array inside plain markdown fences."""
        text = '```\n[1, 2, 3]\n```'
        result = extract_json_from_text(text)
        assert result == [1, 2, 3]

    def test_prose_before_json(self):
        """Test extracting JSON when preceded by prose text."""
        text = 'Here is the data you requested: {"result": "success", "count": 5}'
        result = extract_json_from_text(text)
        assert result == {"result": "success", "count": 5}

    def test_prose_after_json(self):
        """Test extracting JSON when followed by prose text."""
        text = '{"result": "success", "count": 5} Let me know if you need more!'
        result = extract_json_from_text(text)
        assert result == {"result": "success", "count": 5}

    def test_prose_before_and_after_json(self):
        """Test extracting JSON surrounded by prose on both sides."""
        text = 'Here is the data: {"result": "success"} Hope this helps!'
        result = extract_json_from_text(text)
        assert result == {"result": "success"}

    def test_multiple_candidates_returns_first_valid(self):
        """Test that when multiple JSON candidates exist, first valid one is returned."""
        text = '{"first": 1} some text {"second": 2}'
        result = extract_json_from_text(text)
        # Should return the first valid JSON found
        assert result == {"first": 1}

    def test_multiple_arrays_returns_first_valid(self):
        """Test that when multiple array candidates exist, first valid one is returned."""
        text = '[1, 2, 3] some text [4, 5, 6]'
        result = extract_json_from_text(text)
        assert result == [1, 2, 3]

    def test_malformed_json_returns_none(self):
        """Test that malformed JSON returns None, never raises."""
        assert extract_json_from_text('{invalid json}') is None
        assert extract_json_from_text('{"unclosed": "string') is None
        assert extract_json_from_text('{trailing,}') is None
        assert extract_json_from_text('not json at all') is None

    def test_none_input_returns_none(self):
        """Test that None input returns None safely."""
        assert extract_json_from_text(None) is None

    def test_empty_string_returns_none(self):
        """Test that empty string input returns None."""
        assert extract_json_from_text('') is None
        assert extract_json_from_text('   ') is None
        assert extract_json_from_text('\n\t  ') is None

    def test_whitespace_only_fenced_returns_none(self):
        """Test that fenced but empty/whitespace content returns None."""
        assert extract_json_from_text('```json\n   \n```') is None
        assert extract_json_from_text('```\n\n```') is None

    def test_nested_objects(self):
        """Test parsing nested JSON objects."""
        text = '{"outer": {"inner": {"deep": "value"}}}'
        result = extract_json_from_text(text)
        assert result == {"outer": {"inner": {"deep": "value"}}}

    def test_nested_arrays(self):
        """Test parsing nested JSON arrays."""
        text = '[[1, 2], [3, 4], [5, 6]]'
        result = extract_json_from_text(text)
        assert result == [[1, 2], [3, 4], [5, 6]]

    def test_nested_mixed(self):
        """Test parsing mixed nested structures (objects containing arrays)."""
        text = '{"items": [1, 2, 3], "nested": {"arr": ["a", "b"]}}'
        result = extract_json_from_text(text)
        assert result == {"items": [1, 2, 3], "nested": {"arr": ["a", "b"]}}

    def test_json_with_special_characters(self):
        """Test parsing JSON with special characters and escaping."""
        text = '{"quote": "she said \\"hello\\"", "newline": "line1\\nline2"}'
        result = extract_json_from_text(text)
        assert result == {"quote": 'she said "hello"', "newline": "line1\nline2"}

    def test_json_with_unicode(self):
        """Test parsing JSON with unicode characters."""
        text = '{"emoji": "🐶", "chinese": "你好"}'
        result = extract_json_from_text(text)
        assert result == {"emoji": "🐶", "chinese": "你好"}

    def test_json_with_null_true_false(self):
        """Test parsing JSON with null, true, false literals."""
        text = '{"active": true, "deleted": false, "value": null}'
        result = extract_json_from_text(text)
        assert result == {"active": True, "deleted": False, "value": None}

    def test_single_quoted_json_not_parsed(self):
        """Test that single-quoted JSON (invalid) is not parsed."""
        # Single quotes aren't valid JSON - should return None
        assert extract_json_from_text("{'key': 'value'}") is None

    def test_partial_json_in_prose(self):
        """Test handling prose that looks like JSON but isn't."""
        text = 'The config file uses {key: value} syntax which is not valid JSON.'
        # This shouldn't match because the regex expects proper JSON structure
        result = extract_json_from_text(text)
        # The inner part isn't valid JSON, so it should fail
        assert result is None

    def test_json_with_newlines_in_fences(self):
        """Test parsing JSON with internal newlines inside code fences."""
        text = '''```json
{
    "key": "value",
    "array": [1, 2, 3]
}
```'''
        result = extract_json_from_text(text)
        assert result == {"key": "value", "array": [1, 2, 3]}

    def test_case_insensitive_fence(self):
        """Test that 'JSON' and 'Json' annotations work."""
        text1 = '```JSON\n{"key": "value"}\n```'
        text2 = '```Json\n{"key": "value"}\n```'
        assert extract_json_from_text(text1) == {"key": "value"}
        assert extract_json_from_text(text2) == {"key": "value"}

    def test_scalars(self):
        """Test parsing scalar JSON values."""
        assert extract_json_from_text('"just a string"') == "just a string"
        assert extract_json_from_text('42') == 42
        assert extract_json_from_text('3.14') == 3.14
        assert extract_json_from_text('true') is True
        assert extract_json_from_text('false') is False
        assert extract_json_from_text('null') is None

    def test_scalar_in_fences(self):
        """Test parsing scalar values inside fences."""
        text = '```json\n"string value"\n```'
        assert extract_json_from_text(text) == "string value"

    def test_empty_object_and_array(self):
        """Test parsing empty JSON structures."""
        assert extract_json_from_text('{}') == {}
        assert extract_json_from_text('[]') == []
        assert extract_json_from_text('```json\n{}\n```') == {}
        assert extract_json_from_text('```json\n[]\n```') == []

    def test_large_numbers(self):
        """Test parsing JSON with large numbers."""
        text = '{"big": 123456789012345, "decimal": 0.000000001}'
        result = extract_json_from_text(text)
        assert result == {"big": 123456789012345, "decimal": 0.000000001}

    def test_array_of_objects(self):
        """Test parsing array containing objects."""
        text = '[{"id": 1}, {"id": 2}, {"id": 3}]'
        result = extract_json_from_text(text)
        assert result == [{"id": 1}, {"id": 2}, {"id": 3}]

    def test_prose_with_braces_but_no_valid_json(self):
        """Test prose containing braces that aren't valid JSON."""
        text = 'The function foo() { return bar; } is defined here.'
        result = extract_json_from_text(text)
        # The regex will capture { return bar; } which isn't valid JSON
        assert result is None

    def test_json_with_trailing_content_in_fences(self):
        """Test JSON code fences with prose after the closing fence."""
        text = '```json\n{"key": "value"}\n```\n\nDoes this help?'
        result = extract_json_from_text(text)
        assert result == {"key": "value"}


class TestExtractJsonFromTextEdgeCases:
    """Additional edge case tests."""

    def test_multiple_objects_returns_first(self):
        """Test that first valid object is returned when multiple exist."""
        text = '{"a": 1}{"b": 2}'
        result = extract_json_from_text(text)
        # Strategy 1 (raw parse) will parse the first object only
        assert result == {"a": 1}

    def test_escaped_quotes_in_prose(self):
        """Test JSON with escaped quotes within prose context."""
        text = 'The result is {"message": "It\'s working!"} - great!'
        result = extract_json_from_text(text)
        assert result == {"message": "It's working!"}

    def test_deeply_nested_structure(self):
        """Test parsing deeply nested JSON structures."""
        text = '{"a": {"b": {"c": {"d": {"e": "deep"}}}}}'
        result = extract_json_from_text(text)
        assert result == {"a": {"b": {"c": {"d": {"e": "deep"}}}}}

    def test_json_with_arrays_of_mixed_types(self):
        """Test parsing arrays with mixed types."""
        text = '[1, "two", 3.0, true, null, {"nested": "object"}]'
        result = extract_json_from_text(text)
        assert result == [1, "two", 3.0, True, None, {"nested": "object"}]

    def test_invalid_json_followed_by_valid_json(self):
        """Test that valid JSON after invalid JSON is still found."""
        text = '{invalid} {"valid": "json"}'
        result = extract_json_from_text(text)
        # Strategy 3 should find the second object
        assert result == {"valid": "json"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
