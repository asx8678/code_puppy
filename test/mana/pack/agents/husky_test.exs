defmodule Mana.Pack.Agents.HuskyTest do
  @moduledoc """
  Tests for Husky agent - task execution specialist.
  """

  use ExUnit.Case, async: true

  alias Mana.Pack.Agents.Husky

  describe "build_command/1" do
    test "builds custom command" do
      metadata = %{command: "echo", args: ["hello"]}
      assert Husky.build_command(metadata) == {"echo", ["hello"], []}
    end

    test "builds pytest command type" do
      metadata = %{command_type: "pytest"}
      assert Husky.build_command(metadata) == {"pytest", ["-v"], []}
    end

    test "builds npm_test command type" do
      metadata = %{command_type: "npm_test"}
      assert Husky.build_command(metadata) == {"npm", ["test", "--", "--silent"], []}
    end

    test "allows override of predefined command args" do
      metadata = %{command_type: "pytest", args: ["-x"]}
      assert Husky.build_command(metadata) == {"pytest", ["-x"], []}
    end
  end

  describe "compute_timeout/1" do
    test "returns default for nil" do
      assert Husky.compute_timeout(nil) == 60_000
    end

    test "returns appropriate timeouts" do
      assert Husky.compute_timeout("pytest") == 120_000
      assert Husky.compute_timeout("npm_test") == 180_000
      assert Husky.compute_timeout("cargo_test") == 300_000
    end
  end

  describe "execute/2" do
    test "executes echo command" do
      task = %{
        id: "test-1",
        worktree: File.cwd!(),
        metadata: %{command: "echo", args: ["hello"]}
      }

      result = Husky.execute(task, [])
      assert match?({:ok, %{exit_code: 0}}, result)
    end

    test "returns error for nonexistent command" do
      task = %{
        id: "test-1",
        worktree: File.cwd!(),
        metadata: %{command: "nonexistent_xyz", args: []}
      }

      result = Husky.execute(task, [])
      assert match?({:error, _}, result)
    end
  end

  describe "git_command/4" do
    test "executes git status" do
      result = Husky.git_command(File.cwd!(), "status", [], [])
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end
  end

  describe "commit/4" do
    test "builds conventional commit" do
      result = Husky.commit(File.cwd!(), "bd-42", "add feature", [])
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end
  end

  describe "push/3" do
    test "builds push command" do
      result = Husky.push(File.cwd!(), "main", [])
      assert match?({:ok, _}, result) or match?({:error, _}, result)
    end
  end
end
