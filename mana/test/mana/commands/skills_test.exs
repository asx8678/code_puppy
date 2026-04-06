defmodule Mana.Commands.SkillsTest do
  @moduledoc """
  Tests for Mana.Commands.Skills module.
  """

  use ExUnit.Case, async: false

  alias Mana.Commands.Skills
  alias Mana.Plugins.AgentSkills

  setup do
    # Store test skills in persistent_term
    test_skills = [
      %{
        name: "test-skill",
        description: "A skill for testing",
        version: "1.0.0",
        author: "test",
        tags: ["test"],
        content: "Test skill content",
        source: "test"
      },
      %{
        name: "another-skill",
        description: "Another test skill",
        version: "1.0.0",
        author: "test",
        tags: [],
        content: "More content",
        source: "test"
      }
    ]

    :persistent_term.put({AgentSkills, :available_skills}, test_skills)

    # Clean up active skills
    AgentSkills.deactivate_all_skills()

    on_exit(fn ->
      :persistent_term.erase({AgentSkills, :available_skills})
      AgentSkills.deactivate_all_skills()
    end)

    :ok
  end

  describe "behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      Code.ensure_loaded?(Skills)
      assert function_exported?(Skills, :name, 0)
      assert function_exported?(Skills, :description, 0)
      assert function_exported?(Skills, :usage, 0)
      assert function_exported?(Skills, :execute, 2)
    end

    test "name returns '/skills'" do
      assert Skills.name() == "/skills"
    end

    test "description returns expected string" do
      assert Skills.description() == "List and manage agent skills"
    end

    test "usage returns expected string" do
      usage = Skills.usage()
      assert usage =~ "list"
      assert usage =~ "activate"
      assert usage =~ "deactivate"
    end
  end

  describe "execute/2 - list skills" do
    test "shows available skills with no args" do
      assert {:ok, text} = Skills.execute([], %{})
      assert text =~ "Available skills"
      assert text =~ "test-skill"
      assert text =~ "another-skill"
    end

    test "shows available skills with 'list'" do
      assert {:ok, text} = Skills.execute(["list"], %{})
      assert text =~ "Available skills"
      assert text =~ "test-skill"
    end
  end

  describe "execute/2 - active skills" do
    test "shows no active skills by default" do
      assert {:ok, text} = Skills.execute(["active"], %{})
      assert text =~ "No skills currently active"
    end

    test "shows active skills after activation" do
      Skills.execute(["activate", "test-skill"], %{})

      assert {:ok, text} = Skills.execute(["active"], %{})
      assert text =~ "Active skills"
      assert text =~ "test-skill"
    end
  end

  describe "execute/2 - activate" do
    test "activates a skill by name" do
      assert {:ok, text} = Skills.execute(["activate", "test-skill"], %{})
      assert text =~ "Activated skill"
      assert text =~ "test-skill"
    end

    test "handles multi-word skill name" do
      multi_skill = %{
        name: "multi word skill",
        description: "A skill with spaces",
        version: "1.0.0",
        author: "test",
        tags: [],
        content: "Content",
        source: "test"
      }

      existing = :persistent_term.get({AgentSkills, :available_skills}, [])
      :persistent_term.put({AgentSkills, :available_skills}, [multi_skill | existing])

      assert {:ok, text} = Skills.execute(["activate", "multi", "word", "skill"], %{})
      assert text =~ "Activated skill"
      assert text =~ "multi word skill"
    after
      :persistent_term.put({AgentSkills, :available_skills}, [])
    end

    test "reports already active skill" do
      Skills.execute(["activate", "test-skill"], %{})

      assert {:ok, text} = Skills.execute(["activate", "test-skill"], %{})
      assert text =~ "already active"
    end

    test "reports skill not found" do
      assert {:ok, text} = Skills.execute(["activate", "nonexistent"], %{})
      assert text =~ "not found"
    end

    test "returns error for missing name" do
      assert {:error, message} = Skills.execute(["activate"], %{})
      assert message =~ "activate <name>"
    end
  end

  describe "execute/2 - deactivate" do
    test "deactivates an active skill" do
      Skills.execute(["activate", "test-skill"], %{})

      assert {:ok, text} = Skills.execute(["deactivate", "test-skill"], %{})
      assert text =~ "Deactivated skill"
      assert text =~ "test-skill"
    end

    test "reports not active when deactivating inactive skill" do
      assert {:ok, text} = Skills.execute(["deactivate", "test-skill"], %{})
      assert text =~ "not currently active"
    end

    test "deactivates all skills with --all" do
      Skills.execute(["activate", "test-skill"], %{})
      Skills.execute(["activate", "another-skill"], %{})

      assert {:ok, text} = Skills.execute(["deactivate", "--all"], %{})
      assert text =~ "Deactivated"
    end

    test "returns error for missing name" do
      assert {:error, message} = Skills.execute(["deactivate"], %{})
      assert message =~ "deactivate <name>"
    end
  end

  describe "execute/2 - unknown subcommand" do
    test "returns error for unknown subcommand" do
      assert {:error, message} = Skills.execute(["unknown"], %{})
      assert message =~ "Unknown subcommand: unknown"
    end
  end
end
