defmodule CodePuppyControl.Parsing.Parsers.RustParserTest do
  @moduledoc """
  Tests for the Rust parser.
  """
  use ExUnit.Case, async: true

  alias CodePuppyControl.Parsing.Parsers.RustParser

  describe "ParserBehaviour callbacks" do
    test "language/0 returns rust" do
      assert RustParser.language() == "rust"
    end

    test "file_extensions/0 returns .rs" do
      assert RustParser.file_extensions() == [".rs"]
    end

    test "supported?/0 returns true" do
      assert RustParser.supported?() == true
    end
  end

  describe "parse/1 with functions" do
    test "parses simple function definition" do
      source = "fn hello() {}"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert result.language == "rust"
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "hello"
      assert symbol.kind == :function
      assert symbol.line == 1
    end

    test "parses public function" do
      source = "pub fn greet() {}"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "greet"
      assert symbol.kind == :function
      assert symbol.doc == "pub"
    end

    test "parses function with parameters" do
      source = "fn add(a: i32, b: i32) {}"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "add"
      assert symbol.kind == :function
    end

    test "parses multiple function definitions" do
      source = """
      fn foo() {}
      fn bar() {}
      """

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 2

      names = Enum.map(result.symbols, & &1.name)
      assert "foo" in names
      assert "bar" in names
    end
  end

  describe "parse/1 with structs" do
    test "parses simple struct definition" do
      source = "struct Point {}"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "Point"
      assert symbol.kind == :class
      assert symbol.line == 1
    end

    test "parses public struct" do
      source = "pub struct Config {}"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "Config"
      assert symbol.kind == :class
      assert symbol.doc == "pub"
    end
  end

  describe "parse/1 with enums" do
    test "parses simple enum definition" do
      source = "enum Color {}"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "Color"
      assert symbol.kind == :class
    end

    test "parses public enum" do
      source = "pub enum Status {}"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true

      [symbol] = result.symbols
      assert symbol.name == "Status"
      assert symbol.doc == "pub"
    end
  end

  describe "parse/1 with impl blocks" do
    test "parses impl block for type" do
      source = "impl MyStruct {}"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "impl MyStruct"
      assert symbol.kind == :module
    end

    test "parses impl block for trait" do
      source = "impl MyTrait for MyType {}"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "impl MyTrait for MyType"
      assert symbol.kind == :module
    end
  end

  describe "parse/1 with traits" do
    test "parses simple trait definition" do
      source = "trait Printable {}"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "Printable"
      assert symbol.kind == :type
    end

    test "parses public trait" do
      source = "pub trait Drawable {}"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true

      [symbol] = result.symbols
      assert symbol.name == "Drawable"
      assert symbol.doc == "pub"
    end
  end

  describe "parse/1 with modules" do
    test "parses inline module block" do
      source = "mod my_module {}"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "my_module"
      assert symbol.kind == :module
    end

    test "parses module file declaration" do
      source = "mod external;"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "external (file)"
      assert symbol.kind == :module
    end

    test "parses public module" do
      source = "pub mod utils;"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true

      [symbol] = result.symbols
      assert symbol.name == "utils (file)"
      assert symbol.doc == "pub"
    end
  end

  describe "parse/1 with use statements" do
    test "parses simple use statement" do
      source = "use std::io;"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "std::io"
      assert symbol.kind == :import
    end

    test "parses multiple use statements" do
      source = """
      use std::io;
      use std::fs;
      """

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 2

      names = Enum.map(result.symbols, & &1.name)
      assert "std::io" in names
      assert "std::fs" in names
    end
  end

  describe "parse/1 with type aliases" do
    test "parses type alias" do
      source = "type MyInt = i32;"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "MyInt = i32"
      assert symbol.kind == :type
    end

    test "parses public type alias" do
      source = "pub type MyInt = i32;"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true

      [symbol] = result.symbols
      assert symbol.doc == "pub"
      assert symbol.name == "MyInt = i32"
    end
  end

  describe "parse/1 with constants" do
    test "parses const declaration" do
      source = "const MAX_SIZE = 100;"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "MAX_SIZE"
      assert symbol.kind == :constant
    end

    test "parses public const" do
      source = "pub const VERSION = 1;"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true

      [symbol] = result.symbols
      assert symbol.name == "VERSION"
      assert symbol.doc == "pub"
    end
  end

  describe "parse/1 with static items" do
    test "parses static declaration" do
      source = "static COUNTER = 0;"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 1

      [symbol] = result.symbols
      assert symbol.name == "COUNTER"
      assert symbol.kind == :constant
    end

    test "parses mutable static" do
      source = "static mut GLOBAL = 0;"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true

      [symbol] = result.symbols
      assert symbol.name == "GLOBAL"
      assert symbol.doc == "mut"
    end

    test "parses public static" do
      source = "pub static NAME = 42;"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true

      [symbol] = result.symbols
      assert symbol.doc == "pub"
      assert symbol.name == "NAME"
    end
  end

  describe "parse/1 with mixed declarations" do
    test "parses module with multiple items" do
      source = """
      use std::io;

      const PI = 3;

      struct Circle {}

      fn main() {}
      """

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert length(result.symbols) == 4

      kinds = Enum.group_by(result.symbols, & &1.kind)
      assert map_size(kinds) >= 3
    end

    test "returns empty symbols for empty source" do
      source = ""

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert result.symbols == []
    end

    test "returns empty symbols for whitespace-only source" do
      source = "   \n\n   \n"

      {:ok, result} = RustParser.parse(source)

      assert result.success == true
      assert result.symbols == []
    end
  end

  describe "parse/1 error handling" do
    test "handles incomplete input gracefully" do
      source = "fn incomplete("

      result = RustParser.parse(source)

      assert match?({:ok, _}, result)
    end
  end

  describe "registration" do
    test "can be registered with ParserRegistry" do
      assert RustParser.register() == :ok
    end
  end
end
