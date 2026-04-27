defmodule CodePuppyControl.Tools.FileModifications.ValidationTest do
  @moduledoc "Tests for Validation — post-edit syntax validation."

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.FileModifications.Validation

  describe "validatable_extension?/1" do
    test "recognizes Elixir extensions" do
      assert Validation.validatable_extension?("/tmp/file.ex") == true
      assert Validation.validatable_extension?("/tmp/file.exs") == true
    end

    test "recognizes Erlang extensions" do
      assert Validation.validatable_extension?("/tmp/file.erl") == true
      assert Validation.validatable_extension?("/tmp/file.hrl") == true
    end

    test "recognizes JSON extension" do
      assert Validation.validatable_extension?("/tmp/file.json") == true
    end

    test "recognizes Python/JS/TS/Rust extensions" do
      assert Validation.validatable_extension?("/tmp/file.py") == true
      assert Validation.validatable_extension?("/tmp/file.js") == true
      assert Validation.validatable_extension?("/tmp/file.ts") == true
      assert Validation.validatable_extension?("/tmp/file.tsx") == true
      assert Validation.validatable_extension?("/tmp/file.rs") == true
    end

    test "rejects non-code extensions" do
      assert Validation.validatable_extension?("/tmp/file.txt") == false
      assert Validation.validatable_extension?("/tmp/file.md") == false
      assert Validation.validatable_extension?("/tmp/file.csv") == false
    end

    test "is case-insensitive" do
      # Extension comparison uses downcase
      assert Validation.validatable_extension?("/tmp/file.EX") == true
    end
  end

  describe "maybe_attach_warning/2" do
    test "skips validation for failed operations" do
      result = %{success: false, path: "/tmp/test.ex", message: "failed"}
      assert Validation.maybe_attach_warning(result, "/tmp/test.ex") == result
    end

    test "passes through for non-validatable extensions" do
      result = %{success: true, path: "/tmp/test.txt"}
      assert Validation.maybe_attach_warning(result, "/tmp/test.txt") == result
    end

    test "adds syntax_warning for invalid Elixir syntax" do
      # Write invalid Elixir to a temp file to test validation
      path = Path.join(System.tmp_dir!(), "validation_test_#{:erlang.unique_integer([:positive])}.ex")
      File.write!(path, "defmodule Foo do\n  def bar(\nend")  # Missing closing paren

      result = %{success: true, path: path}
      result = Validation.maybe_attach_warning(result, path)

      # Should have a syntax_warning key
      assert Map.has_key?(result, :syntax_warning)

      File.rm(path)
    end

    test "does not add warning for valid Elixir syntax" do
      path = Path.join(System.tmp_dir!(), "validation_valid_test_#{:erlang.unique_integer([:positive])}.ex")
      File.write!(path, "def foo, do: :bar")

      result = %{success: true, path: path}
      result = Validation.maybe_attach_warning(result, path)

      # Should NOT have a syntax_warning key for valid code
      refute Map.has_key?(result, :syntax_warning)

      File.rm(path)
    end
  end

  describe "validate_file/2" do
    test "returns :ok for non-validatable extensions" do
      assert {:ok, :valid} = Validation.validate_file("/tmp/test.txt", "anything")
    end

    test "validates valid Elixir code" do
      assert {:ok, :valid} = Validation.validate_file("/tmp/test.ex", "def foo, do: :bar")
    end

    test "detects invalid Elixir code" do
      assert {:warning, msg} = Validation.validate_file("/tmp/test.ex", "defmodule Foo do\n  def bar(\nend")
      assert msg =~ "Syntax error" or msg =~ "syntax"
    end

    test "validates valid JSON" do
      assert {:ok, :valid} = Validation.validate_file("/tmp/test.json", ~s({"key": "value"}))
    end

    test "detects invalid JSON" do
      assert {:warning, msg} = Validation.validate_file("/tmp/test.json", "{invalid json")
      assert msg =~ "Invalid JSON"
    end
  end

  describe "validation_enabled?/0" do
    test "returns a boolean" do
      assert is_boolean(Validation.validation_enabled?())
    end
  end
end
