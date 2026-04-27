defmodule CodePuppyControl.Tools.FileModifications.SafeWriteTest do
  @moduledoc "Tests for SafeWrite — symlink-safe file writing."

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.FileModifications.SafeWrite

  @tmp_dir System.tmp_dir!()

  describe "safe_write/2" do
    test "writes content to a new file" do
      path = Path.join(@tmp_dir, "safe_write_new_#{:erlang.unique_integer([:positive])}.txt")

      assert :ok = SafeWrite.safe_write(path, "hello world")
      assert File.read!(path) == "hello world"

      File.rm(path)
    end

    test "overwrites existing file content" do
      path =
        Path.join(@tmp_dir, "safe_write_overwrite_#{:erlang.unique_integer([:positive])}.txt")

      File.write!(path, "original")

      assert :ok = SafeWrite.safe_write(path, "updated")
      assert File.read!(path) == "updated"

      File.rm(path)
    end

    test "creates parent directories if they don't exist" do
      subdir = Path.join(@tmp_dir, "safe_write_nested_#{:erlang.unique_integer([:positive])}")
      path = Path.join([subdir, "deep", "file.txt"])

      assert :ok = SafeWrite.safe_write(path, "nested content")
      assert File.exists?(path)

      File.rm_rf!(subdir)
    end

    test "refuses to write to a symlink" do
      target = Path.join(@tmp_dir, "safe_write_target_#{:erlang.unique_integer([:positive])}.txt")
      link = Path.join(@tmp_dir, "safe_write_link_#{:erlang.unique_integer([:positive])}.txt")

      File.write!(target, "target content")
      File.ln_s!(target, link)

      assert {:error, :symlink_detected} = SafeWrite.safe_write(link, "evil content")
      # Target should not be modified
      assert File.read!(target) == "target content"

      File.rm(target)
      File.rm(link)
    end

    test "rejects paths with null bytes" do
      assert {:error, reason} = SafeWrite.safe_write("/tmp/test\0.txt", "content")
      assert reason =~ "null byte"
    end

    test "writes UTF-8 content correctly" do
      path = Path.join(@tmp_dir, "safe_write_utf8_#{:erlang.unique_integer([:positive])}.txt")

      assert :ok = SafeWrite.safe_write(path, "日本語テスト 🐶")
      assert File.read!(path) == "日本語テスト 🐶"

      File.rm(path)
    end

    test "writes content with BOM correctly" do
      path = Path.join(@tmp_dir, "safe_write_bom_#{:erlang.unique_integer([:positive])}.txt")
      bom = <<0xEF, 0xBB, 0xBF>>
      content = bom <> "BOM content"

      assert :ok = SafeWrite.safe_write(path, content)
      assert File.read!(path) == content

      File.rm(path)
    end
  end

  describe "symlink?/1" do
    test "returns true for symlinks" do
      target = Path.join(@tmp_dir, "symlink_target_#{:erlang.unique_integer([:positive])}.txt")
      link = Path.join(@tmp_dir, "symlink_link_#{:erlang.unique_integer([:positive])}.txt")

      File.write!(target, "target")
      File.ln_s!(target, link)

      assert SafeWrite.symlink?(link) == true

      File.rm(target)
      File.rm(link)
    end

    test "returns false for regular files" do
      path = Path.join(@tmp_dir, "symlink_regular_#{:erlang.unique_integer([:positive])}.txt")
      File.write!(path, "regular")

      assert SafeWrite.symlink?(path) == false

      File.rm(path)
    end

    test "returns false for non-existent files" do
      assert SafeWrite.symlink?("/tmp/nonexistent_abc123.txt") == false
    end

    test "returns false for directories" do
      dir = Path.join(@tmp_dir, "symlink_dir_#{:erlang.unique_integer([:positive])}")
      File.mkdir_p!(dir)

      assert SafeWrite.symlink?(dir) == false

      File.rmdir(dir)
    end
  end
end
