defmodule Mana.Prompt.CompositorTest do
  use ExUnit.Case, async: false

  alias Mana.Callbacks.Registry
  alias Mana.Prompt.Compositor

  setup do
    # Start a fresh registry for each test
    start_supervised!({Registry, max_backlog_size: 10, backlog_ttl: 1_000})

    :ok
  end

  describe "assemble/3" do
    test "returns prompt with all layers for basic agent" do
      agent_def = %{system_prompt: "You are a helpful assistant."}

      prompt = Compositor.assemble(agent_def, "generic-model")

      assert prompt =~ "You are a helpful assistant."
      assert prompt =~ "## Environment"
      assert prompt =~ "## Identity"
      assert prompt =~ "Mana"
    end

    test "handles agent with function system_prompt" do
      agent_def = %{system_prompt: fn -> "Dynamic prompt content." end}

      prompt = Compositor.assemble(agent_def, "generic-model")

      assert prompt =~ "Dynamic prompt content."
    end

    test "handles agent without system_prompt" do
      agent_def = %{}

      prompt = Compositor.assemble(agent_def, "generic-model")

      assert prompt =~ "## Environment"
      assert prompt =~ "## Identity"
    end

    test "includes working directory in metadata when specified" do
      agent_def = %{}

      prompt = Compositor.assemble(agent_def, "generic-model", cwd: "/custom/path")

      assert prompt =~ "Working directory: /custom/path"
    end

    test "layers are joined with double newlines" do
      agent_def = %{system_prompt: "First layer."}

      prompt = Compositor.assemble(agent_def, "generic-model")

      # Check that layers are separated by double newlines
      parts = String.split(prompt, "\n\n")
      assert length(parts) >= 3
    end

    test "claude models receive unwrapped prompt" do
      agent_def = %{system_prompt: "Test content."}

      prompt = Compositor.assemble(agent_def, "claude-3-opus")

      # Claude wrapper doesn't add XML tags
      refute prompt =~ "<antigravity>"
      assert prompt =~ "Test content."
      assert prompt =~ "## Environment"
    end

    test "antigravity models receive wrapped prompt" do
      agent_def = %{system_prompt: "Test content."}

      prompt = Compositor.assemble(agent_def, "antigravity-model")

      assert prompt =~ "<antigravity>"
      assert prompt =~ "</antigravity>"
      assert prompt =~ "Test content."
    end

    test "handles empty prompt layers gracefully" do
      # When AGENTS.md doesn't exist and no system_prompt, should still work
      agent_def = %{}

      prompt = Compositor.assemble(agent_def, "generic-model", cwd: "/nonexistent")

      # Should still contain environment and identity
      assert prompt =~ "## Environment"
      assert prompt =~ "## Identity"
    end

    test "load_prompt callbacks add content when registered" do
      # Register a callback that returns extra content
      callback = fn -> "Extra callback content." end
      :ok = Mana.Callbacks.register(:load_prompt, callback)

      agent_def = %{system_prompt: "Base prompt."}

      try do
        prompt = Compositor.assemble(agent_def, "generic-model")
        assert prompt =~ "Base prompt."
        assert prompt =~ "Extra callback content."
      after
        Mana.Callbacks.unregister(:load_prompt, callback)
      end
    end

    test "load_prompt callbacks that return nil are filtered out" do
      # Register a callback that returns nil
      callback = fn -> nil end
      :ok = Mana.Callbacks.register(:load_prompt, callback)

      agent_def = %{system_prompt: "Base prompt."}

      try do
        prompt = Compositor.assemble(agent_def, "generic-model")
        # Should not crash and should still have base content
        assert prompt =~ "Base prompt."
      after
        Mana.Callbacks.unregister(:load_prompt, callback)
      end
    end
  end
end
