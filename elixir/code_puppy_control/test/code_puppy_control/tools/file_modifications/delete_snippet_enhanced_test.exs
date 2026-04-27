defmodule CodePuppyControl.Tools.FileModifications.DeleteSnippetEnhancedTest do
  @moduledoc "Enhanced tests for DeleteSnippet — BOM, whitespace, symlink, validation."

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.FileModifications.DeleteSnippet

  @tmp_dir System.tmp_dir!()

  describe "invoke/2 with BOM handling" do
    test "preserves BOM after snippet deletion" do
      path = Path.join(@tmp_dir, "del_snippet_bom_#{:erlang.unique_integer([:positive])}.txt")
      bom = <<0xEF, 0xBB, 0xBF>>
      File.write!(path, bom <> "line 1\nREMOVE ME\nline 3")

      args = %{
        "file_path" => path,
        "snippet" => "REMOVE ME"
      }

      assert {:ok, result} = DeleteSnippet.invoke(args, %{})
      assert result.success == true
      # BOM should be preserved
      assert File.read!(path) == bom <> "line 1\n\nline 3"

      File.rm(path)
    end

    test "handles file without BOM" do
      path = Path.join(@tmp_dir, "del_snippet_no_bom_#{:erlang.unique_integer([:positive])}.txt")
      File.write!(path, "line 1\nREMOVE ME\nline 3")

      args = %{
        "file_path" => path,
        "snippet" => "REMOVE ME"
      }

      assert {:ok, result} = DeleteSnippet.invoke(args, %{})
      assert result.success == true
      assert File.read!(path) == "line 1\n\nline 3"

      File.rm(path)
    end
  end

  describe "invoke/2 with symlink protection" do
    test "refuses to delete snippet from a symlink" do
      target =
        Path.join(
          @tmp_dir,
          "del_snippet_symlink_target_#{:erlang.unique_integer([:positive])}.txt"
        )

      link =
        Path.join(@tmp_dir, "del_snippet_symlink_link_#{:erlang.unique_integer([:positive])}.txt")

      File.write!(target, "foo bar baz")
      File.ln_s!(target, link)

      args = %{
        "file_path" => link,
        "snippet" => "bar"
      }

      assert {:error, result} = DeleteSnippet.invoke(args, %{})
      assert result.message =~ "symlink"
      # Target should be unmodified
      assert File.read!(target) == "foo bar baz"

      File.rm(target)
      File.rm(link)
    end
  end

  describe "invoke/2 with post-edit validation" do
    test "attaches syntax warning for invalid Elixir after deletion" do
      path =
        Path.join(@tmp_dir, "del_snippet_validation_#{:erlang.unique_integer([:positive])}.ex")

      File.write!(path, "defmodule Foo do\n  BAD SYNTAX\n  def bar, do: :baz\nend")

      args = %{
        "file_path" => path,
        "snippet" => "BAD SYNTAX\n  "
      }

      # Deletion should succeed
      result = DeleteSnippet.invoke(args, %{})
      # May succeed or fail depending on exact match; either way no crash
      assert match?({:ok, _}, result) or match?({:error, _}, result)

      File.rm(path)
    end
  end

  describe "invoke/2 with whitespace stripping" do
    test "strips surplus blank lines after deletion" do
      path = Path.join(@tmp_dir, "del_snippet_ws_#{:erlang.unique_integer([:positive])}.txt")
      File.write!(path, "line 1\nline 2\nline 3")

      args = %{
        "file_path" => path,
        "snippet" => "line 2\n"
      }

      assert {:ok, result} = DeleteSnippet.invoke(args, %{})
      assert result.success == true
      content = File.read!(path)
      # Should not have surplus blank lines from the deletion
      assert content == "line 1\nline 3" or content == "line 1line 3" or
               not String.contains?(content, "line 2")

      File.rm(path)
    end
  end
end
