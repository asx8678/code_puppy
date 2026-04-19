defmodule CodePuppyControl.Tools.FileModifications.EditFileTest do
  @moduledoc "Tests for the EditFile tool (comprehensive editor dispatcher)."

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.FileModifications.EditFile

  @tmp_dir System.tmp_dir!()

  describe "name/0" do
    test "returns :edit_file" do
      assert EditFile.name() == :edit_file
    end
  end

  describe "parameters/0" do
    test "supports content, replacements, and delete_snippet" do
      schema = EditFile.parameters()
      props = schema["properties"]
      assert Map.has_key?(props, "file_path")
      assert Map.has_key?(props, "content")
      assert Map.has_key?(props, "replacements")
      assert Map.has_key?(props, "delete_snippet")
    end
  end

  describe "invoke/2 with content payload" do
    test "creates file with content" do
      path = Path.join(@tmp_dir, "edit_content_test_#{:rand.uniform(10000)}.txt")

      args = %{
        "file_path" => path,
        "content" => "hello from edit_file"
      }

      assert {:ok, result} = EditFile.invoke(args, %{})
      assert result.success == true
      assert File.read!(path) == "hello from edit_file"

      File.rm(path)
    end
  end

  describe "invoke/2 with replacements payload" do
    test "applies replacements" do
      path = Path.join(@tmp_dir, "edit_replace_test_#{:rand.uniform(10000)}.txt")
      File.write!(path, "foo bar baz")

      args = %{
        "file_path" => path,
        "replacements" => [%{"old_str" => "bar", "new_str" => "qux"}]
      }

      assert {:ok, result} = EditFile.invoke(args, %{})
      assert result.success == true
      assert File.read!(path) == "foo qux baz"

      File.rm(path)
    end
  end

  describe "invoke/2 with delete_snippet payload" do
    test "deletes snippet from file" do
      path = Path.join(@tmp_dir, "edit_delete_test_#{:rand.uniform(10000)}.txt")
      File.write!(path, "line 1\nremove this\nline 3")

      args = %{
        "file_path" => path,
        "delete_snippet" => "remove this\n"
      }

      assert {:ok, result} = EditFile.invoke(args, %{})
      assert result.success == true
      assert File.read!(path) == "line 1\nline 3"

      File.rm(path)
    end
  end

  describe "invoke/2 with no payload" do
    test "returns error when no modification payload given" do
      args = %{"file_path" => "/tmp/test.txt"}

      assert {:error, result} = EditFile.invoke(args, %{})
      assert result.message =~ "Must provide one of"
    end
  end
end
