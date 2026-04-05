defmodule Mana.Tools.SafePathTest do
  @moduledoc """
  Tests for Mana.Tools.SafePath module.
  """

  use ExUnit.Case, async: true

  alias Mana.Tools.SafePath

  describe "validate/2" do
    test "validates paths within base directory" do
      base = "/project"

      assert {:ok, "/project/file.txt"} = SafePath.validate("file.txt", base)
      assert {:ok, "/project/lib/file.ex"} = SafePath.validate("lib/file.ex", base)
    end

    test "expands relative paths including current directory" do
      # Path.expand(".", base) returns base itself
      assert {:ok, expanded} = SafePath.validate(".", "/project")
      assert expanded == "/project"
    end

    test "allows absolute paths (no traversal check needed)" do
      # Absolute paths are allowed as long as they don't contain traversal attempts
      assert {:ok, "/etc/passwd"} = SafePath.validate("/etc/passwd", "/project")
      assert {:ok, "/tmp/file.txt"} = SafePath.validate("/tmp/file.txt", "/project")
    end

    test "blocks relative paths escaping base directory via .." do
      base = "/project"

      assert {:error, "Path escapes allowed directory"} =
               SafePath.validate("../secret.txt", base)

      assert {:error, "Path escapes allowed directory"} =
               SafePath.validate("../../etc/passwd", base)

      assert {:error, "Path escapes allowed directory"} =
               SafePath.validate("lib/../../../etc/passwd", base)
    end

    test "blocks absolute paths with traversal sequences" do
      # Absolute paths containing .. are suspicious
      assert {:error, "Path escapes allowed directory"} =
               SafePath.validate("/project/../etc/passwd", "/project")
    end

    test "allows base directory itself" do
      base = "/project"
      assert {:ok, "/project"} = SafePath.validate("/project", base)
    end

    test "returns error for invalid inputs" do
      assert {:error, "Invalid path or base directory"} = SafePath.validate(nil, "/base")
      assert {:error, "Invalid path or base directory"} = SafePath.validate("path", nil)
      assert {:error, "Invalid path or base directory"} = SafePath.validate(123, "/base")
    end
  end

  describe "validate_many/2" do
    test "validates multiple paths successfully" do
      base = "/project"
      paths = ["file1.txt", "file2.txt", "lib/file.ex"]

      assert {:ok, expanded} = SafePath.validate_many(paths, base)
      assert length(expanded) == 3
      assert "/project/file1.txt" in expanded
      assert "/project/file2.txt" in expanded
      assert "/project/lib/file.ex" in expanded
    end

    test "returns error if any path has traversal" do
      base = "/project"
      paths = ["file1.txt", "../../secret.txt", "file3.txt"]

      assert {:error, "Path escapes allowed directory"} =
               SafePath.validate_many(paths, base)
    end

    test "allows absolute paths in the list" do
      base = "/project"
      paths = ["file.txt", "/etc/passwd", "lib/code.ex"]

      assert {:ok, expanded} = SafePath.validate_many(paths, base)
      assert "/project/file.txt" in expanded
      assert "/etc/passwd" in expanded
      assert "/project/lib/code.ex" in expanded
    end

    test "handles empty list" do
      assert {:ok, []} = SafePath.validate_many([], "/project")
    end
  end

  describe "suspicious_traversal?/1" do
    test "detects obvious traversal patterns" do
      assert SafePath.suspicious_traversal?("../file.txt") == true
      assert SafePath.suspicious_traversal?("../../etc/passwd") == true
      assert SafePath.suspicious_traversal?("path/../../../secret") == true
    end

    test "detects Windows-style traversal" do
      assert SafePath.suspicious_traversal?("..\\file.txt") == true
    end

    test "detects traversal ending with .." do
      assert SafePath.suspicious_traversal?("path/to/..") == true
    end

    test "detects null bytes" do
      assert SafePath.suspicious_traversal?("file.txt\x00") == true
      assert SafePath.suspicious_traversal?("\x00etc/passwd") == true
    end

    test "returns false for safe paths" do
      assert SafePath.suspicious_traversal?("file.txt") == false
      assert SafePath.suspicious_traversal?("lib/file.ex") == false
      assert SafePath.suspicious_traversal?("path/to/file.txt") == false
    end

    test "returns false for absolute paths without traversal" do
      # An absolute path alone is not suspicious
      assert SafePath.suspicious_traversal?("/etc/passwd") == false
    end

    test "returns false for invalid inputs" do
      assert SafePath.suspicious_traversal?(nil) == false
      assert SafePath.suspicious_traversal?(123) == false
    end
  end

  describe "current_working_dir/0" do
    test "returns the current working directory" do
      assert {:ok, cwd} = SafePath.current_working_dir()
      assert is_binary(cwd)
      assert Path.type(cwd) == :absolute
    end
  end

  describe "validate_within_base/2" do
    test "returns :ok for paths within base" do
      assert :ok = SafePath.validate_within_base("/project/file.txt", "/project")
      assert :ok = SafePath.validate_within_base("/project/lib/file.ex", "/project")
    end

    test "returns :ok for base directory itself" do
      assert :ok = SafePath.validate_within_base("/project", "/project")
    end

    test "returns error for paths outside base" do
      assert {:error, "Path escapes allowed directory"} =
               SafePath.validate_within_base("/etc/passwd", "/project")

      assert {:error, "Path escapes allowed directory"} =
               SafePath.validate_within_base("/other/path", "/project")
    end
  end

  describe "integration with real file operations" do
    test "works with actual temp directory using relative paths" do
      temp_dir = Path.join(System.tmp_dir!(), "safe_path_test_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      try do
        # Create a nested file
        nested_dir = Path.join(temp_dir, "nested")
        File.mkdir_p!(nested_dir)
        File.write!(Path.join(nested_dir, "file.txt"), "content")

        # Should be able to validate relative paths within temp_dir
        assert {:ok, _} = SafePath.validate("nested/file.txt", temp_dir)
        assert {:ok, _} = SafePath.validate(".", temp_dir)

        # Should block relative paths escaping temp_dir
        assert {:error, _} = SafePath.validate("../secret", temp_dir)
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "allows absolute temp paths for file operations" do
      # Absolute paths are allowed even if outside base
      temp_file = Path.join(System.tmp_dir!(), "safe_path_abs_#{System.unique_integer([:positive])}.txt")
      File.write!(temp_file, "content")

      try do
        # Should allow absolute path even though it's outside cwd
        assert {:ok, ^temp_file} = SafePath.validate(temp_file, File.cwd!())
      after
        File.rm(temp_file)
      end
    end
  end
end
