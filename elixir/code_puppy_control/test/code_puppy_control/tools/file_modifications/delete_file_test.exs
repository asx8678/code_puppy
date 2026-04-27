defmodule CodePuppyControl.Tools.FileModifications.DeleteFileTest do
  @moduledoc "Tests for the DeleteFile tool (stat-based, no deleted_content)."

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.FileModifications.DeleteFile

  @tmp_dir System.tmp_dir!()

  describe "name/0" do
    test "returns :delete_file" do
      assert DeleteFile.name() == :delete_file
    end
  end

  describe "parameters/0" do
    test "requires file_path" do
      schema = DeleteFile.parameters()
      assert "file_path" in schema["required"]
    end
  end

  describe "invoke/2" do
    test "deletes an existing file" do
      path = Path.join(@tmp_dir, "delete_test_#{:rand.uniform(10000)}.txt")
      File.write!(path, "delete me")

      args = %{"file_path" => path}

      assert {:ok, result} = DeleteFile.invoke(args, %{})
      assert result.success == true
      assert result.changed == true
      assert not File.exists?(path)
    end

    test "does NOT return deleted_content (large-file safety)" do
      path = Path.join(@tmp_dir, "delete_no_content_#{:rand.uniform(10000)}.txt")
      File.write!(path, "important content")

      args = %{"file_path" => path}

      assert {:ok, result} = DeleteFile.invoke(args, %{})
      refute Map.has_key?(result, :deleted_content)
    end

    test "generates summary diff (lines/bytes)" do
      path = Path.join(@tmp_dir, "delete_diff_test_#{:rand.uniform(10000)}.txt")
      File.write!(path, "line 1\nline 2\n")

      args = %{"file_path" => path}

      assert {:ok, result} = DeleteFile.invoke(args, %{})
      assert result.diff =~ "lines"
      assert result.diff =~ "bytes"
    end

    test "fails on non-existent file" do
      args = %{"file_path" => "/tmp/nonexistent_#{:rand.uniform(10000)}.txt"}

      assert {:error, result} = DeleteFile.invoke(args, %{})
      assert result.message =~ "not found"
    end

    test "refuses to delete directories" do
      path = Path.join(@tmp_dir, "delete_dir_test_#{:rand.uniform(10000)}")
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
