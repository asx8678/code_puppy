defmodule Mana.Tools.FileEditTest do
  @moduledoc """
  Tests for Mana.Tools.FileEdit module.
  """

  use ExUnit.Case, async: true

  alias Mana.Tools.FileEdit.{CreateFile, DeleteFile, ReplaceInFile}

  # Use a temp dir within the project so SafePath containment is satisfied.
  defp project_tmp_dir do
    dir = Path.join([File.cwd!(), "test", "tmp"])
    File.mkdir_p!(dir)
    dir
  end

  describe "CreateFile" do
    test "behaviour implementation is correct" do
      assert CreateFile.name() == "create_file"
      assert is_binary(CreateFile.description())
      assert %{type: "object", properties: _} = CreateFile.parameters()
    end

    test "creates file with content" do
      temp_file = Path.join(project_tmp_dir(), "create_test_#{System.unique_integer([:positive])}.txt")
      content = "Hello, World!"

      try do
        assert {:ok, %{"created" => ^temp_file, "size" => 13}} =
                 CreateFile.execute(%{"file_path" => temp_file, "content" => content})

        assert File.read!(temp_file) == content
      after
        File.rm(temp_file)
      end
    end

    test "creates parent directories if needed" do
      temp_dir = Path.join(project_tmp_dir(), "create_nested_#{System.unique_integer([:positive])}")
      temp_file = Path.join([temp_dir, "nested", "path", "file.txt"])
      content = "nested content"

      try do
        assert {:ok, %{"created" => ^temp_file}} =
                 CreateFile.execute(%{"file_path" => temp_file, "content" => content})

        assert File.read!(temp_file) == content
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "returns error for invalid path" do
      # Try to create file in a non-existent directory that can't be created
      assert {:error, _} =
               CreateFile.execute(%{
                 "file_path" => "/dev/null/invalid/file.txt",
                 "content" => "test"
               })
    end

    test "blocks path traversal in file_path" do
      assert {:error, message} =
               CreateFile.execute(%{
                 "file_path" => "../../../etc/malicious.txt",
                 "content" => "hacked"
               })

      assert message =~ "Path escapes allowed directory"
    end

    test "blocks absolute path outside working directory" do
      assert {:error, _} =
               CreateFile.execute(%{
                 "file_path" => "/etc/passwd",
                 "content" => "modified"
               })
    end
  end

  describe "ReplaceInFile" do
    test "behaviour implementation is correct" do
      assert ReplaceInFile.name() == "replace_in_file"
      assert is_binary(ReplaceInFile.description())
      assert %{type: "object", properties: _} = ReplaceInFile.parameters()
    end

    test "replaces text in file" do
      temp_file = Path.join(project_tmp_dir(), "replace_test_#{System.unique_integer([:positive])}.txt")
      File.write!(temp_file, "Hello, World! This is a test.")

      try do
        assert {:ok, %{"replaced" => ^temp_file, "diff" => diff}} =
                 ReplaceInFile.execute(%{
                   "file_path" => temp_file,
                   "old_string" => "World",
                   "new_string" => "Elixir"
                 })

        assert File.read!(temp_file) == "Hello, Elixir! This is a test."
        assert diff =~ "- World"
        assert diff =~ "+ Elixir"
      after
        File.rm(temp_file)
      end
    end

    test "returns error when old string not found" do
      temp_file = Path.join(project_tmp_dir(), "replace_notfound_#{System.unique_integer([:positive])}.txt")
      File.write!(temp_file, "Hello, World!")

      try do
        assert {:error, message} =
                 ReplaceInFile.execute(%{
                   "file_path" => temp_file,
                   "old_string" => "NotPresent",
                   "new_string" => "Replacement"
                 })

        assert message =~ "String not found"

        # File should be unchanged
        assert File.read!(temp_file) == "Hello, World!"
      after
        File.rm(temp_file)
      end
    end

    test "replaces only first occurrence" do
      temp_file = Path.join(project_tmp_dir(), "replace_first_#{System.unique_integer([:positive])}.txt")
      File.write!(temp_file, "foo bar foo baz foo")

      try do
        assert {:ok, _} =
                 ReplaceInFile.execute(%{
                   "file_path" => temp_file,
                   "old_string" => "foo",
                   "new_string" => "xxx"
                 })

        assert File.read!(temp_file) == "xxx bar foo baz foo"
      after
        File.rm(temp_file)
      end
    end

    test "returns error for non-existent file" do
      assert {:error, _} =
               ReplaceInFile.execute(%{
                 "file_path" => "/nonexistent/file.txt",
                 "old_string" => "old",
                 "new_string" => "new"
               })
    end

    test "blocks path traversal in file_path" do
      assert {:error, message} =
               ReplaceInFile.execute(%{
                 "file_path" => "../../../etc/passwd",
                 "old_string" => "root",
                 "new_string" => "hacked"
               })

      assert message =~ "Path escapes allowed directory"
    end

    test "generates correct diff format" do
      temp_file = Path.join(project_tmp_dir(), "diff_test_#{System.unique_integer([:positive])}.txt")
      File.write!(temp_file, "line1\nline2\nline3")

      try do
        assert {:ok, %{"diff" => diff}} =
                 ReplaceInFile.execute(%{
                   "file_path" => temp_file,
                   "old_string" => "line1\nline2",
                   "new_string" => "new1\nnew2"
                 })

        assert diff =~ "- line1"
        assert diff =~ "- line2"
        assert diff =~ "+ new1"
        assert diff =~ "+ new2"
      after
        File.rm(temp_file)
      end
    end
  end

  describe "DeleteFile" do
    test "behaviour implementation is correct" do
      assert DeleteFile.name() == "delete_file"
      assert is_binary(DeleteFile.description())
      assert %{type: "object", properties: _} = DeleteFile.parameters()
    end

    test "deletes existing file" do
      temp_file = Path.join(project_tmp_dir(), "delete_test_#{System.unique_integer([:positive])}.txt")
      File.write!(temp_file, "content")

      assert File.exists?(temp_file)

      assert {:ok, %{"deleted" => ^temp_file}} =
               DeleteFile.execute(%{"file_path" => temp_file})

      refute File.exists?(temp_file)
    end

    test "returns error for non-existent file" do
      assert {:error, _} =
               DeleteFile.execute(%{"file_path" => "/nonexistent/file.txt"})
    end

    test "returns error for directory" do
      temp_dir = Path.join(project_tmp_dir(), "delete_dir_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      try do
        # File.rm returns :eisdir when trying to delete a directory
        assert {:error, _} = DeleteFile.execute(%{"file_path" => temp_dir})
      after
        File.rmdir(temp_dir)
      end
    end

    test "blocks path traversal in file_path" do
      assert {:error, message} =
               DeleteFile.execute(%{"file_path" => "../../../etc/passwd"})

      assert message =~ "Path escapes allowed directory"
    end

    test "blocks absolute path outside working directory" do
      assert {:error, _} = DeleteFile.execute(%{"file_path" => "/etc/passwd"})
    end
  end
end
