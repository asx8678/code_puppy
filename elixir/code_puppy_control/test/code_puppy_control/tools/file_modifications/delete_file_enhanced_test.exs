defmodule CodePuppyControl.Tools.FileModifications.DeleteFileEnhancedTest do
  @moduledoc "Enhanced tests for DeleteFile — symlink protection, summary diff, no deleted_content."

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.FileModifications.DeleteFile

  @tmp_dir System.tmp_dir!()

  describe "invoke/2 with symlink protection" do
    test "refuses to delete a symlink" do
      target =
        Path.join(
          @tmp_dir,
          "delete_symlink_target_#{:erlang.unique_integer([:positive])}.txt"
        )

      link =
        Path.join(
          @tmp_dir,
          "delete_symlink_link_#{:erlang.unique_integer([:positive])}.txt"
        )

      File.write!(target, "target content")
      File.ln_s!(target, link)

      args = %{"file_path" => link}

      assert {:error, result} = DeleteFile.invoke(args, %{})
      assert result.message =~ "symlink"
      assert File.exists?(target)
      assert File.read!(target) == "target content"

      File.rm(target)
      File.rm(link)
    end
  end

  describe "invoke/2 with summary diff" do
    test "generates summary diff with lines and bytes" do
      path =
        Path.join(
          @tmp_dir,
          "delete_summary_#{:erlang.unique_integer([:positive])}.txt"
        )

      content = Enum.map_join(1..50, "\n", &"line #{&1}")
      File.write!(path, content)

      args = %{"file_path" => path}

      assert {:ok, result} = DeleteFile.invoke(args, %{})
      assert result.success == true
      assert result.diff =~ "lines"
      assert result.diff =~ "bytes"
    end

    test "does NOT include deleted_content field" do
      path =
        Path.join(
          @tmp_dir,
          "delete_no_deleted_content_#{:erlang.unique_integer([:positive])}.txt"
        )

      File.write!(path, "some content")

      args = %{"file_path" => path}

      assert {:ok, result} = DeleteFile.invoke(args, %{})
      refute Map.has_key?(result, :deleted_content)
    end
  end

  describe "invoke/2 edge cases" do
    test "fails on non-existent file" do
      args = %{
        "file_path" => "/tmp/nonexistent_#{:erlang.unique_integer([:positive])}.txt"
      }

      assert {:error, result} = DeleteFile.invoke(args, %{})
      assert result.message =~ "not found"
    end

    test "refuses to delete directories" do
      path =
        Path.join(@tmp_dir, "delete_dir_test_#{:erlang.unique_integer([:positive])}")

      File.mkdir_p!(path)

      args = %{"file_path" => path}

      assert {:error, result} = DeleteFile.invoke(args, %{})
      assert result.message =~ "Cannot delete directory"

      File.rmdir(path)
    end
  end

  describe "permission_check/2" do
    test "allows non-sensitive paths" do
      args = %{"file_path" => "/tmp/safe_to_delete.txt"}
      assert :ok = DeleteFile.permission_check(args, %{})
    end

    test "denies SSH key deletion" do
      args = %{"file_path" => Path.join(System.user_home!(), ".ssh/id_rsa")}
      assert {:deny, _reason} = DeleteFile.permission_check(args, %{})
    end
  end
end
