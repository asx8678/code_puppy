defmodule CodePuppyControl.CodeContext.FileOutlineTest do
  @moduledoc """
  Tests for the FileOutline module.
  """

  use ExUnit.Case, async: true

  alias CodePuppyControl.CodeContext.{FileOutline, SymbolInfo}

  describe "new/2" do
    test "creates a FileOutline with required language" do
      outline = FileOutline.new("python")

      assert outline.language == "python"
      assert outline.symbols == []
      assert outline.extraction_time_ms == 0.0
      assert outline.success == true
      assert outline.errors == []
    end

    test "creates a FileOutline with optional fields" do
      symbols = [SymbolInfo.new("test", "function", 1, 10)]

      outline =
        FileOutline.new("elixir",
          symbols: symbols,
          extraction_time_ms: 50.0,
          success: true,
          errors: []
        )

      assert outline.language == "elixir"
      assert outline.symbols == symbols
      assert outline.extraction_time_ms == 50.0
    end
  end

  describe "from_map/1" do
    test "creates FileOutline from string-keyed map" do
      map = %{
        "language" => "python",
        "symbols" => [],
        "extraction_time_ms" => 25.0,
        "success" => true,
        "errors" => []
      }

      outline = FileOutline.from_map(map)

      assert outline.language == "python"
      assert outline.extraction_time_ms == 25.0
      assert outline.success == true
    end

    test "creates FileOutline from atom-keyed map" do
      map = %{
        language: "elixir",
        symbols: [],
        success: true
      }

      outline = FileOutline.from_map(map)

      assert outline.language == "elixir"
    end

    test "handles symbol maps in children" do
      map = %{
        "language" => "python",
        "symbols" => [
          %{
            "name" => "my_func",
            "kind" => "function",
            "start_line" => 10,
            "end_line" => 20
          }
        ],
        "success" => true
      }

      outline = FileOutline.from_map(map)

      assert length(outline.symbols) == 1
      symbol = hd(outline.symbols)
      assert symbol.name == "my_func"
    end

    test "handles errors as list" do
      map = %{
        "language" => "unknown",
        "symbols" => [],
        "success" => false,
        "errors" => ["Failed to parse"]
      }

      outline = FileOutline.from_map(map)

      assert outline.errors == ["Failed to parse"]
    end

    test "converts non-list errors to list" do
      map = %{
        "language" => "unknown",
        "symbols" => [],
        "success" => false,
        "errors" => "Single error"
      }

      outline = FileOutline.from_map(map)

      assert outline.errors == ["Single error"]
    end
  end

  describe "to_map/1" do
    test "converts FileOutline to map" do
      outline = FileOutline.new("python", symbols: [SymbolInfo.new("test", "function", 1, 10)])

      map = FileOutline.to_map(outline)

      assert map["language"] == "python"
      assert is_list(map["symbols"])
      assert map["success"] == true
    end
  end

  describe "top_level_symbols/1" do
    test "returns symbols without parents" do
      outline = %FileOutline{
        language: "python",
        symbols: [
          SymbolInfo.new("global_func", "function", 1, 10, parent: nil),
          SymbolInfo.new("method", "method", 15, 20, parent: "SomeClass")
        ]
      }

      top_level = FileOutline.top_level_symbols(outline)

      assert length(top_level) == 1
      assert hd(top_level).name == "global_func"
    end
  end

  describe "classes/1" do
    test "returns class-like symbols" do
      outline = %FileOutline{
        language: "python",
        symbols: [
          SymbolInfo.new("MyClass", "class", 1, 50),
          SymbolInfo.new("MyStruct", "struct", 60, 100),
          SymbolInfo.new("my_func", "function", 110, 120),
          SymbolInfo.new("MyEnum", "enum", 130, 150)
        ]
      }

      classes = FileOutline.classes(outline)

      assert length(classes) == 3
      assert Enum.any?(classes, &(&1.name == "MyClass"))
      assert Enum.any?(classes, &(&1.name == "MyStruct"))
      assert Enum.any?(classes, &(&1.name == "MyEnum"))
    end
  end

  describe "functions/1" do
    test "returns function-like symbols" do
      outline = %FileOutline{
        language: "python",
        symbols: [
          SymbolInfo.new("global_func", "function", 1, 10),
          SymbolInfo.new("method", "method", 15, 20),
          SymbolInfo.new("MyClass", "class", 25, 50)
        ]
      }

      functions = FileOutline.functions(outline)

      assert length(functions) == 2
      assert Enum.any?(functions, &(&1.kind == "function"))
      assert Enum.any?(functions, &(&1.kind == "method"))
    end
  end

  describe "imports/1" do
    test "returns import symbols" do
      outline = %FileOutline{
        language: "python",
        symbols: [
          SymbolInfo.new("os", "import", 1, 1),
          SymbolInfo.new("sys", "import", 2, 2),
          SymbolInfo.new("my_func", "function", 5, 10)
        ]
      }

      imports = FileOutline.imports(outline)

      assert length(imports) == 2
      assert Enum.all?(imports, &(&1.kind == "import"))
    end
  end

  describe "get_symbol_by_name/2" do
    test "finds top-level symbol by name" do
      outline = %FileOutline{
        language: "python",
        symbols: [
          SymbolInfo.new("target", "function", 1, 10),
          SymbolInfo.new("other", "function", 15, 20)
        ]
      }

      found = FileOutline.get_symbol_by_name(outline, "target")

      assert found.name == "target"
    end

    test "finds nested symbol by name" do
      child = SymbolInfo.new("child", "method", 15, 18)
      parent = SymbolInfo.new("parent", "class", 10, 50, children: [child])

      outline = %FileOutline{
        language: "python",
        symbols: [parent]
      }

      found = FileOutline.get_symbol_by_name(outline, "child")

      assert found.name == "child"
    end

    test "returns nil when not found" do
      outline = %FileOutline{
        language: "python",
        symbols: [SymbolInfo.new("test", "function", 1, 10)]
      }

      assert FileOutline.get_symbol_by_name(outline, "nonexistent") == nil
    end
  end

  describe "get_symbols_in_range/3" do
    test "returns symbols within line range" do
      outline = %FileOutline{
        language: "python",
        symbols: [
          SymbolInfo.new("early", "function", 1, 5),
          SymbolInfo.new("target", "function", 10, 20),
          SymbolInfo.new("late", "function", 30, 40)
        ]
      }

      in_range = FileOutline.get_symbols_in_range(outline, 8, 25)

      assert length(in_range) == 1
      assert hd(in_range).name == "target"
    end
  end

  describe "total_symbol_count/1" do
    test "counts all symbols including nested" do
      grandchild = SymbolInfo.new("grandchild", "variable", 20, 22)
      child = SymbolInfo.new("child", "method", 15, 18, children: [grandchild])
      parent = SymbolInfo.new("parent", "class", 10, 50, children: [child])

      outline = %FileOutline{
        language: "python",
        symbols: [parent, SymbolInfo.new("other", "function", 60, 70)]
      }

      count = FileOutline.total_symbol_count(outline)

      # parent (1) + child (1) + grandchild (1) + other (1) = 4
      assert count == 4
    end

    test "returns 0 for empty outline" do
      outline = %FileOutline{language: "python", symbols: []}

      assert FileOutline.total_symbol_count(outline) == 0
    end
  end

  describe "limit_depth/2" do
    test "limits symbol hierarchy to max depth" do
      level3 = SymbolInfo.new("level3", "variable", 30, 32)
      level2 = SymbolInfo.new("level2", "method", 20, 28, children: [level3])
      level1 = SymbolInfo.new("level1", "method", 15, 18, children: [level2])
      root = SymbolInfo.new("root", "class", 10, 50, children: [level1])

      outline = %FileOutline{language: "python", symbols: [root]}

      limited = FileOutline.limit_depth(outline, 2)

      # At depth 2, level2's children should be empty
      limited_root = hd(limited.symbols)
      limited_level1 = hd(limited_root.children)
      assert limited_level1.children == []
    end

    test "returns unchanged outline when depth is sufficient" do
      symbol = SymbolInfo.new("test", "function", 1, 10)
      outline = %FileOutline{language: "python", symbols: [symbol]}

      limited = FileOutline.limit_depth(outline, 5)

      assert limited.symbols == outline.symbols
    end
  end
end
