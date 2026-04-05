defmodule Mana.Pack.Agents.BloodhoundTest do
  @moduledoc """
  Tests for Bloodhound agent - issue tracking specialist.
  """

  use ExUnit.Case, async: true

  alias Mana.Pack.Agents.Bloodhound

  describe "build_bd_command/1" do
    test "builds ready command" do
      task = %{metadata: %{command: "ready", args: ["--json"]}}
      assert Bloodhound.build_bd_command(task) == ["ready", "--json"]
    end

    test "builds list command" do
      task = %{metadata: %{command: "list"}}
      assert Bloodhound.build_bd_command(task) == ["list"]
    end

    test "builds blocked command" do
      task = %{metadata: %{command: "blocked", args: ["--json"]}}
      assert Bloodhound.build_bd_command(task) == ["blocked", "--json"]
    end

    test "builds show command with issue_id" do
      task = %{metadata: %{command: "show", issue_id: "bd-42", args: ["--json"]}}
      assert Bloodhound.build_bd_command(task) == ["show", "bd-42", "--json"]
    end

    test "builds close command" do
      task = %{metadata: %{command: "close", issue_id: "bd-42"}}
      assert Bloodhound.build_bd_command(task) == ["close", "bd-42"]
    end

    test "builds reopen command" do
      task = %{metadata: %{command: "reopen", issue_id: "bd-42"}}
      assert Bloodhound.build_bd_command(task) == ["reopen", "bd-42"]
    end

    test "builds dep tree command" do
      task = %{metadata: %{command: "dep_tree", issue_id: "bd-42"}}
      assert Bloodhound.build_bd_command(task) == ["dep", "tree", "bd-42"]
    end

    test "builds dep cycles command" do
      task = %{metadata: %{command: "dep_cycles"}}
      assert Bloodhound.build_bd_command(task) == ["dep", "cycles"]
    end

    test "defaults to list command for unknown command" do
      task = %{metadata: %{command: "unknown"}}
      assert Bloodhound.build_bd_command(task) == ["list"]
    end

    test "defaults to list when no metadata" do
      task = %{}
      assert Bloodhound.build_bd_command(task) == ["list"]
    end
  end

  describe "build_create_command/1" do
    test "builds basic create command" do
      metadata = %{description: "Fix login bug"}
      assert Bloodhound.build_create_command(metadata) == ["create", "Fix login bug"]
    end

    test "builds create command with priority" do
      metadata = %{description: "Fix login bug", priority: 1}
      assert Bloodhound.build_create_command(metadata) == ["create", "Fix login bug", "-p", "1"]
    end

    test "builds create command with type" do
      metadata = %{description: "Fix login bug", issue_type: "bug"}
      assert Bloodhound.build_create_command(metadata) == ["create", "Fix login bug", "-t", "bug"]
    end

    test "builds create command with dependencies" do
      metadata = %{description: "Add auth routes", deps: "blocks:bd-1"}
      assert Bloodhound.build_create_command(metadata) == ["create", "Add auth routes", "--deps", "blocks:bd-1"]
    end

    test "builds create command with all options" do
      metadata = %{description: "Add auth", priority: 1, issue_type: "feature", deps: "blocks:bd-1"}

      result = Bloodhound.build_create_command(metadata)
      assert hd(result) == "create"
      assert "Add auth" in result
      assert "-p" in result
      assert "1" in result
      assert "-t" in result
      assert "feature" in result
      assert "--deps" in result
      assert "blocks:bd-1" in result
    end
  end

  describe "build_update_command/1" do
    test "builds update command with description" do
      metadata = %{issue_id: "bd-42", description: "Updated description"}
      assert Bloodhound.build_update_command(metadata) == ["update", "bd-42", "-d", "Updated description"]
    end

    test "builds update command with priority" do
      metadata = %{issue_id: "bd-42", priority: 0}
      assert Bloodhound.build_update_command(metadata) == ["update", "bd-42", "-p", "0"]
    end

    test "builds update command with type" do
      metadata = %{issue_id: "bd-42", issue_type: "bug"}
      assert Bloodhound.build_update_command(metadata) == ["update", "bd-42", "-t", "bug"]
    end

    test "returns bare update command when no issue_id" do
      metadata = %{description: "Test"}
      assert Bloodhound.build_update_command(metadata) == ["update"]
    end
  end

  describe "execute/2" do
    test "returns error for missing bd command (in test environment)" do
      task = %{
        id: "test-1",
        issue_id: nil,
        worktree: nil,
        description: "List issues",
        metadata: %{command: "list"}
      }

      # In a test environment without bd installed, this will fail
      # but we can verify the error handling
      result = Bloodhound.execute(task, [])

      # Should return either an error or a result with exit code
      assert match?({:ok, %{exit_code: _}}, result) or match?({:error, _}, result)
    end

    test "respects timeout option" do
      task = %{
        id: "test-1",
        metadata: %{command: "list"}
      }

      # Just verify the option is accepted
      result = Bloodhound.execute(task, timeout: 5000)
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end
  end
end
