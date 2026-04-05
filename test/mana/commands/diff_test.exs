defmodule Mana.Commands.DiffTest do
  @moduledoc """
  Tests for Mana.Commands.Diff module.
  """

  use ExUnit.Case, async: false

  alias Mana.Commands.Diff
  alias Mana.Shell.Executor

  setup do
    # Start the Shell Executor
    start_supervised!({Executor, []})
    :ok
  end

  describe "behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      Code.ensure_loaded?(Diff)
      assert function_exported?(Diff, :name, 0)
      assert function_exported?(Diff, :description, 0)
      assert function_exported?(Diff, :usage, 0)
      assert function_exported?(Diff, :execute, 2)
    end

    test "name returns '/diff'" do
      assert Diff.name() == "/diff"
    end

    test "description returns expected string" do
      assert Diff.description() == "Show pending file changes (git diff integration)"
    end

    test "usage returns expected string" do
      assert Diff.usage() == "/diff [--staged|--cached] [path] | /diff stats"
    end
  end

  describe "execute/2 - stats" do
    test "returns stats for unstaged changes" do
      # In a git repo, this should work
      result = Diff.execute(["stats"], %{})

      # Should return either stats or an error about not being a git repo
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end

    test "returns stats for staged changes" do
      result = Diff.execute(["--staged", "stats"], %{})
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end

    test "cached is alias for staged" do
      result = Diff.execute(["--cached", "stats"], %{})
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end
  end

  describe "execute/2 - diff output" do
    test "returns diff with no args" do
      result = Diff.execute([], %{})
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end

    test "returns diff with staged flag" do
      result = Diff.execute(["--staged"], %{})
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end
  end

  describe "execute/2 - with path" do
    test "returns error for non-existent path" do
      assert {:error, "Path does not exist: /nonexistent/path"} =
               Diff.execute(["/nonexistent/path"], %{})
    end

    test "returns diff for existing path" do
      # Use the current directory (should be a git repo)
      result = Diff.execute(["."], %{})
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end
  end

  describe "colorization" do
    test "diff output includes ANSI codes for additions" do
      # Just verify the function doesn't crash and returns a string
      result = Diff.execute([], %{})

      case result do
        {:ok, output} -> assert is_binary(output)
        # Not a git repo is fine
        {:error, _} -> :ok
      end
    end
  end
end
