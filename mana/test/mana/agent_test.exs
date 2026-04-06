defmodule Mana.AgentTest do
  @moduledoc """
  Tests for Mana.Agent behaviour.
  """

  use ExUnit.Case, async: true

  defmodule TestAgent do
    use Mana.Agent

    @impl true
    def name, do: "test_agent"

    @impl true
    def system_prompt, do: "You are a test agent."

    @impl true
    def available_tools, do: ["tool1", "tool2"]
  end

  defmodule MinimalAgent do
    use Mana.Agent

    @impl true
    def name, do: "minimal"
  end

  describe "using macro with defaults" do
    test "provides default display_name" do
      assert TestAgent.display_name() == "Test_agent"
    end

    test "provides default description" do
      assert TestAgent.description() == "An agent named test_agent"
    end

    test "allows overriding system_prompt" do
      assert TestAgent.system_prompt() == "You are a test agent."
    end

    test "provides default empty user_prompt" do
      assert TestAgent.user_prompt() == ""
    end

    test "provides default empty tools_config" do
      assert TestAgent.tools_config() == %{}
    end

    test "allows overriding available_tools" do
      assert TestAgent.available_tools() == ["tool1", "tool2"]
    end
  end

  describe "minimal agent with only required callbacks" do
    test "name is required" do
      assert MinimalAgent.name() == "minimal"
    end

    test "display_name defaults to capitalized name" do
      assert MinimalAgent.display_name() == "Minimal"
    end

    test "description has default" do
      assert MinimalAgent.description() == "An agent named minimal"
    end

    test "system_prompt defaults to empty string" do
      assert MinimalAgent.system_prompt() == ""
    end

    test "available_tools defaults to empty list" do
      assert MinimalAgent.available_tools() == []
    end
  end

  describe "behaviour implementation" do
    test "TestAgent implements Mana.Agent behaviour" do
      # This would fail compilation if not properly implementing the behaviour
      assert function_exported?(TestAgent, :name, 0)
      assert function_exported?(TestAgent, :display_name, 0)
      assert function_exported?(TestAgent, :description, 0)
      assert function_exported?(TestAgent, :system_prompt, 0)
      assert function_exported?(TestAgent, :available_tools, 0)
      assert function_exported?(TestAgent, :user_prompt, 0)
      assert function_exported?(TestAgent, :tools_config, 0)
    end
  end
end
