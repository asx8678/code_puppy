defmodule Mana.Agent.BuilderTest do
  @moduledoc """
  Tests for Mana.Agent.Builder.
  """

  use ExUnit.Case, async: false

  alias Mana.Agent.Builder
  alias Mana.Agent.Server
  alias Mana.Callbacks.Registry
  alias Mana.Config.Store

  setup do
    start_supervised!(Store)
    start_supervised!(Registry)
    :ok
  end

  defmodule TestAgent do
    use Mana.Agent

    @impl true
    def name, do: "test_builder"

    @impl true
    def system_prompt, do: "You are a test agent for builder."

    @impl true
    def available_tools, do: ["tool1"]

    @impl true
    def tools_config, do: %{model: "gpt-4-turbo"}
  end

  defmodule MinimalAgent do
    use Mana.Agent

    @impl true
    def name, do: "minimal_builder"
  end

  describe "build/2 with module" do
    test "builds agent from module definition" do
      assert {:ok, pid} = Builder.build(TestAgent)
      assert Process.alive?(pid)
    end

    test "creates correct agent_def from module" do
      {:ok, pid} = Builder.build(TestAgent)
      state = Server.get_state(pid)

      assert state.agent_def.name == "test_builder"
      assert state.agent_def.display_name == "Test_builder"
      assert state.agent_def.description == "An agent named test_builder"
      assert state.agent_def.system_prompt == "You are a test agent for builder."
      assert state.agent_def.available_tools == ["tool1"]
      assert state.agent_def.tools_config == %{model: "gpt-4-turbo"}
    end

    test "uses model from tools_config when no override" do
      {:ok, pid} = Builder.build(TestAgent)
      state = Server.get_state(pid)

      assert state.model_name == "gpt-4-turbo"
    end

    test "uses global model when agent has no model in tools_config" do
      {:ok, pid} = Builder.build(MinimalAgent)
      state = Server.get_state(pid)

      assert state.model_name == Mana.Config.global_model_name()
    end

    test "opts model_name overrides agent's model" do
      {:ok, pid} = Builder.build(TestAgent, model_name: "overridden-model")
      state = Server.get_state(pid)

      assert state.model_name == "overridden-model"
    end

    test "accepts session_id option" do
      {:ok, pid} = Builder.build(TestAgent, session_id: "builder-session-123")
      state = Server.get_state(pid)

      assert state.session_id == "builder-session-123"
    end

    test "additional options are passed to server" do
      # Build with minimal agent, should use global model
      {:ok, pid} = Builder.build(MinimalAgent, model_name: "custom-model")
      state = Server.get_state(pid)

      assert state.model_name == "custom-model"
      assert state.agent_def.name == "minimal_builder"
    end
  end

  describe "build_from_map/2" do
    test "builds agent from map definition" do
      agent_def = %{
        name: "map_agent",
        system_prompt: "You are from a map.",
        available_tools: ["read_file"]
      }

      assert {:ok, pid} = Builder.build_from_map(agent_def)
      assert Process.alive?(pid)
    end

    test "preserves map agent_def in state" do
      agent_def = %{
        name: "map_agent",
        display_name: "Map Agent",
        description: "Created from map",
        system_prompt: "Map system prompt",
        available_tools: ["tool_a", "tool_b"],
        user_prompt: "Default user prompt"
      }

      {:ok, pid} = Builder.build_from_map(agent_def)
      state = Server.get_state(pid)

      assert state.agent_def == agent_def
    end

    test "resolves model from atom key in map" do
      agent_def = %{
        name: "map_agent",
        model: "map-model-atom"
      }

      {:ok, pid} = Builder.build_from_map(agent_def)
      state = Server.get_state(pid)

      assert state.model_name == "map-model-atom"
    end

    test "resolves model from string key in map" do
      agent_def = %{
        :name => "map_agent",
        "model" => "map-model-string"
      }

      {:ok, pid} = Builder.build_from_map(agent_def)
      state = Server.get_state(pid)

      assert state.model_name == "map-model-string"
    end

    test "opts model_name overrides map model" do
      agent_def = %{
        name: "map_agent",
        model: "map-model"
      }

      {:ok, pid} = Builder.build_from_map(agent_def, model_name: "override-model")
      state = Server.get_state(pid)

      assert state.model_name == "override-model"
    end

    test "falls back to global model when no model in map" do
      agent_def = %{
        name: "map_agent"
      }

      {:ok, pid} = Builder.build_from_map(agent_def)
      state = Server.get_state(pid)

      assert state.model_name == Mana.Config.global_model_name()
    end

    test "accepts session_id option" do
      agent_def = %{name: "map_agent"}

      {:ok, pid} = Builder.build_from_map(agent_def, session_id: "map-session")
      state = Server.get_state(pid)

      assert state.session_id == "map-session"
    end
  end

  describe "model resolution priority" do
    test "opts > tools_config > global for module build" do
      {:ok, pid1} = Builder.build(TestAgent)
      state1 = Server.get_state(pid1)
      # Uses tools_config model
      assert state1.model_name == "gpt-4-turbo"

      {:ok, pid2} = Builder.build(TestAgent, model_name: "opt-override")
      state2 = Server.get_state(pid2)
      # Uses opts override
      assert state2.model_name == "opt-override"
    end

    test "opts > atom key > string key > global for map build" do
      # Test string key takes precedence over global
      agent_def1 = %{"model" => "string-model"}
      {:ok, pid1} = Builder.build_from_map(agent_def1)
      state1 = Server.get_state(pid1)
      assert state1.model_name == "string-model"

      # Test atom key takes precedence over string key
      agent_def2 = %{:model => "atom-model", "model" => "string-model"}
      {:ok, pid2} = Builder.build_from_map(agent_def2)
      state2 = Server.get_state(pid2)
      assert state2.model_name == "atom-model"

      # Test opts takes precedence over atom key
      agent_def3 = %{model: "atom-model"}
      {:ok, pid3} = Builder.build_from_map(agent_def3, model_name: "opt-wins")
      state3 = Server.get_state(pid3)
      assert state3.model_name == "opt-wins"
    end
  end

  describe "server functionality" do
    test "built agent can add messages" do
      {:ok, pid} = Builder.build(MinimalAgent)

      assert :ok = Server.add_message(pid, %{role: "user", content: "Hello"})
      assert length(Server.get_history(pid)) == 1
    end

    test "built agent can compact history" do
      {:ok, pid} = Builder.build(MinimalAgent)

      for i <- 1..50 do
        :ok = Server.add_message(pid, %{role: "user", content: "Message #{i}"})
      end

      original_count = length(Server.get_history(pid))
      assert :ok = Server.compact_history(pid, max_tokens: 500)

      # After compaction, should have fewer or equal messages
      assert length(Server.get_history(pid)) <= original_count
    end

    test "built agent can change model" do
      {:ok, pid} = Builder.build(MinimalAgent)

      original_model = Server.get_state(pid).model_name
      assert :ok = Server.set_model(pid, "new-model")
      new_model = Server.get_state(pid).model_name

      assert new_model == "new-model"
      assert new_model != original_model
    end
  end

  describe "complex agent definitions" do
    test "handles agent with function system_prompt" do
      defmodule DynamicAgent do
        use Mana.Agent

        @impl true
        def name, do: "dynamic"

        @impl true
        def system_prompt do
          "Dynamic prompt at #{DateTime.utc_now().year}"
        end
      end

      {:ok, pid} = Builder.build(DynamicAgent)
      state = Server.get_state(pid)

      # The function should be called during building
      assert is_binary(state.agent_def.system_prompt)
      assert String.contains?(state.agent_def.system_prompt, "Dynamic prompt")
    end

    test "handles map with all fields" do
      agent_def = %{
        :name => "full_agent",
        :display_name => "Full Agent",
        :description => "A fully configured agent",
        :system_prompt => "Full system prompt",
        :available_tools => ["tool1", "tool2", "tool3"],
        :user_prompt => "Default user prompt",
        :tools_config => %{timeout: 30_000},
        :model => "full-model"
      }

      {:ok, pid} = Builder.build_from_map(agent_def)
      state = Server.get_state(pid)

      assert state.agent_def == agent_def
      assert state.model_name == "full-model"
    end
  end
end
