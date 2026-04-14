defmodule CodePuppyControl.FileOpsTest do
  @moduledoc """
  Tests for FileOps module - ported from Python file_operations tests.
  """

  use ExUnit.Case

  alias CodePuppyControl.FileOps

  @test_dir Path.join(System.tmp_dir!(), "file_ops_test_#{:erlang.unique_integer([:positive])}")

  setup do
    # Create test directory structure
    File.rm_rf!(@test_dir)
    File.mkdir_p!(@test_dir)

    # Create test files
    File.write!(Path.join(@test_dir, "file1.txt"), "Line 1\nLine 2\nLine 3\nLine 4\nLine 5")
    File.write!(Path.join(@test_dir, "file2.ex"), "defmodule Test do\n  def hello do\n    :world\n  end\nend")
    File.write!(Path.join(@test_dir, "file3.py"), "# TODO: implement this\ndef main():\n    pass")

    # Create subdirectory with more files
    subdir = Path.join(@test_dir, "subdir")
    File.mkdir_p!(subdir)
    File.write!(Path.join(subdir, "nested.ex"), "defmodule Nested do\n  # FIXME: fix this\n  def run do\n    :ok\n  end\nend")

    # Create hidden file (should be excluded by default)
    File.write!(Path.join(@test_dir, ".hidden"), "secret content")

    on_exit(fn ->
      File.rm_rf!(@test_dir)
    end)

    %{test_dir: @test_dir, subdir: subdir}
  end

  # ============================================================================
  # list_files tests
  # ============================================================================

  describe "list_files/2" do
    test "lists files in a directory (shallow)", %{test_dir: dir} do
      assert {:ok, files} = FileOps.list_files(dir, recursive: false)

      # Should have file1.txt, file2.ex, file3.py, subdir (but not .hidden by default)
      paths = Enum.map(files, & &1.path)

      assert "file1.txt" in paths
      assert "file2.ex" in paths
      assert "file3.py" in paths
      assert "subdir" in paths
      refute ".hidden" in paths

      # Check structure
      file1 = Enum.find(files, &(&1.path == "file1.txt"))
      assert file1.type == :file
      assert file1.size >= 29  # "Line 1\nLine 2\nLine 3\nLine 4\nLine 5" (may have trailing newline)
      assert %DateTime{} = file1.modified
    end

    test "lists files recursively", %{test_dir: dir} do
      assert {:ok, files} = FileOps.list_files(dir, recursive: true)

      paths = Enum.map(files, & &1.path)

      # Should include all files including nested
      assert "file1.txt" in paths
      assert "subdir/nested.ex" in paths
      assert "subdir" in paths
    end

    test "can include hidden files", %{test_dir: dir} do
      assert {:ok, files} = FileOps.list_files(dir, recursive: false, include_hidden: true)

      paths = Enum.map(files, & &1.path)
      assert ".hidden" in paths
    end

    test "respects ignore patterns", %{test_dir: dir} do
      assert {:ok, files} = FileOps.list_files(dir, recursive: true, ignore_patterns: ["subdir"])

      paths = Enum.map(files, & &1.path)
      assert "file1.txt" in paths
      refute "subdir" in paths
      refute "subdir/nested.ex" in paths
    end

    test "respects max_files limit", %{test_dir: dir} do
      assert {:ok, files} = FileOps.list_files(dir, recursive: true, max_files: 3)
      assert length(files) <= 3
    end

    test "returns error for non-existent directory" do
      assert {:error, _} = FileOps.list_files("/nonexistent/directory/12345")
    end

    test "returns error for file instead of directory", %{test_dir: dir} do
      file_path = Path.join(dir, "file1.txt")
      assert {:error, _} = FileOps.list_files(file_path)
    end
  end

  # ============================================================================
  # grep tests
  # ============================================================================

  describe "grep/3" do
    test "finds pattern in files", %{test_dir: dir} do
      assert {:ok, matches} = FileOps.grep("defmodule", dir)

      assert length(matches) >= 2

      # Check structure
      match = hd(matches)
      assert is_binary(match.file)
      assert is_integer(match.line_number)
      assert is_binary(match.line_content)
      assert match.line_content =~ "defmodule"
      assert is_integer(match.match_start)
      assert is_integer(match.match_end)
    end

    test "is case sensitive by default", %{test_dir: dir} do
      # "DEFMODULE" should not match "defmodule"
      assert {:ok, matches} = FileOps.grep("DEFMODULE", dir)
      assert matches == []
    end

    test "can be case insensitive", %{test_dir: dir} do
      # Create file with uppercase DEFMODULE
      File.write!(Path.join(dir, "upper.ex"), "DEFMODULE Upper do\nend")

      assert {:ok, matches} = FileOps.grep("defmodule", dir, case_sensitive: false)
      assert length(matches) >= 1
    end

    test "respects max_matches limit", %{test_dir: dir} do
      assert {:ok, matches} = FileOps.grep("Line", dir, max_matches: 2)
      assert length(matches) <= 2
    end

    test "returns empty list for non-matching pattern", %{test_dir: dir} do
      assert {:ok, matches} = FileOps.grep("XYZ_NONEXISTENT_PATTERN_123", dir)
      assert matches == []
    end

    test "returns error for invalid regex", %{test_dir: dir} do
      assert {:error, _} = FileOps.grep("[invalid", dir)
    end
  end

  # ============================================================================
  # read_file tests
  # ============================================================================

  describe "read_file/2" do
    test "reads file contents", %{test_dir: dir} do
      file_path = Path.join(dir, "file1.txt")
      assert {:ok, result} = FileOps.read_file(file_path)

      assert result.path == file_path
      assert result.content == "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
      assert result.num_lines == 5
      assert result.size >= 29  # File may have trailing newline
      assert result.truncated == false
      assert result.error == nil
    end

    test "reads specific line range", %{test_dir: dir} do
      file_path = Path.join(dir, "file1.txt")
      assert {:ok, result} = FileOps.read_file(file_path, start_line: 2, num_lines: 2)

      assert result.content == "Line 2\nLine 3"
      assert result.num_lines == 2
      assert result.truncated == true
    end

    test "returns error for non-existent file", %{test_dir: dir} do
      assert {:error, _} = FileOps.read_file(Path.join(dir, "nonexistent.txt"))
    end

    test "returns error for directory", %{test_dir: dir} do
      assert {:error, _} = FileOps.read_file(dir)
    end

    test "reads start_line from end", %{test_dir: dir} do
      file_path = Path.join(dir, "file1.txt")
      # Request more lines than exist from a starting point near the end
      assert {:ok, result} = FileOps.read_file(file_path, start_line: 4, num_lines: 10)

      assert result.content == "Line 4\nLine 5"
      assert result.num_lines == 2
    end
  end

  # ============================================================================
  # read_files tests (batch)
  # ============================================================================

  describe "read_files/2" do
    test "reads multiple files concurrently", %{test_dir: dir} do
      paths = [
        Path.join(dir, "file1.txt"),
        Path.join(dir, "file2.ex"),
        Path.join(dir, "file3.py")
      ]

      assert {:ok, results} = FileOps.read_files(paths)
      assert length(results) == 3

      # All should have content
      assert Enum.all?(results, &(&1.error == nil))

      # Check each file was read
      paths_returned = Enum.map(results, & &1.path)
      assert Enum.all?(paths, fn p -> p in paths_returned end)
    end

    test "handles partial failures gracefully", %{test_dir: dir} do
      paths = [
        Path.join(dir, "file1.txt"),
        Path.join(dir, "nonexistent.txt"),
        Path.join(dir, "file2.ex")
      ]

      assert {:ok, results} = FileOps.read_files(paths)
      assert length(results) == 3

      # Check that nonexistent file has an error
      nonexistent = Enum.find(results, fn r -> r.path =~ "nonexistent" end)
      assert nonexistent.error != nil

      # Check we have the valid results too
      contents = Enum.map(results, & &1.content)
      assert Enum.any?(contents, &(is_binary(&1) and &1 =~ "Line 1"))
      assert Enum.any?(contents, &(is_binary(&1) and &1 =~ "defmodule"))
    end

    test "respects concurrency limit", %{test_dir: dir} do
      # Create many files
      for i <- 1..20 do
        File.write!(Path.join(dir, "bulk#{i}.txt"), "content #{i}")
      end

      paths = for i <- 1..20, do: Path.join(dir, "bulk#{i}.txt")

      assert {:ok, results} = FileOps.read_files(paths, max_concurrency: 2)
      assert length(results) == 20
    end

    test "returns error entries when all paths are invalid" do
      paths = [
        "/nonexistent1.txt",
        "/nonexistent2.txt"
      ]

      assert {:ok, results} = FileOps.read_files(paths)
      assert length(results) == 2
      # All entries should have errors
      assert Enum.all?(results, &(&1.error != nil))
    end
  end

  # ============================================================================
  # Security tests
  # ============================================================================

  describe "security" do
    test "blocks sensitive paths" do
      assert FileOps.sensitive_path?(Path.join(System.user_home!(), ".ssh/id_rsa"))
      assert FileOps.sensitive_path?("/etc/shadow")
      assert FileOps.sensitive_path?("/private/etc/sudoers")
      assert FileOps.sensitive_path?(Path.join(System.user_home!(), ".aws/credentials"))
      assert FileOps.sensitive_path?("/root/.ssh/authorized_keys")
    end

    test "allows safe paths", %{test_dir: dir} do
      refute FileOps.sensitive_path?(Path.join(dir, "file1.txt"))
      refute FileOps.sensitive_path?("/home/user/project/main.py")
    end

    test "blocks .env files except examples" do
      assert FileOps.sensitive_path?(Path.join(System.user_home!(), ".env"))
      assert FileOps.sensitive_path?("/project/.env.local")

      # Allow examples
      refute FileOps.sensitive_path?("/project/.env.example")
      refute FileOps.sensitive_path?("/project/.env.sample")
    end

    test "blocks private key files by extension" do
      assert FileOps.sensitive_path?("/path/to/cert.pem")
      assert FileOps.sensitive_path?("/path/to/key.key")
      assert FileOps.sensitive_path?("/path/to/keystore.p12")
    end

    test "list_files filters sensitive paths" do
      # Create a mock sensitive file (won't actually exist, but path validation should catch it)
      assert {:error, _} = FileOps.list_files(Path.join(System.user_home!(), ".ssh"))
    end

    test "read_file blocks sensitive paths" do
      assert {:error, _} = FileOps.read_file(Path.join(System.user_home!(), ".ssh/id_rsa"))
    end

    test "grep blocks sensitive directory searches" do
      assert {:error, _} = FileOps.grep("test", "/etc")
    end

    test "read_files marks sensitive paths with errors", %{test_dir: dir} do
      # Mix of safe and sensitive paths
      paths = [
        Path.join(dir, "file1.txt"),
        Path.join(System.user_home!(), ".ssh/id_rsa")
      ]

      # Sensitive paths are included but marked with errors
      assert {:ok, results} = FileOps.read_files(paths)
      assert length(results) == 2

      # Safe path should succeed
      safe_result = Enum.find(results, fn r -> String.contains?(r.path, "file1.txt") end)
      assert safe_result.error == nil

      # Sensitive path should have error
      sensitive_result = Enum.find(results, fn r -> String.contains?(r.path, ".ssh") end)
      assert sensitive_result.error =~ "sensitive path blocked"
    end
  end

  # ============================================================================
  # validate_path tests
  # ============================================================================

  describe "validate_path/2" do
    test "accepts valid paths", %{test_dir: dir} do
      assert {:ok, _} = FileOps.validate_path(dir, "list")
      assert {:ok, _} = FileOps.validate_path(Path.join(dir, "file1.txt"), "read")
    end

    test "rejects empty paths" do
      assert {:error, "File path cannot be empty"} = FileOps.validate_path("", "read")
    end

    test "rejects paths with null bytes" do
      assert {:error, "File path contains null byte"} = FileOps.validate_path("/path/with\0null", "read")
    end

    test "rejects sensitive paths with appropriate message" do
      assert {:error, msg} = FileOps.validate_path(Path.join(System.user_home!(), ".ssh/id_rsa"), "read")
      assert msg =~ "sensitive path blocked"
      assert msg =~ "read"
    end

    test "normalizes paths", %{test_dir: dir} do
      # Path with .. should be normalized
      assert {:ok, normalized} = FileOps.validate_path(Path.join(dir, "../#{Path.basename(dir)}/file1.txt"), "read")
      assert normalized == Path.join(dir, "file1.txt")
    end
  end
end
