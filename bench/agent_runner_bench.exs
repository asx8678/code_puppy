defmodule Bench.AgentRunnerBench do
  @moduledoc """
  Benchmarks for Agent.Runner execution paths.

  These benchmarks focus on the hot-path code in the agent execution loop:
  - Message building and prompt assembly
  - Tool schema extraction
  - Callback dispatch
  - Session management
  """

  alias Mana.Agent.Runner

  # Sample agent definitions for benchmarking
  @simple_agent_def %{
    name: "test_agent",
    description: "A simple test agent",
    available_tools: []
  }

  @agent_with_tools %{
    name: "tool_agent",
    description: "Agent with tools",
    available_tools: ["file_read", "file_edit", "shell_exec"]
  }

  @sample_history [
    %{role: "user", content: "Hello"},
    %{role: "assistant", content: "Hi there!"},
    %{role: "user", content: "How are you?"}
  ]

  @sample_system_prompt "You are a helpful assistant."

  @doc """
  Run all benchmarks.
  """
  def run do
    IO.puts("Running Agent Runner benchmarks...\n")

    Benchee.run(%{
      "agent state building (simple)" => fn ->
        # Simulate building agent state for simple agent
        build_agent_state(@simple_agent_def)
      end,
      "agent state building (with tools)" => fn ->
        # Simulate building agent state with tool definitions
        build_agent_state(@agent_with_tools)
      end,
      "message assembly (small history)" => fn ->
        assemble_messages(@sample_system_prompt, @sample_history, "Test message")
      end,
      "message assembly (large history)" => fn ->
        large_history = generate_large_history(50)
        assemble_messages(@sample_system_prompt, large_history, "Test message")
      end,
      "session ID generation" => fn ->
        generate_session_id()
      end,
      "callback dispatch (no handlers)" => fn ->
        # Benchmark callback dispatch when no handlers are registered
        Mana.Callbacks.dispatch(:agent_run_start, ["test", "gpt-4", "session-123"])
      end
    })
  end

  # Helper functions

  defp build_agent_state(agent_def) do
    %{
      agent_def: agent_def,
      model_name: "gpt-4",
      session_id: generate_session_id(),
      system_prompt: @sample_system_prompt,
      message_history: @sample_history
    }
  end

  defp assemble_messages(system_prompt, history, user_message) do
    [%{role: "system", content: system_prompt}] ++
      history ++
      [%{role: "user", content: user_message}]
  end

  defp generate_large_history(n) do
    Enum.flat_map(1..n, fn i ->
      [
        %{role: "user", content: "Message #{i} from user"},
        %{role: "assistant", content: "Response #{i} from assistant"}
      ]
    end)
  end

  defp generate_session_id do
    "session-" <> Base.encode16(:crypto.strong_rand_bytes(8), case: :lower)
  end
end

# Run benchmarks if this file is executed directly
if Code.ensure_loaded?(Benchee) do
  Bench.AgentRunnerBench.run()
else
  IO.puts("Benchee not available. Run: mix deps.get")
end
