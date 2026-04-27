defmodule CodePuppyControl.Tools.CpFileOpsTest do
  @moduledoc """
  Tests for CpFileOps Tool-behaviour wrappers with permission gating.

  Covers:
  - permission_check/2: hard gate validates paths against Security.validate_path/2
  - invoke/2: delegation to FileOps with correct result shapes
  - Integration with Tool.Runner FilePermission callback chain (second layer)
  - Error responses matching bridge-caller expectations

  Refs: code_puppy-mmk.1 (Phase E: Port file_operations.py to FileOps with permission gating)
  """

  use ExUnit.Case

  alias CodePuppyControl.Callbacks
  alias CodePuppyControl.PolicyEngine
  alias CodePuppyControl.PolicyEngine.PolicyRule
  alias CodePuppyControl.Tool.{Registry, Runner}
  alias CodePuppyControl.Tools.CpFileOps.{CpListFiles, CpReadFile, CpGrep}

  @test_dir Path.join(System.tmp_dir!(), "cp_file_ops_test_#{:erlang.unique_integer([:positive])}")

  # ============================================================================
  # Setup / Teardown
  # ============================================================================

  setup do
    # Create test directory with sample files
    File.rm_rf!(@test_dir)
    File.mkdir_p!(@test_dir)

    File.write!(Path.join(@test_dir, "hello.txt"), "Hello World\nLine 2\nLine 3")
    File.write!(Path.join(@test_dir, "code.ex"), "defmodule Foo do\n  def bar, do: :ok\nend")

    subdir = Path.join(@test_dir, "sub")
    File.mkdir_p!(subdir)
    File.write!(Path.join(subdir, "nested.py"), "def main():\n    pass\n")

    on_exit(fn ->
      File.rm_rf!(@test_dir)
    end)

    %{test_dir: @test_dir, subdir: subdir}
  end

  # ============================================================================
  # CpListFiles — permission_check/2
  # ============================================================================

  describe "CpListFiles.permission_check/2" do
    test "allows safe directory path" do
      assert CpListFiles.permission_check(%{"directory" => @test_dir}, %{}) == :ok
    end

    test "allows current directory (default)" do
      assert CpListFiles.permission_check(%{}, %{}) == :ok
    end

    test "denies sensitive directory (.ssh)" do
      ssh_path = Path.join(System.user_home!(), ".ssh")
      assert {:deny, reason} = CpListFiles.permission_check(%{"directory" => ssh_path}, %{})
      assert reason =~ "sensitive path blocked"
    end

    test "denies /etc directory" do
      assert {:deny, reason} = CpListFiles.permission_check(%{"directory" => "/etc"}, %{})
      assert reason =~ "sensitive path blocked"
    end

    test "denies empty string path" do
      assert {:deny, reason} = CpListFiles.permission_check(%{"directory" => ""}, %{})
      assert reason =~ "empty" or reason =~ "cannot be empty"
    end

    test "denies path with null byte" do
      assert {:deny, reason} = CpListFiles.permission_check(%{"directory" => "/foo\x00bar"}, %{})
      assert reason =~ "null byte"
    end

    test "denies case-variant sensitive directory" do
      assert {:deny, _} = CpListFiles.permission_check(%{"directory" => "/ETC"}, %{})
    end
  end

  # ============================================================================
  # CpReadFile — permission_check/2
  # ============================================================================

  describe "CpReadFile.permission_check/2" do
    test "allows safe file path" do
      file_path = Path.join(@test_dir, "hello.txt")
      assert CpReadFile.permission_check(%{"file_path" => file_path}, %{}) == :ok
    end

    test "denies sensitive file path (.ssh/id_rsa)" do
      ssh_key = Path.join(System.user_home!(), ".ssh/id_rsa")
      assert {:deny, reason} = CpReadFile.permission_check(%{"file_path" => ssh_key}, %{})
      assert reason =~ "sensitive path blocked"
    end

    test "denies /etc/shadow" do
      assert {:deny, reason} = CpReadFile.permission_check(%{"file_path" => "/etc/shadow"}, %{})
      assert reason =~ "sensitive path blocked"
    end

    test "denies empty file_path" do
      assert {:deny, reason} = CpReadFile.permission_check(%{"file_path" => ""}, %{})
      assert reason =~ "empty" or reason =~ "cannot be empty"
    end

    test "denies file_path with null byte" do
      assert {:deny, reason} = CpReadFile.permission_check(%{"file_path" => "/foo\x00bar"}, %{})
      assert reason =~ "null byte"
    end

    test "denies private key extension" do
      assert {:deny, _} = CpReadFile.permission_check(%{"file_path" => "/tmp/secret.pem"}, %{})
      assert {:deny, _} = CpReadFile.permission_check(%{"file_path" => "/tmp/cert.key"}, %{})
    end
  end

  # ============================================================================
  # CpGrep — permission_check/2
  # ============================================================================

  describe "CpGrep.permission_check/2" do
    test "allows safe directory path" do
      assert CpGrep.permission_check(%{"directory" => @test_dir, "search_string" => "def"}, %{}) ==
               :ok
    end

    test "allows current directory (default)" do
      assert CpGrep.permission_check(%{"search_string" => "TODO"}, %{}) == :ok
    end

    test "denies sensitive directory (.aws)" do
      aws_path = Path.join(System.user_home!(), ".aws")
      assert {:deny, reason} = CpGrep.permission_check(%{"directory" => aws_path}, %{})
      assert reason =~ "sensitive path blocked"
    end

    test "denies /var/log directory" do
      assert {:deny, reason} = CpGrep.permission_check(%{"directory" => "/var/log"}, %{})
      assert reason =~ "sensitive path blocked"
    end

    test "denies empty directory path" do
      assert {:deny, reason} = CpGrep.permission_check(%{"directory" => ""}, %{})
      assert reason =~ "empty" or reason =~ "cannot be empty"
    end
  end

  # ============================================================================
  # CpListFiles — invoke/2
  # ============================================================================

  describe "CpListFiles.invoke/2" do
    test "lists files in directory with correct result shape", %{test_dir: dir} do
      assert {:ok, %{files: files, count: count}} =
               CpListFiles.invoke(%{"directory" => dir, "recursive" => false}, %{})

      assert is_list(files)
      assert count == length(files)

      paths = Enum.map(files, & &1.path)
      assert "hello.txt" in paths
      assert "code.ex" in paths
    end

    test "lists files recursively", %{test_dir: dir} do
      assert {:ok, %{files: files}} =
               CpListFiles.invoke(%{"directory" => dir, "recursive" => true}, %{})

      rel_paths = Enum.map(files, & &1.path)
      assert "sub/nested.py" in rel_paths
    end

    test "defaults to current directory and recursive", %{test_dir: dir} do
      assert {:ok, %{files: _files}} =
               CpListFiles.invoke(%{"directory" => dir}, %{})
    end

    test "returns error for non-existent directory" do
      assert {:error, reason} =
               CpListFiles.invoke(%{"directory" => "/nonexistent_dir_xyz_12345"}, %{})

      assert is_binary(reason)
    end
  end

  # ============================================================================
  # CpReadFile — invoke/2
  # ============================================================================

  describe "CpReadFile.invoke/2" do
    test "reads file with correct result shape", %{test_dir: dir} do
      file_path = Path.join(dir, "hello.txt")

      assert {:ok, result} = CpReadFile.invoke(%{"file_path" => file_path}, %{})

      assert Map.has_key?(result, :path)
      assert Map.has_key?(result, :content)
      assert Map.has_key?(result, :num_lines)
      assert Map.has_key?(result, :size)
      assert Map.has_key?(result, :truncated)
      assert Map.has_key?(result, :error)
      assert result.content =~ "Hello World"
    end

    test "reads file with line range", %{test_dir: dir} do
      file_path = Path.join(dir, "hello.txt")

      assert {:ok, result} =
               CpReadFile.invoke(
                 %{"file_path" => file_path, "start_line" => 2, "num_lines" => 1},
                 %{}
               )

      assert result.content =~ "Line 2"
      assert result.truncated == true
    end

    test "returns error for non-existent file" do
      assert {:error, reason} =
               CpReadFile.invoke(%{"file_path" => "/nonexistent_file_xyz.txt"}, %{})

      assert is_binary(reason)
    end

    test "returns error for directory path", %{test_dir: dir} do
      assert {:error, reason} = CpReadFile.invoke(%{"file_path" => dir}, %{})
      assert is_binary(reason)
    end
  end

  # ============================================================================
  # CpGrep — invoke/2
  # ============================================================================

  describe "CpGrep.invoke/2" do
    test "finds pattern with correct result shape", %{test_dir: dir} do
      assert {:ok, %{matches: matches, count: count}} =
               CpGrep.invoke(%{"search_string" => "Hello", "directory" => dir}, %{})

      assert is_list(matches)
      assert count == length(matches)
      assert count >= 1

      match = hd(matches)
      assert Map.has_key?(match, :file)
      assert Map.has_key?(match, :line_number)
      assert Map.has_key?(match, :line_content)
      assert Map.has_key?(match, :match_start)
      assert Map.has_key?(match, :match_end)
      assert match.line_content =~ "Hello"
    end

    test "returns empty matches for non-matching pattern", %{test_dir: dir} do
      assert {:ok, %{matches: [], count: 0}} =
               CpGrep.invoke(
                 %{"search_string" => "ZZZ_NO_MATCH_12345", "directory" => dir},
                 %{}
               )
    end

    test "returns error for invalid regex" do
      assert {:error, reason} =
               CpGrep.invoke(%{"search_string" => "[invalid", "directory" => @test_dir}, %{})

      assert is_binary(reason)
    end

    test "defaults to current directory" do
      # Should not crash even with default directory
      assert {:ok, _} =
               CpGrep.invoke(%{"search_string" => "nonexistent_pattern_xyz"}, %{})
    end
  end

  # ============================================================================
  # Integration: Tool.Runner + FilePermission callback chain (second layer)
  # ============================================================================

  describe "Runner integration — two-layer permission stack" do
    setup do
      Registry.clear()
      PolicyEngine.reset()
      Callbacks.clear(:file_permission)

      Registry.register(CpListFiles)
      Registry.register(CpReadFile)
      Registry.register(CpGrep)

      on_exit(fn ->
        Registry.clear()
      end)

      :ok
    end

    defp allow_all_policy do
      PolicyEngine.add_rule(%PolicyRule{
        tool_name: "*",
        decision: :allow,
        priority: 1,
        source: "cp_file_ops_test"
      })

      on_exit(fn ->
        PolicyEngine.remove_rules_by_source("cp_file_ops_test")
      end)
    end

    # ── Layer 1: Tool permission_check (hard gate) ─────────────────────────

    test "CpListFiles: hard gate blocks sensitive path even with allow-all policy" do
      allow_all_policy()

      result =
        Runner.invoke(
          :cp_list_files,
          %{"directory" => Path.join(System.user_home!(), ".ssh")},
          %{}
        )

      assert {:error, reason} = result
      assert reason =~ "permission denied"
      assert reason =~ "sensitive path blocked"
    end

    test "CpReadFile: hard gate blocks sensitive path even with allow-all policy" do
      allow_all_policy()

      result =
        Runner.invoke(
          :cp_read_file,
          %{"file_path" => Path.join(System.user_home!(), ".ssh/id_rsa")},
          %{}
        )

      assert {:error, reason} = result
      assert reason =~ "permission denied"
      assert reason =~ "sensitive path blocked"
    end

    test "CpGrep: hard gate blocks sensitive path even with allow-all policy" do
      allow_all_policy()

      result =
        Runner.invoke(
          :cp_grep,
          %{"directory" => "/etc", "search_string" => "password"},
          %{}
        )

      assert {:error, reason} = result
      assert reason =~ "permission denied"
      assert reason =~ "sensitive path blocked"
    end

    # ── Layer 2: FilePermission callback chain (policy gate) ───────────────

    test "CpListFiles: callback deny blocks safe path" do
      allow_all_policy()

      deny_cb = fn _ctx, _path, _op, _, _, _ -> false end
      Callbacks.register(:file_permission, deny_cb)

      result = Runner.invoke(:cp_list_files, %{"directory" => @test_dir}, %{})
      assert {:error, reason} = result
      assert reason =~ "permission denied"
      assert reason =~ "blocked by security plugin"

      Callbacks.unregister(:file_permission, deny_cb)
    end

    test "CpReadFile: callback deny blocks safe path" do
      allow_all_policy()

      deny_cb = fn _ctx, _path, _op, _, _, _ -> false end
      Callbacks.register(:file_permission, deny_cb)

      result =
        Runner.invoke(
          :cp_read_file,
          %{"file_path" => Path.join(@test_dir, "hello.txt")},
          %{}
        )

      assert {:error, reason} = result
      assert reason =~ "permission denied"

      Callbacks.unregister(:file_permission, deny_cb)
    end

    test "CpGrep: callback deny blocks safe path" do
      allow_all_policy()

      deny_cb = fn _ctx, _path, _op, _, _, _ -> false end
      Callbacks.register(:file_permission, deny_cb)

      result =
        Runner.invoke(
          :cp_grep,
          %{"directory" => @test_dir, "search_string" => "def"},
          %{}
        )

      assert {:error, reason} = result
      assert reason =~ "permission denied"

      Callbacks.unregister(:file_permission, deny_cb)
    end

    # ── Both layers: allow when both pass ──────────────────────────────────

    test "CpListFiles: both layers pass → tool executes" do
      allow_all_policy()

      result = Runner.invoke(:cp_list_files, %{"directory" => @test_dir}, %{})
      assert {:ok, %{files: _}} = result
    end

    test "CpReadFile: both layers pass → tool executes" do
      allow_all_policy()

      result =
        Runner.invoke(
          :cp_read_file,
          %{"file_path" => Path.join(@test_dir, "hello.txt")},
          %{}
        )

      assert {:ok, _} = result
    end

    test "CpGrep: both layers pass → tool executes" do
      allow_all_policy()

      result =
        Runner.invoke(
          :cp_grep,
          %{"directory" => @test_dir, "search_string" => "Hello"},
          %{}
        )

      assert {:ok, %{matches: _}} = result
    end

    # ── Callback chain path verification ──────────────────────────────────

    test "CpListFiles: FilePermission receives directory path" do
      allow_all_policy()

      test_pid = self()

      spy_cb = fn _ctx, path, _op, _, _, _ ->
        send(test_pid, {:file_perm_path, path})
        nil
      end

      Callbacks.register(:file_permission, spy_cb)

      Runner.invoke(:cp_list_files, %{"directory" => @test_dir}, %{})
      assert_received {:file_perm_path, @test_dir}

      Callbacks.unregister(:file_permission, spy_cb)
    end

    test "CpGrep: FilePermission receives directory path" do
      allow_all_policy()

      test_pid = self()

      spy_cb = fn _ctx, path, _op, _, _, _ ->
        send(test_pid, {:file_perm_path, path})
        nil
      end

      Callbacks.register(:file_permission, spy_cb)

      Runner.invoke(:cp_grep, %{"directory" => @test_dir, "search_string" => "x"}, %{})
      assert_received {:file_perm_path, @test_dir}

      Callbacks.unregister(:file_permission, spy_cb)
    end

    test "CpReadFile: FilePermission receives file_path" do
      allow_all_policy()

      file_path = Path.join(@test_dir, "hello.txt")
      test_pid = self()

      spy_cb = fn _ctx, path, _op, _, _, _ ->
        send(test_pid, {:file_perm_path, path})
        nil
      end

      Callbacks.register(:file_permission, spy_cb)

      Runner.invoke(:cp_read_file, %{"file_path" => file_path}, %{})
      assert_received {:file_perm_path, ^file_path}

      Callbacks.unregister(:file_permission, spy_cb)
    end

    # ── Default directory path propagation ────────────────────────────────

    test "CpListFiles: FilePermission receives \".\" when directory omitted" do
      allow_all_policy()

      test_pid = self()

      spy_cb = fn _ctx, path, _op, _, _, _ ->
        send(test_pid, {:file_perm_path, path})
        nil
      end

      Callbacks.register(:file_permission, spy_cb)

      Runner.invoke(:cp_list_files, %{}, %{})
      assert_received {:file_perm_path, "."}

      Callbacks.unregister(:file_permission, spy_cb)
    end

    test "CpGrep: FilePermission receives \".\" when directory omitted" do
      allow_all_policy()

      test_pid = self()

      spy_cb = fn _ctx, path, _op, _, _, _ ->
        send(test_pid, {:file_perm_path, path})
        nil
      end

      Callbacks.register(:file_permission, spy_cb)

      Runner.invoke(:cp_grep, %{"search_string" => "TODO"}, %{})
      assert_received {:file_perm_path, "."}

      Callbacks.unregister(:file_permission, spy_cb)
    end

    # ── PolicyEngine deny ─────────────────────────────────────────────────

    test "CpListFiles: PolicyEngine deny blocks even for safe path" do
      PolicyEngine.add_rule(%PolicyRule{
        tool_name: "cp_list_files",
        decision: :deny,
        priority: 10,
        source: "cp_file_ops_test"
      })

      result = Runner.invoke(:cp_list_files, %{"directory" => @test_dir}, %{})
      assert {:error, reason} = result
      assert reason =~ "Denied by policy"
    end

    test "CpReadFile: PolicyEngine deny blocks even for safe path" do
      PolicyEngine.add_rule(%PolicyRule{
        tool_name: "cp_read_file",
        decision: :deny,
        priority: 10,
        source: "cp_file_ops_test"
      })

      result =
        Runner.invoke(
          :cp_read_file,
          %{"file_path" => Path.join(@test_dir, "hello.txt")},
          %{}
        )

      assert {:error, reason} = result
      assert reason =~ "Denied by policy"
    end
  end

  # ============================================================================
  # Result shape parity with bridge callers
  # ============================================================================

  describe "result shapes match bridge-caller expectations" do
    test "CpListFiles result contains file_info maps with expected keys", %{test_dir: dir} do
      assert {:ok, %{files: [file | _]}} =
               CpListFiles.invoke(%{"directory" => dir, "recursive" => false}, %{})

      # Bridge callers expect: path, size, type, modified
      assert Map.has_key?(file, :path)
      assert Map.has_key?(file, :size)
      assert Map.has_key?(file, :type)
      assert Map.has_key?(file, :modified)

      assert file.type in [:file, :directory]
      assert is_integer(file.size)
    end

    test "CpReadFile result matches read_result type spec", %{test_dir: dir} do
      file_path = Path.join(dir, "hello.txt")
      assert {:ok, result} = CpReadFile.invoke(%{"file_path" => file_path}, %{})

      # Bridge callers expect: path, content, num_lines, size, truncated, error
      assert Map.has_key?(result, :path)
      assert Map.has_key?(result, :content)
      assert Map.has_key?(result, :num_lines)
      assert Map.has_key?(result, :size)
      assert Map.has_key?(result, :truncated)
      assert Map.has_key?(result, :error)

      assert is_binary(result.content)
      assert is_integer(result.num_lines)
      assert is_integer(result.size)
      assert is_boolean(result.truncated)
    end

    test "CpGrep result contains match maps with expected keys", %{test_dir: dir} do
      assert {:ok, %{matches: [match | _]}} =
               CpGrep.invoke(%{"search_string" => "Hello", "directory" => dir}, %{})

      # Bridge callers expect: file, line_number, line_content, match_start, match_end
      assert Map.has_key?(match, :file)
      assert Map.has_key?(match, :line_number)
      assert Map.has_key?(match, :line_content)
      assert Map.has_key?(match, :match_start)
      assert Map.has_key?(match, :match_end)

      assert is_binary(match.file)
      assert is_integer(match.line_number)
      assert is_binary(match.line_content)
      assert is_integer(match.match_start)
      assert is_integer(match.match_end)
    end

    test "CpReadFile error result shape for non-existent file" do
      assert {:error, reason} =
               CpReadFile.invoke(%{"file_path" => "/nonexistent_xyz.txt"}, %{})

      # Error is a string (inspect of the reason)
      assert is_binary(reason)
    end

    test "CpGrep error result shape for invalid regex" do
      assert {:error, reason} =
               CpGrep.invoke(%{"search_string" => "[invalid", "directory" => @test_dir}, %{})

      assert is_binary(reason)
    end
  end
end
