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

    test "rejects absolute paths outside base directory" do
      # Absolute paths outside the base directory are rejected — no bypasses
      assert {:error, "Path escapes allowed directory"} =
               SafePath.validate("/etc/passwd", "/project")

      assert {:error, "Path escapes allowed directory"} =
               SafePath.validate("/tmp/file.txt", "/project")
    end

    test "allows absolute paths within base directory" do
      assert {:ok, "/project/lib/code.ex"} =
               SafePath.validate("/project/lib/code.ex", "/project")
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

    test "rejects absolute paths outside base in list" do
      base = "/project"
      paths = ["file.txt", "/etc/passwd", "lib/code.ex"]

      assert {:error, "Path escapes allowed directory"} =
               SafePath.validate_many(paths, base)
    end

    test "allows absolute paths within base in list" do
      base = "/project"
      paths = ["file.txt", "/project/lib/deep/code.ex", "lib/code.ex"]

      assert {:ok, expanded} = SafePath.validate_many(paths, base)
      assert "/project/file.txt" in expanded
      assert "/project/lib/deep/code.ex" in expanded
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

    test "rejects absolute temp paths outside base directory" do
      # Absolute paths outside base are now correctly rejected
      temp_file = Path.join(System.tmp_dir!(), "safe_path_abs_#{System.unique_integer([:positive])}.txt")
      File.write!(temp_file, "content")

      try do
        # Temp file is outside the project cwd — must be rejected
        assert {:error, "Path escapes allowed directory"} =
                 SafePath.validate(temp_file, File.cwd!())
      after
        File.rm(temp_file)
      end
    end

    test "detects symlink pointing outside base directory" do
      temp_dir = Path.join(System.tmp_dir!(), "safe_path_symlink_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      try do
        # Create a symlink inside temp_dir that points to /etc/hosts
        link_path = Path.join(temp_dir, "sneaky_link")
        File.ln_s!("/etc/hosts", link_path)

        assert {:error, msg} = SafePath.validate("sneaky_link", temp_dir)
        assert msg =~ "Symlink"
        assert msg =~ "points outside base directory"
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "allows symlink pointing within base directory" do
      temp_dir = Path.join(System.tmp_dir!(), "safe_path_symlink_ok_#{System.unique_integer([:positive])}")
      nested_dir = Path.join(temp_dir, "nested")
      File.mkdir_p!(nested_dir)

      try do
        target = Path.join(nested_dir, "real_file.txt")
        File.write!(target, "hello")

        link_path = Path.join(temp_dir, "good_link")
        File.ln_s!(target, link_path)

        assert {:ok, resolved} = SafePath.validate("good_link", temp_dir)
        assert resolved == target
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "passes through non-existent paths for create operations" do
      temp_dir = Path.join(System.tmp_dir!(), "safe_path_create_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      try do
        # File doesn't exist yet — should pass (create operation)
        assert {:ok, _} = SafePath.validate("new_file.txt", temp_dir)
      after
        File.rm_rf!(temp_dir)
      end
    end
  end

  describe "safe_read/2" do
    test "reads file content atomically with validation" do
      temp_dir = Path.join(System.tmp_dir!(), "safe_read_test_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      try do
        file_path = Path.join(temp_dir, "test.txt")
        File.write!(file_path, "hello world")

        assert {:ok, "hello world"} = SafePath.safe_read("test.txt", temp_dir)
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "rejects reading outside base directory" do
      temp_dir = Path.join(System.tmp_dir!(), "safe_read_oob_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      try do
        assert {:error, "Path escapes allowed directory"} =
                 SafePath.safe_read("../etc/passwd", temp_dir)
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "rejects reading symlinks" do
      temp_dir = Path.join(System.tmp_dir!(), "safe_read_symlink_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      try do
        # Create a legitimate file
        file_path = Path.join(temp_dir, "real.txt")
        File.write!(file_path, "real content")

        # Create a symlink to it
        link_path = Path.join(temp_dir, "link.txt")
        File.ln_s!(file_path, link_path)

        # Should reject reading the symlink due to TOCTOU protection
        assert {:error, msg} = SafePath.safe_read("link.txt", temp_dir)
        assert msg =~ "symlink"
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "returns error for non-existent file" do
      temp_dir = Path.join(System.tmp_dir!(), "safe_read_missing_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      try do
        assert {:error, _} = SafePath.safe_read("nonexistent.txt", temp_dir)
      after
        File.rm_rf!(temp_dir)
      end
    end
  end

  describe "safe_delete/2" do
    test "deletes file atomically with validation" do
      temp_dir = Path.join(System.tmp_dir!(), "safe_delete_test_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      try do
        file_path = Path.join(temp_dir, "delete_me.txt")
        File.write!(file_path, "delete me")

        assert :ok = SafePath.safe_delete("delete_me.txt", temp_dir)
        refute File.exists?(file_path)
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "rejects deleting outside base directory" do
      temp_dir = Path.join(System.tmp_dir!(), "safe_delete_oob_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      try do
        assert {:error, "Path escapes allowed directory"} =
                 SafePath.safe_delete("../etc/passwd", temp_dir)
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "rejects deleting symlinks" do
      temp_dir = Path.join(System.tmp_dir!(), "safe_delete_symlink_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      try do
        # Create a legitimate file outside temp_dir
        outside_file = Path.join(System.tmp_dir!(), "outside_#{System.unique_integer([:positive])}.txt")
        File.write!(outside_file, "outside content")

        # Create a symlink inside temp_dir that points to outside file
        link_path = Path.join(temp_dir, "sneaky_link")
        File.ln_s!(outside_file, link_path)

        # Should reject deleting the symlink due to TOCTOU protection
        assert {:error, msg} = SafePath.safe_delete("sneaky_link", temp_dir)
        assert msg =~ "symlink"

        # Clean up outside file
        File.rm(outside_file)
      after
        File.rm_rf!(temp_dir)
      end
    end

    test "returns error for non-existent file" do
      temp_dir = Path.join(System.tmp_dir!(), "safe_delete_missing_#{System.unique_integer([:positive])}")
      File.mkdir_p!(temp_dir)

      try do
        assert {:error, _} = SafePath.safe_delete("nonexistent.txt", temp_dir)
      after
        File.rm_rf!(temp_dir)
      end
    end
  end
end
