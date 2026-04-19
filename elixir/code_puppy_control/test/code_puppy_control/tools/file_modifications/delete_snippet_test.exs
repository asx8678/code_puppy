defmodule CodePuppyControl.Tools.FileModifications.DeleteSnippetTest do
  @moduledoc "Tests for the DeleteSnippet tool."

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.FileModifications.DeleteSnippet

  @tmp_dir System.tmp_dir!()

  describe "name/0" do
    test "returns :delete_snippet" do
      assert DeleteSnippet.name() == :delete_snippet
    end
  end

  describe "parameters/0" do
    test "requires file_path and snippet" do
      schema = DeleteSnippet.parameters()
      assert "file_path" in schema["required"]
      assert "snippet" in schema["required"]
    end
  end

  describe "invoke/2" do
    test "removes first occurrence of snippet" do
      path = Path.join(@tmp_dir, "del_snippet_test_#{:rand.uniform(10000)}.txt")
      File.write!(path, "line 1\nREMOVE ME\nline 3")

      args = %{
        "file_path" => path,
        "snippet" => "REMOVE ME"
      }

      assert {:ok, result} = DeleteSnippet.invoke(args, %{})
      assert result.success == true
      assert result.changed == true
      assert File.read!(path) == "line 1\n\nline 3"

      File.rm(path)
    end

    test "removes only the first occurrence" do
      path = Path.join(@tmp_dir, "del_snippet_first_test_#{:rand.uniform(10000)}.txt")
      File.write!(path, "aaa xxx bbb xxx ccc")

      args = %{
        "file_path" => path,
        "snippet" => " xxx "
      }

      assert {:ok, result} = DeleteSnippet.invoke(args, %{})
      assert result.success == true
      # Only first " xxx " removed
      assert File.read!(path) == "aaabbb xxx ccc"

      File.rm(path)
    end

    test "fails when snippet not found" do
      path = Path.join(@tmp_dir, "del_snippet_notfound_test_#{:rand.uniform(10000)}.txt")
      File.write!(path, "nothing to remove here")

      args = %{
        "file_path" => path,
        "snippet" => "NOT FOUND"
      }

      assert {:error, result} = DeleteSnippet.invoke(args, %{})
      assert result.message =~ "not found"

      File.rm(path)
    end

    test "fails with empty snippet" do
      path = Path.join(@tmp_dir, "del_snippet_empty_test_#{:rand.uniform(10000)}.txt")
      File.write!(path, "content")

      args = %{
        "file_path" => path,
        "snippet" => ""
      }

      assert {:error, reason} = DeleteSnippet.invoke(args, %{})
      assert reason =~ "empty"

      File.rm(path)
    end

    test "fails on non-existent file" do
      args = %{
        "file_path" => "/tmp/nonexistent_#{:rand.uniform(10000)}.txt",
        "snippet" => "anything"
      }

      assert {:error, result} = DeleteSnippet.invoke(args, %{})
      assert result.message =~ "not found"
    end

    test "generates diff" do
      path = Path.join(@tmp_dir, "del_snippet_diff_test_#{:rand.uniform(10000)}.txt")
      File.write!(path, "keep this\nremove that\nkeep this too")

      args = %{
        "file_path" => path,
        "snippet" => "remove that\n"
      }

      assert {:ok, result} = DeleteSnippet.invoke(args, %{})
      assert result.diff =~ "-remove that"

      File.rm(path)
    end
  end

  describe "permission_check/2" do
    test "allows non-sensitive paths" do
      args = %{"file_path" => "/tmp/safe_file.txt"}
      assert :ok = DeleteSnippet.permission_check(args, %{})
    end

    test "denies sensitive paths" do
      args = %{"file_path" => Path.join(System.user_home!(), ".ssh/config")}
      assert {:deny, _reason} = DeleteSnippet.permission_check(args, %{})
    end
  end
end
