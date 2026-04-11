"""Tests for tool_schema module."""

from typing import Annotated

import pytest

from code_puppy.tool_schema import (
    ToolParameter,
    ToolSchema,
    get_tool_schema,
    infer_schema_from_function,
    is_tool_function,
    tool,
)


class TestInferSchemaFromFunction:
    """Test schema inference from Python functions."""

    def test_simple_function(self):
        """Test basic function with primitives."""

        def simple_func(path: str, count: int) -> str:
            """A simple function."""
            return "result"

        schema = infer_schema_from_function(simple_func)

        assert schema.name == "simple_func"
        assert schema.description == "A simple function."
        assert len(schema.parameters) == 2
        assert schema.parameters[0].name == "path"
        assert schema.parameters[0].type == "string"
        assert schema.parameters[1].name == "count"
        assert schema.parameters[1].type == "integer"
        assert schema.required == ["path", "count"]

    def test_optional_parameters(self):
        """Test function with optional/default parameters."""

        def func_with_defaults(
            required: str,
            optional: str = "default_value",
            count: int = 42,
        ) -> str:
            """Function with defaults."""
            return "result"

        schema = infer_schema_from_function(func_with_defaults)

        assert schema.required == ["required"]

        # Find optional param
        opt_param = next(p for p in schema.parameters if p.name == "optional")
        assert not opt_param.required
        assert opt_param.default == "default_value"

    def test_all_primitive_types(self):
        """Test all supported primitive types."""

        def type_test(
            s: str,
            i: int,
            f: float,
            b: bool,
        ) -> None:
            """Test all types."""
            pass

        schema = infer_schema_from_function(type_test)

        types_found = {p.name: p.type for p in schema.parameters}
        assert types_found["s"] == "string"
        assert types_found["i"] == "integer"
        assert types_found["f"] == "number"
        assert types_found["b"] == "boolean"

    def test_list_and_dict_types(self):
        """Test list and dict type inference."""

        def collection_func(
            items: list[str],
            mapping: dict[str, int],
        ) -> None:
            """Collections."""
            pass

        schema = infer_schema_from_function(collection_func)

        items_param = next(p for p in schema.parameters if p.name == "items")
        assert items_param.type == "array"
        assert items_param.item_schema == {"type": "string"}

        mapping_param = next(p for p in schema.parameters if p.name == "mapping")
        assert mapping_param.type == "object"

    def test_optional_union_type(self):
        """Test T | None handling."""

        def with_optional(name: str | None = None) -> None:
            """With optional."""
            pass

        schema = infer_schema_from_function(with_optional)

        param = schema.parameters[0]
        assert param.type == "string"
        assert not param.required

    def test_annotated_descriptions(self):
        """Test Annotated type for descriptions."""

        def with_annotations(
            path: Annotated[str, "File path to read"],
            encoding: Annotated[str, "Character encoding"] = "utf-8",
        ) -> str:
            """Read file."""
            return "content"

        schema = infer_schema_from_function(with_annotations)

        path_param = next(p for p in schema.parameters if p.name == "path")
        assert path_param.description == "File path to read"

        encoding_param = next(p for p in schema.parameters if p.name == "encoding")
        assert encoding_param.description == "Character encoding"

    def test_custom_name(self):
        """Test custom tool name override."""

        def my_function() -> None:
            """Docstring."""
            pass

        schema = infer_schema_from_function(my_function, name="custom_name")
        assert schema.name == "custom_name"

    def test_custom_description(self):
        """Test custom description override."""

        def my_function() -> None:
            """Original docstring."""
            pass

        schema = infer_schema_from_function(my_function, description="Custom desc")
        assert schema.description == "Custom desc"

    def test_no_docstring(self):
        """Test function without docstring."""

        def no_docs(x: int) -> None:
            pass

        schema = infer_schema_from_function(no_docs)
        assert "no_docs" in schema.description

    def test_multiline_docstring(self):
        """Test that only first paragraph is used."""

        def multi_doc(x: int) -> None:
            """First paragraph.

            Second paragraph should be ignored.
            """
            pass

        schema = infer_schema_from_function(multi_doc)
        assert schema.description == "First paragraph."


class TestToolSchema:
    """Test ToolSchema dataclass."""

    def test_to_json_schema(self):
        """Test JSON Schema generation."""
        schema = ToolSchema(
            name="test",
            description="A test",
            parameters=[
                ToolParameter(name="x", type="integer", required=True),
                ToolParameter(name="y", type="string", required=False),
            ],
            required=["x"],
        )

        json_schema = schema.to_json_schema()

        assert json_schema["type"] == "object"
        assert "properties" in json_schema
        assert json_schema["properties"]["x"]["type"] == "integer"
        assert json_schema["properties"]["y"]["type"] == "string"
        assert json_schema["required"] == ["x"]

    def test_to_tool_definition(self):
        """Test tool definition format."""
        schema = ToolSchema(
            name="test_tool",
            description="Does something",
            parameters=[],
            required=[],
        )

        definition = schema.to_tool_definition()

        assert definition["name"] == "test_tool"
        assert definition["description"] == "Does something"
        assert "parameters" in definition


