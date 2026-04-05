defmodule Mana.Plugins.AgentSkillsTest do
  use ExUnit.Case, async: false

  alias Mana.Plugins.AgentSkills

  setup do
    # Clear any existing state before each test
    AgentSkills.deactivate_all_skills()

    # Mock available skills for testing
    test_skills = [
      %{
        name: "elixir-dev",
        description: "Elixir development expertise",
        version: "1.0.0",
        author: "test",
        tags: ["elixir", "programming"],
        content: "# Elixir Development\n\nBest practices for Elixir...",
        source: "/test/elixir.md"
      },
      %{
        name: "rust-api",
        description: "Rust API design patterns",
        version: "1.0.0",
        author: "test",
        tags: ["rust", "api"],
        content: "# Rust API Design\n\nPatterns for building APIs...",
        source: "/test/rust.md"
      }
    ]

    # Store test skills in persistent_term
    :persistent_term.put({AgentSkills, :available_skills}, test_skills)

    on_exit(fn ->
      # Cleanup: clear active skills and reset available skills
      AgentSkills.deactivate_all_skills()
      :persistent_term.erase({AgentSkills, :available_skills})
    end)

    :ok
  end

  describe "behaviour compliance" do
    test "implements Mana.Plugin.Behaviour" do
      behaviours = AgentSkills.__info__(:attributes)[:behaviour] || []
      assert Mana.Plugin.Behaviour in behaviours
    end

    test "has required callbacks" do
      assert function_exported?(AgentSkills, :name, 0)
      assert function_exported?(AgentSkills, :init, 1)
      assert function_exported?(AgentSkills, :hooks, 0)
      assert function_exported?(AgentSkills, :terminate, 0)
    end
  end

  describe "name/0" do
    test "returns correct plugin name" do
      assert AgentSkills.name() == "agent_skills"
    end
  end

  describe "init/1" do
    test "initializes successfully" do
      # Note: init/1 calls load_skills which will load from disk
      # We verify it returns the expected shape
      assert {:ok, state} = AgentSkills.init(%{})
      assert state.loaded == true
    end
  end

  describe "hooks/0" do
    test "returns expected hooks" do
      hooks = AgentSkills.hooks()
      assert is_list(hooks)
      assert length(hooks) == 4

      hook_names = Enum.map(hooks, fn {name, _func} -> name end)
      assert :startup in hook_names
      assert :load_prompt in hook_names
      assert :custom_command in hook_names
      assert :agent_run_end in hook_names
    end
  end

  describe "on_startup/0" do
    test "returns :ok" do
      assert AgentSkills.on_startup() == :ok
    end
  end

  describe "on_load_prompt/0" do
    test "returns nil when no skills are active" do
      AgentSkills.deactivate_all_skills()
      assert AgentSkills.on_load_prompt() == nil
    end

    test "returns formatted prompt with active skills" do
      AgentSkills.activate_skill("elixir-dev")

      prompt = AgentSkills.on_load_prompt()
      assert is_binary(prompt)
      assert prompt =~ "Active Skills"
      assert prompt =~ "elixir-dev"
      assert prompt =~ "Elixir development expertise"
      assert prompt =~ "Best practices for Elixir"
    end

    test "includes multiple active skills" do
      AgentSkills.activate_skill("elixir-dev")
      AgentSkills.activate_skill("rust-api")

      prompt = AgentSkills.on_load_prompt()
      assert prompt =~ "elixir-dev"
      assert prompt =~ "rust-api"
    end
  end

  describe "on_custom_command/2" do
    test "handles skills list command" do
      result = AgentSkills.on_custom_command("skills", ["list"])
      assert is_binary(result)
      assert result =~ "Available skills:"
      assert result =~ "elixir-dev"
      assert result =~ "rust-api"
      assert result =~ "activate"
    end

    test "handles skills active command with no active skills" do
      AgentSkills.deactivate_all_skills()
      result = AgentSkills.on_custom_command("skills", ["active"])
      assert result =~ "No skills currently active"
    end

    test "handles skills active command with active skills" do
      AgentSkills.activate_skill("elixir-dev")
      result = AgentSkills.on_custom_command("skills", ["active"])
      assert result =~ "Active skills:"
      assert result =~ "elixir-dev"
    end

    test "handles skill activation" do
      result = AgentSkills.on_custom_command("skills", ["activate", "elixir-dev"])
      assert result =~ "Activated skill: elixir-dev"
      assert result =~ "Elixir development expertise"
    end

    test "handles skill activation with multi-word names" do
      result = AgentSkills.on_custom_command("skills", ["activate", "some", "complex", "name"])
      # Should gracefully handle (though skill won't exist in test setup)
      assert is_binary(result)
    end

    test "handles activating already active skill" do
      AgentSkills.activate_skill("elixir-dev")
      result = AgentSkills.on_custom_command("skills", ["activate", "elixir-dev"])
      assert result =~ "already active"
    end

    test "handles skill deactivation" do
      AgentSkills.activate_skill("elixir-dev")
      result = AgentSkills.on_custom_command("skills", ["deactivate", "elixir-dev"])
      assert result =~ "Deactivated skill: elixir-dev"
    end

    test "handles deactivating inactive skill" do
      AgentSkills.deactivate_all_skills()
      result = AgentSkills.on_custom_command("skills", ["deactivate", "elixir-dev"])
      assert result =~ "not currently active"
    end

    test "handles deactivate --all" do
      AgentSkills.activate_skill("elixir-dev")
      AgentSkills.activate_skill("rust-api")
      result = AgentSkills.on_custom_command("skills", ["deactivate", "--all"])
      assert result =~ "Deactivated 2 skill(s)"
    end

    test "returns help for unknown skills subcommand" do
      result = AgentSkills.on_custom_command("skills", ["unknown"])
      assert result =~ "Usage:"
      assert result =~ "list"
      assert result =~ "active"
      assert result =~ "activate"
    end

    test "returns nil for non-skills commands" do
      assert AgentSkills.on_custom_command("other", ["args"]) == nil
    end
  end

  describe "on_agent_run_end/7" do
    test "returns :ok" do
      result = AgentSkills.on_agent_run_end("agent", "model", "session", true, nil, "response", %{})
      assert result == :ok
    end
  end

  describe "list_skills/0" do
    test "returns available skills" do
      skills = AgentSkills.list_skills()
      assert length(skills) == 2
      assert Enum.any?(skills, fn s -> s.name == "elixir-dev" end)
      assert Enum.any?(skills, fn s -> s.name == "rust-api" end)
    end

    test "returns empty list when no skills loaded" do
      :persistent_term.put({AgentSkills, :available_skills}, [])
      assert AgentSkills.list_skills() == []
    end
  end

  describe "get_active_skills/1" do
    test "returns empty list when no skills active" do
      AgentSkills.deactivate_all_skills()
      assert AgentSkills.get_active_skills() == []
      assert AgentSkills.get_active_skills("session-123") == []
    end

    test "returns active skills for current session" do
      AgentSkills.activate_skill("elixir-dev")
      active = AgentSkills.get_active_skills()
      assert length(active) == 1
      assert hd(active).name == "elixir-dev"
    end
  end

  describe "activate_skill/1" do
    test "activates a skill by name" do
      result = AgentSkills.activate_skill("elixir-dev")
      assert result =~ "Activated skill: elixir-dev"

      active = AgentSkills.get_active_skills()
      assert length(active) == 1
      assert hd(active).name == "elixir-dev"
    end

    test "returns error for unknown skill" do
      result = AgentSkills.activate_skill("unknown-skill")
      assert result =~ "Skill not found: unknown-skill"
      assert result =~ "Run '/skills list'"
    end

    test "returns message for already active skill" do
      AgentSkills.activate_skill("elixir-dev")
      result = AgentSkills.activate_skill("elixir-dev")
      assert result =~ "already active"
    end

    test "can activate multiple skills" do
      AgentSkills.activate_skill("elixir-dev")
      AgentSkills.activate_skill("rust-api")

      active = AgentSkills.get_active_skills()
      assert length(active) == 2
      names = Enum.map(active, & &1.name)
      assert "elixir-dev" in names
      assert "rust-api" in names
    end
  end

  describe "deactivate_skill/1" do
    test "deactivates an active skill" do
      AgentSkills.activate_skill("elixir-dev")
      result = AgentSkills.deactivate_skill("elixir-dev")
      assert result =~ "Deactivated skill: elixir-dev"

      active = AgentSkills.get_active_skills()
      assert active == []
    end

    test "returns message for inactive skill" do
      result = AgentSkills.deactivate_skill("not-active")
      assert result =~ "not currently active"
    end

    test "deactivates only the specified skill" do
      AgentSkills.activate_skill("elixir-dev")
      AgentSkills.activate_skill("rust-api")

      AgentSkills.deactivate_skill("elixir-dev")

      active = AgentSkills.get_active_skills()
      assert length(active) == 1
      assert hd(active).name == "rust-api"
    end
  end

  describe "deactivate_all_skills/0" do
    test "deactivates all active skills" do
      AgentSkills.activate_skill("elixir-dev")
      AgentSkills.activate_skill("rust-api")

      result = AgentSkills.deactivate_all_skills()
      assert result =~ "Deactivated 2 skill(s)"

      assert AgentSkills.get_active_skills() == []
    end

    test "handles case with no active skills" do
      AgentSkills.deactivate_all_skills()
      result = AgentSkills.deactivate_all_skills()
      assert result =~ "Deactivated 0 skill(s)"
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      # Setup some state first
      :persistent_term.put({AgentSkills, :available_skills}, [])

      assert AgentSkills.terminate() == :ok

      # Available skills should be erased
      assert :persistent_term.get({AgentSkills, :available_skills}, :not_found) == :not_found
    end
  end
end
