defmodule Mana.Plugins.LoggerTest do
  @moduledoc """
  Tests for Mana.Plugins.Logger plugin.
  """

  use ExUnit.Case, async: true

  alias Mana.Plugins.Logger

  describe "behaviour implementation" do
    test "implements Mana.Plugin.Behaviour" do
      Code.ensure_loaded(Logger)

      assert function_exported?(Logger, :name, 0)
      assert function_exported?(Logger, :init, 1)
      assert function_exported?(Logger, :hooks, 0)
      assert function_exported?(Logger, :terminate, 0)
    end

    test "name returns 'logger'" do
      assert Logger.name() == "logger"
    end
  end

  describe "init/1" do
    test "returns ok with default config" do
      assert {:ok, state} = Logger.init(%{})
      assert state.level == :info
      assert state.log_tool_calls == true
      assert state.log_stream_events == false
      assert state.run_count == 0
      assert state.tool_count == 0
    end

    test "accepts custom config" do
      config = %{level: :debug, log_tool_calls: false, log_stream_events: true}

      assert {:ok, state} = Logger.init(config)
      assert state.level == :debug
      assert state.log_tool_calls == false
      assert state.log_stream_events == true
    end

    test "returns a map state" do
      assert {:ok, state} = Logger.init(%{})
      assert is_map(state)
    end
  end

  describe "hooks/0" do
    test "returns a list of {phase, function} tuples" do
      hooks = Logger.hooks()

      assert is_list(hooks)
      assert length(hooks) > 0

      for {phase, func} <- hooks do
        assert is_atom(phase)
        assert is_function(func)
      end
    end

    test "registers expected hook phases" do
      hooks = Logger.hooks()
      phases = Enum.map(hooks, fn {phase, _} -> phase end) |> Enum.sort()

      assert :startup in phases
      assert :agent_run_start in phases
      assert :agent_run_end in phases
      assert :pre_tool_call in phases
      assert :post_tool_call in phases
      assert :stream_event in phases
      assert :shutdown in phases
    end
  end

  describe "hook callbacks" do
    test "on_startup returns :ok" do
      assert Logger.on_startup() == :ok
    end

    test "on_agent_run_start returns :ok" do
      assert Logger.on_agent_run_start("test-agent", "gpt-4", "session-1") == :ok
    end

    test "on_agent_run_start handles nil session_id" do
      assert Logger.on_agent_run_start("test-agent", "gpt-4", nil) == :ok
    end

    test "on_agent_run_end returns :ok on success" do
      assert Logger.on_agent_run_end("test-agent", "gpt-4", "session-1", true, nil, "response", %{}) ==
               :ok
    end

    test "on_agent_run_end returns :ok on failure" do
      assert Logger.on_agent_run_end("test-agent", "gpt-4", nil, false, "timeout", nil, %{}) == :ok
    end

    test "on_pre_tool_call returns :ok" do
      assert Logger.on_pre_tool_call("file_read", %{"path" => "/test.txt"}, %{}) == :ok
    end

    test "on_post_tool_call returns :ok" do
      assert Logger.on_post_tool_call("file_read", %{}, "contents", 150, %{}) == :ok
    end

    test "on_stream_event returns :ok" do
      assert Logger.on_stream_event("text_delta", %{"text" => "hello"}, "session-1") == :ok
    end

    test "on_shutdown returns :ok" do
      assert Logger.on_shutdown() == :ok
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      assert Logger.terminate() == :ok
    end
  end
end
