defmodule Mana.Tools.FileOpsTest do
  @moduledoc """
  Tests for Mana.Tools.FileOps module.
  """

  use ExUnit.Case, async: true

  alias Mana.Tools.FileOps.{Grep, ListFiles, ReadFile}

  describe "ListFiles" do
    test "behaviour implementation is correct" do
      assert ListFiles.name() == "list_files"
      assert is_binary(ListFiles.description())
      assert %{type: "object", properties: _} = ListFiles.parameters()
    end

    test "lists files in directory" do
      # Create temp directory with test files
      temp_dir = Path.join(System.tmp_dir!(), "mana_test_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      File.write!(Path.join(temp_dir, "file1.txt"), "content1")
      File.write!(Path.join(temp_dir, "file2.txt"), "content2")

      try do
        assert {:ok, %{"files" => files, "count" => 2}} =
                 ListFiles.execute(%{"directory" => temp_dir, "recursive" => false})

        assert Enum.any?(files, &String.ends_with?(&1, "file1.txt"))
        assert Enum.any?(files, &String.ends_with?(&1, "file2.txt"))
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "lists files recursively" do
      temp_dir = Path.join(System.tmp_dir!(), "mana_test_#{System.unique_integer([:positive])}")
      sub_dir = Path.join(temp_dir, "subdir")
      File.mkdir_p!(sub_dir)

      File.write!(Path.join(temp_dir, "root.txt"), "content")
      File.write!(Path.join(sub_dir, "nested.txt"), "content")

      try do
        assert {:ok, %{"files" => files, "count" => 3}} =
                 ListFiles.execute(%{"directory" => temp_dir, "recursive" => true})

        assert Enum.any?(files, &String.ends_with?(&1, "root.txt"))
        assert Enum.any?(files, &String.ends_with?(&1, "nested.txt"))
        assert Enum.any?(files, &String.ends_with?(&1, "subdir"))
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "ignores patterns defined in IgnorePatterns" do
      temp_dir = Path.join(System.tmp_dir!(), "mana_test_#{System.unique_integer([:positive])}")
      File.mkdir_p!(Path.join(temp_dir, ".git"))
      File.mkdir_p!(Path.join(temp_dir, "node_modules"))

      File.write!(Path.join(temp_dir, "valid.txt"), "content")
      File.write!(Path.join(temp_dir, ".git/config"), "content")
      File.write!(Path.join(temp_dir, "node_modules/pkg.js"), "content")

      try do
        assert {:ok, %{"files" => files}} =
                 ListFiles.execute(%{"directory" => temp_dir, "recursive" => true})

        assert Enum.any?(files, &String.ends_with?(&1, "valid.txt"))
        refute Enum.any?(files, &String.contains?(&1, ".git"))
        refute Enum.any?(files, &String.contains?(&1, "node_modules"))
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "returns error for non-existent directory" do
      assert {:error, _} = ListFiles.execute(%{"directory" => "/nonexistent/path"})
    end

    test "uses current directory as default" do
      assert {:ok, %{"files" => files}} = ListFiles.execute(%{})
      assert is_list(files)
    end
  end

  describe "ReadFile" do
    test "behaviour implementation is correct" do
      assert ReadFile.name() == "read_file"
      assert is_binary(ReadFile.description())
      assert %{type: "object", properties: _} = ReadFile.parameters()
    end

    test "reads entire file" do
      temp_file = Path.join(System.tmp_dir!(), "read_test_#{System.unique_integer([:positive])}.txt")
      content = "Line 1\nLine 2\nLine 3"
      File.write!(temp_file, content)

      try do
        assert {:ok, %{"content" => ^content, "total_lines" => 3}} =
                 ReadFile.execute(%{"file_path" => temp_file})
      after
        File.rm!(temp_file)
      end
    end

    test "reads file with line range" do
      temp_file = Path.join(System.tmp_dir!(), "range_test_#{System.unique_integer([:positive])}.txt")
      File.write!(temp_file, "Line 1\nLine 2\nLine 3\nLine 4\nLine 5")

      try do
        assert {:ok, %{"content" => "Line 2\nLine 3", "total_lines" => 5}} =
                 ReadFile.execute(%{
                   "file_path" => temp_file,
                   "start_line" => 2,
                   "num_lines" => 2
                 })
      after
        File.rm!(temp_file)
      end
    end

    test "reads from start_line to end when num_lines not specified" do
      temp_file = Path.join(System.tmp_dir!(), "to_end_test_#{System.unique_integer([:positive])}.txt")
      File.write!(temp_file, "Line 1\nLine 2\nLine 3")

      try do
        assert {:ok, %{"content" => "Line 2\nLine 3"}} =
                 ReadFile.execute(%{
                   "file_path" => temp_file,
                   "start_line" => 2
                 })
      after
        File.rm!(temp_file)
      end
    end

    test "returns error for non-existent file" do
      assert {:error, _} = ReadFile.execute(%{"file_path" => "/nonexistent/file.txt"})
    end
  end

  describe "Grep" do
    test "behaviour implementation is correct" do
      assert Grep.name() == "grep"
      assert is_binary(Grep.description())
      assert %{type: "object", properties: _} = Grep.parameters()
    end

    test "searches for pattern in directory" do
      temp_dir = Path.join(System.tmp_dir!(), "grep_test_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      File.write!(Path.join(temp_dir, "file1.txt"), "hello world")
      File.write!(Path.join(temp_dir, "file2.txt"), "goodbye world")

      try do
        assert {:ok, %{"matches" => matches, "count" => count}} =
                 Grep.execute(%{"search_string" => "world", "directory" => temp_dir})

        assert count == 2
        assert Enum.all?(matches, fn m -> m["text"] =~ "world" end)
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "returns empty results when no matches found" do
      temp_dir = Path.join(System.tmp_dir!(), "grep_empty_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)
      File.write!(Path.join(temp_dir, "file.txt"), "content")

      try do
        assert {:ok, %{"matches" => [], "count" => 0}} =
                 Grep.execute(%{"search_string" => "notfound", "directory" => temp_dir})
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "uses current directory as default" do
      # Just verify it runs without error
      assert {:ok, %{"matches" => _}} = Grep.execute(%{"search_string" => "defmodule"})
    end
  end
end