class TestToolParameter:
    """Test ToolParameter dataclass."""

    def test_to_json_schema_with_description(self):
        """Test parameter with description."""
        param = ToolParameter(
            name="path",
            type="string",
            description="File path",
        )

        schema = param.to_json_schema()

        assert schema["type"] == "string"
        assert schema["description"] == "File path"

    def test_to_json_schema_with_enum(self):
        """Test parameter with enum."""
        param = ToolParameter(
            name="format",
            type="string",
            enum=["json", "yaml", "xml"],
        )

        schema = param.to_json_schema()

        assert schema["enum"] == ["json", "yaml", "xml"]

    def test_to_json_schema_with_items(self):
        """Test array parameter with item schema."""
        param = ToolParameter(
            name="tags",
            type="array",
            item_schema={"type": "string"},
        )

        schema = param.to_json_schema()

        assert schema["type"] == "array"
        assert schema["items"]["type"] == "string"


class TestToolDecorator:
    """Test @tool decorator."""

    def test_tool_decorator_marks_function(self):
        """Test that @tool marks function as tool."""

        @tool()
        def my_tool(x: int) -> str:
            """My tool."""
            return "result"

        assert is_tool_function(my_tool)

    def test_tool_decorator_attaches_schema(self):
        """Test that @tool attaches schema."""

        @tool()
        def my_tool(x: int, y: str = "default") -> str:
            """My tool description."""
            return "result"

        schema = get_tool_schema(my_tool)

        assert schema is not None
        assert schema.name == "my_tool"
        assert schema.description == "My tool description."

    def test_tool_decorator_custom_name(self):
        """Test @tool with custom name."""

        @tool(name="custom_tool_name")
        def original_name() -> None:
            """Description."""
            pass

        schema = get_tool_schema(original_name)
        assert schema.name == "custom_tool_name"

    def test_tool_decorator_custom_description(self):
        """Test @tool with custom description."""

        @tool(description="Custom desc override")
        def my_func() -> None:
            """Original description."""
            pass

        schema = get_tool_schema(my_func)
        assert schema.description == "Custom desc override"

    def test_undecorated_function(self):
        """Test that undecorated function is not a tool."""

        def regular_func() -> None:
            pass

        assert not is_tool_function(regular_func)
        assert get_tool_schema(regular_func) is None


class TestIntegration:
    """Integration tests for real-world scenarios."""

    def test_file_read_tool(self):
        """Test file read tool schema."""
        from typing import Optional as Opt  # Local import to avoid annotation issues

        def read_file(
            path: Annotated[str, "Path to the file"],
            encoding: Annotated[str, "Character encoding"] = "utf-8",
            limit: Annotated[Opt[int], "Max lines to read"] = None,
        ) -> str:
            """Read contents of a file."""
            return "content"

        schema = infer_schema_from_function(read_file)

        assert schema.name == "read_file"
        assert "path" in [p.name for p in schema.parameters if p.required]

        path_param = next(p for p in schema.parameters if p.name == "path")
        assert path_param.description == "Path to the file"
        assert path_param.required

    def test_search_tool(self):
        """Test search tool with complex types."""

        def search_files(
            query: str,
            paths: list[str],
            include_hidden: bool = False,
            max_results: int = 100,
        ) -> list[dict[str, str]]:
            """Search for files matching query."""
            return []

        schema = infer_schema_from_function(search_files)

        # Check required params
        assert "query" in schema.required
        assert "paths" in schema.required

        # Check types
        paths_param = next(p for p in schema.parameters if p.name == "paths")
        assert paths_param.type == "array"
        assert paths_param.item_schema == {"type": "string"}

        # Check optionals not in required
        assert "include_hidden" not in schema.required
        assert "max_results" not in schema.required

    def test_nested_list_type(self):
        """Test nested list types."""

        def matrix_op(data: list[list[int]]) -> None:
            """Matrix operation."""
            pass

        schema = infer_schema_from_function(matrix_op)

        data_param = schema.parameters[0]
        assert data_param.type == "array"
        assert data_param.item_schema == {"type": "array"}

    def test_boolean_before_int(self):
        """Test that bool is correctly identified (not int)."""

        def bool_test(flag: bool) -> None:
            """Test."""
            pass

        schema = infer_schema_from_function(bool_test)

        assert schema.parameters[0].type == "boolean"


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_function(self):
        """Test function with no parameters."""

        def no_params() -> None:
            """No params."""
            pass

        schema = infer_schema_from_function(no_params)

        assert len(schema.parameters) == 0
        assert schema.required == []

    def test_any_type(self):
        """Test Any type handling."""
        from typing import Any as AnyType  # Local import

        def any_param(data: AnyType) -> None:
            """Any."""
            pass

        schema = infer_schema_from_function(any_param)

        assert schema.parameters[0].type == "object"

    def test_union_type_complex(self):
        """Test complex union types fallback to object."""

        def union_param(x: int | str | None) -> None:
            """Union."""
            pass

        schema = infer_schema_from_function(union_param)

        # Complex unions fall back to object
        assert schema.parameters[0].type == "object"

    def test_class_method_skips_self(self):
        """Test that self is skipped for methods."""

        class MyClass:
            def method(self, x: int) -> str:
                """Method doc."""
                return "result"

        schema = infer_schema_from_function(MyClass.method)

        param_names = [p.name for p in schema.parameters]
        assert "self" not in param_names
        assert "x" in param_names
