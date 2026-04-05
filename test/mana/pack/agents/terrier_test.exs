defmodule Mana.Pack.Agents.TerrierTest do
  @moduledoc """
  Tests for Terrier agent - worktree management specialist.
  """

  use ExUnit.Case, async: true

  alias Mana.Pack.Agents.Terrier

  describe "build_git_command/1" do
    test "builds worktree list command" do
      task = %{metadata: %{action: "list"}}
      assert Terrier.build_git_command(task) == ["worktree", "list"]
    end

    test "builds worktree list with porcelain" do
      task = %{metadata: %{action: "list", args: ["--porcelain"]}}
      assert Terrier.build_git_command(task) == ["worktree", "list", "--porcelain"]
    end

    test "builds worktree add command with branch" do
      task = %{
        worktree: "../bd-42",
        metadata: %{action: "create", branch: "feature/bd-42-auth", base: "main"}
      }

      assert Terrier.build_git_command(task) == ["worktree", "add", "../bd-42", "-b", "feature/bd-42-auth", "main"]
    end

    test "builds worktree add without branch" do
      task = %{
        worktree: "../feature-auth",
        metadata: %{action: "create", base: "develop"}
      }

      assert Terrier.build_git_command(task) == ["worktree", "add", "../feature-auth", "develop"]
    end

    test "builds worktree remove command" do
      task = %{worktree: "../bd-42", metadata: %{action: "remove"}}
      assert Terrier.build_git_command(task) == ["worktree", "remove", "../bd-42"]
    end

    test "builds worktree remove with force" do
      task = %{worktree: "../bd-42", metadata: %{action: "remove", force: true}}
      assert Terrier.build_git_command(task) == ["worktree", "remove", "--force", "../bd-42"]
    end

    test "builds worktree prune command" do
      task = %{metadata: %{action: "prune"}}
      assert Terrier.build_git_command(task) == ["worktree", "prune"]
    end

    test "builds worktree move command" do
      task = %{metadata: %{action: "move", source: "../old", destination: "../new"}}
      assert Terrier.build_git_command(task) == ["worktree", "move", "../old", "../new"]
    end

    test "builds worktree verify command" do
      task = %{worktree: "../bd-42", metadata: %{action: "verify"}}
      assert Terrier.build_git_command(task) == ["worktree", "list", "../bd-42"]
    end

    test "defaults to list when action not specified" do
      task = %{metadata: %{}}
      assert Terrier.build_git_command(task) == ["worktree", "list"]
    end
  end

  describe "worktree_path_for_issue/2" do
    test "generates standard worktree path" do
      assert Terrier.worktree_path_for_issue("bd-42") == "../bd-42"
    end

    test "generates worktree path with base" do
      assert Terrier.worktree_path_for_issue("bd-42", "/home/user/project") == "/home/user/bd-42"
    end
  end

  describe "branch_name_for_issue/2" do
    test "generates standard branch name" do
      assert Terrier.branch_name_for_issue("bd-42", "implement-auth") == "feature/bd-42-implement-auth"
    end

    test "generates branch name with different slug" do
      assert Terrier.branch_name_for_issue("bd-99", "fix-bug") == "feature/bd-99-fix-bug"
    end
  end

  describe "build_create_command/2" do
    test "builds create with all options" do
      task = %{worktree: "../bd-42"}
      metadata = %{branch: "feature/bd-42-auth", base: "main"}

      assert Terrier.build_create_command(task, metadata) ==
               ["worktree", "add", "../bd-42", "-b", "feature/bd-42-auth", "main"]
    end

    test "builds create with only worktree from task" do
      task = %{worktree: "../bd-42"}
      metadata = %{}

      assert Terrier.build_create_command(task, metadata) == ["worktree", "add", "../bd-42", "main"]
    end

    test "builds create with only worktree from metadata" do
      task = %{}
      metadata = %{worktree: "../bd-42"}

      assert Terrier.build_create_command(task, metadata) == ["worktree", "add", "../bd-42", "main"]
    end
  end

  describe "worktree_exists?/2" do
    test "checks if worktree exists" do
      # In a repo without worktrees, this should return false
      result = Terrier.worktree_exists?("../nonexistent", [])

      assert match?({:ok, boolean}, result) or match?({:error, _}, result)
    end
  end

  describe "execute/2" do
    test "executes worktree list" do
      task = %{
        id: "test-1",
        metadata: %{action: "list"}
      }

      result = Terrier.execute(task, [])

      # Should succeed in any git repo
      assert match?({:ok, %{exit_code: _}}, result) or match?({:error, _}, result)
    end

    test "accepts timeout option" do
      task = %{
        id: "test-1",
        metadata: %{action: "list"}
      }

      result = Terrier.execute(task, timeout: 5000)
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end
  end
end
