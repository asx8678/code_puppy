defmodule CodePuppyControl.Tools.FileModifications.CreateFileEnhancedTest do
  @moduledoc "Enhanced tests for CreateFile — BOM, whitespace, symlink, validation."

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.FileModifications.CreateFile

  @tmp_dir System.tmp_dir!()

  describe "invoke/2 with BOM handling" do
    test "preserves BOM when overwriting existing file" do
      path = Path.join(@tmp_dir, "create_bom_test_#{:erlang.unique_integer([:positive])}.txt")
      bom = <<0xEF, 0xBB, 0xBF>>
      File.write!(path, bom <> "original content")

      args = %{
        "file_path" => path,
        "content" => "new content",
        "overwrite" => true
      }

      assert {:ok, result} = CreateFile.invoke(args, %{})
      assert result.success == true
      # BOM should be preserved
      assert File.read!(path) == bom <> "new content"

      File.rm(path)
    end

    test "handles file without BOM correctly" do
      path = Path.join(@tmp_dir, "create_no_bom_test_#{:erlang.unique_integer([:positive])}.txt")
      File.write!(path, "no bom here")

      args = %{
        "file_path" => path,
        "content" => "updated content",
        "overwrite" => true
      }

      assert {:ok, result} = CreateFile.invoke(args, %{})
      assert result.success == true
      # No BOM should be added
      assert File.read!(path) == "updated content"

      File.rm(path)
    end
  end

  describe "invoke/2 with whitespace stripping" do
    test "strips surplus leading blank lines from LLM output" do
      path = Path.join(@tmp_dir, "create_ws_test_#{:erlang.unique_integer([:positive])}.txt")
      File.write!(path, "line 1\nline 2\n")

      args = %{
        "file_path" => path,
        "content" => "\n\n\nline 1\nline 2\n",
        "overwrite" => true
      }

      assert {:ok, result} = CreateFile.invoke(args, %{})
      assert result.success == true
      # Surplus leading blank lines should be stripped
      content = File.read!(path)
      refute String.starts_with?(content, "\n\n\n")

      File.rm(path)
    end

    test "preserves original leading blank lines" do
      path = Path.join(@tmp_dir, "create_ws_preserve_#{:erlang.unique_integer([:positive])}.txt")
      File.write!(path, "\nline 1\nline 2\n")

      args = %{
        "file_path" => path,
        "content" => "\nmodified line 1\nline 2\n",
        "overwrite" => true
      }

      assert {:ok, result} = CreateFile.invoke(args, %{})
      assert result.success == true
      # Original had 1 leading blank line, so 1 is preserved
      content = File.read!(path)
      assert String.starts_with?(content, "\n")

      File.rm(path)
    end
  end

  describe "invoke/2 with symlink protection" do
    test "refuses to overwrite a symlink" do
      target = Path.join(@tmp_dir, "create_symlink_target_#{:erlang.unique_integer([:positive])}.txt")
      link = Path.join(@tmp_dir, "create_symlink_link_#{:erlang.unique_integer([:positive])}.txt")

      File.write!(target, "target content")
      File.ln_s!(target, link)

      args = %{
        "file_path" => link,
        "content" => "evil content",
        "overwrite" => true
      }

      assert {:error, result} = CreateFile.invoke(args, %{})
      assert result.message =~ "symlink"
      # Target should be unmodified
      assert File.read!(target) == "target content"

      File.rm(target)
      File.rm(link)
    end

    test "refuses to create a new file at a symlink path" do
      target = Path.join(@tmp_dir, "create_symlink_new_target_#{:erlang.unique_integer([:positive])}.txt")
      link = Path.join(@tmp_dir, "create_symlink_new_link_#{:erlang.unique_integer([:positive])}.txt")

      File.write!(target, "target content")
      File.ln_s!(target, link)

      args = %{
        "file_path" => link,
        "content" => "new content"
      }

      # The file exists (as a symlink), and overwrite is false
      assert {:error, result} = CreateFile.invoke(args, %{})
      # Either "already exists" or "symlink" — both are correct rejections
      assert result.success == false

      File.rm(target)
      File.rm(link)
    end
  end

  describe "invoke/2 with post-edit validation" do
    test "attaches syntax warning for invalid Elixir code" do
      path = Path.join(@tmp_dir, "create_validation_#{:erlang.unique_integer([:positive])}.ex")

      args = %{
        "file_path" => path,
        "content" => "defmodule Foo do\n  def bar(\nend"
      }

      assert {:ok, result} = CreateFile.invoke(args, %{})
      assert result.success == true
      # Should have syntax_warning for invalid Elixir
      assert Map.has_key?(result, :syntax_warning)

      File.rm(path)
    end

    test "no syntax warning for valid Elixir code" do
      path = Path.join(@tmp_dir, "create_valid_ex_#{:erlang.unique_integer([:positive])}.ex")

      args = %{
        "file_path" => path,
        "content" => "defmodule Foo do\n  def bar, do: :baz\nend"
      }

      assert {:ok, result} = CreateFile.invoke(args, %{})
      assert result.success == true
      refute Map.has_key?(result, :syntax_warning)

      File.rm(path)
    end

    test "no syntax warning for non-code extensions" do
      path = Path.join(@tmp_dir, "create_txt_#{:erlang.unique_integer([:positive])}.txt")

      args = %{
        "file_path" => path,
        "content" => "just text"
      }

      assert {:ok, result} = CreateFile.invoke(args, %{})
      assert result.success == true
      refute Map.has_key?(result, :syntax_warning)

      File.rm(path)
    end
  end
end
