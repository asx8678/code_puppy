defmodule CodePuppyControl.CodeContext.SymbolInfoTest do
  @moduledoc """
  Tests for the SymbolInfo module.
  """

  use ExUnit.Case, async: true

  alias CodePuppyControl.CodeContext.SymbolInfo

  describe "new/4" do
    test "creates a SymbolInfo with required fields" do
      symbol = SymbolInfo.new("my_func", "function", 10, 20)

      assert symbol.name == "my_func"
      assert symbol.kind == "function"
      assert symbol.start_line == 10
      assert symbol.end_line == 20
      assert symbol.start_col == 0
      assert symbol.end_col == 0
      assert symbol.parent == nil
      assert symbol.docstring == nil
      assert symbol.children == []
    end

    test "creates a SymbolInfo with optional fields" do
      child = SymbolInfo.new("child", "method", 15, 18)

      symbol =
        SymbolInfo.new("parent", "class", 10, 50,
          start_col: 4,
          end_col: 20,
          parent: "OuterClass",
          docstring: "A class",
          children: [child]
        )

      assert symbol.name == "parent"
      assert symbol.kind == "class"
      assert symbol.start_col == 4
      assert symbol.end_col == 20
      assert symbol.parent == "OuterClass"
      assert symbol.docstring == "A class"
      assert symbol.children == [child]
    end
  end

  describe "from_map/1" do
    test "creates SymbolInfo from string-keyed map" do
      map = %{
        "name" => "my_func",
        "kind" => "function",
        "start_line" => 10,
        "end_line" => 20
      }

      symbol = SymbolInfo.from_map(map)

      assert symbol.name == "my_func"
      assert symbol.kind == "function"
      assert symbol.start_line == 10
      assert symbol.end_line == 20
    end

    test "creates SymbolInfo from atom-keyed map" do
      map = %{
        name: "my_func",
        kind: "function",
        start_line: 10,
        end_line: 20
      }

      symbol = SymbolInfo.from_map(map)

      assert symbol.name == "my_func"
    end

    test "handles nested children" do
      map = %{
        "name" => "Parent",
        "kind" => "class",
        "start_line" => 1,
        "end_line" => 50,
        "children" => [
          %{
            "name" => "Child",
            "kind" => "method",
            "start_line" => 10,
            "end_line" => 20
          }
        ]
      }

      symbol = SymbolInfo.from_map(map)

      assert symbol.name == "Parent"
      assert length(symbol.children) == 1
      child = hd(symbol.children)
      assert child.name == "Child"
      assert child.kind == "method"
    end

    test "handles nil values gracefully" do
      map = %{
        "name" => "test",
        "kind" => "function"
      }

      symbol = SymbolInfo.from_map(map)

      assert symbol.name == "test"
      assert symbol.start_line == 0
      assert symbol.end_line == 0
    end
  end

  describe "to_map/1" do
    test "converts SymbolInfo to map" do
      symbol = SymbolInfo.new("my_func", "function", 10, 20)
      map = SymbolInfo.to_map(symbol)

      assert map["name"] == "my_func"
      assert map["kind"] == "function"
      assert map["start_line"] == 10
      assert map["end_line"] == 20
      assert map["children"] == []
    end

    test "converts nested children" do
      child = SymbolInfo.new("child", "method", 15, 18)
      parent = SymbolInfo.new("parent", "class", 10, 50, children: [child])

      map = SymbolInfo.to_map(parent)

      assert length(map["children"]) == 1
      child_map = hd(map["children"])
      assert child_map["name"] == "child"
    end
  end

  describe "line_range/1" do
    test "returns line range as tuple" do
      symbol = SymbolInfo.new("test", "function", 10, 25)

      assert SymbolInfo.line_range(symbol) == {10, 25}
    end
  end

  describe "top_level?/1" do
    test "returns true when parent is nil" do
      symbol = SymbolInfo.new("test", "function", 1, 10)

      assert SymbolInfo.top_level?(symbol)
    end

    test "returns false when parent is set" do
      symbol = SymbolInfo.new("test", "method", 1, 10, parent: "SomeClass")

      refute SymbolInfo.top_level?(symbol)
    end
  end

  describe "size_lines/1" do
    test "calculates size correctly" do
      symbol = SymbolInfo.new("test", "function", 10, 15)

      # Lines 10-15 inclusive = 6 lines
      assert SymbolInfo.size_lines(symbol) == 6
    end

    test "handles single line" do
      symbol = SymbolInfo.new("test", "variable", 5, 5)

      assert SymbolInfo.size_lines(symbol) == 1
    end
  end

  describe "all_descendants/1" do
    test "returns all nested symbols" do
      grandchild = SymbolInfo.new("grandchild", "variable", 20, 22)
      child = SymbolInfo.new("child", "method", 15, 18, children: [grandchild])
      parent = SymbolInfo.new("parent", "class", 10, 50, children: [child])

      descendants = SymbolInfo.all_descendants(parent)

      assert length(descendants) == 2
      assert Enum.any?(descendants, &(&1.name == "child"))
      assert Enum.any?(descendants, &(&1.name == "grandchild"))
    end

    test "returns empty list for symbol without children" do
      symbol = SymbolInfo.new("test", "function", 1, 10)

      assert SymbolInfo.all_descendants(symbol) == []
    end
  end

  describe "find_by_name/2" do
    test "finds symbol by name" do
      symbol = SymbolInfo.new("target", "function", 1, 10)

      assert SymbolInfo.find_by_name(symbol, "target") == symbol
    end

    test "finds nested symbol by name" do
      child = SymbolInfo.new("child", "method", 15, 18)
      parent = SymbolInfo.new("parent", "class", 10, 50, children: [child])

      assert SymbolInfo.find_by_name(parent, "child").name == "child"
    end

    test "returns nil when not found" do
      symbol = SymbolInfo.new("test", "function", 1, 10)

      assert SymbolInfo.find_by_name(symbol, "nonexistent") == nil
    end
  end

  describe "filter_by_kind/2" do
    test "filters by single kind" do
      symbols = [
        SymbolInfo.new("Class1", "class", 1, 10),
        SymbolInfo.new("func1", "function", 15, 20),
        SymbolInfo.new("Class2", "class", 25, 35)
      ]

      classes = SymbolInfo.filter_by_kind(symbols, "class")

      assert length(classes) == 2
      assert Enum.all?(classes, &(&1.kind == "class"))
    end

    test "filters by multiple kinds" do
      symbols = [
        SymbolInfo.new("Class1", "class", 1, 10),
        SymbolInfo.new("func1", "function", 15, 20),
        SymbolInfo.new("Interface1", "interface", 25, 35),
        SymbolInfo.new("var1", "variable", 40, 40)
      ]

      types = SymbolInfo.filter_by_kind(symbols, ["class", "interface"])

      assert length(types) == 2
    end
  end
end
