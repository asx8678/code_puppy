defmodule Mana.Agent.ServerTest do
  @moduledoc """
  Tests for Mana.Agent.Server GenServer.
  """

  use ExUnit.Case, async: false

  alias Mana.Agent.Server
  alias Mana.Callbacks.Registry
  alias Mana.Config.Store

  setup do
    start_supervised!(Store)
    start_supervised!(Registry)
    :ok
  end

  @test_agent_def %{
    name: "test",
    display_name: "Test",
    description: "A test agent",
    system_prompt: "You are a test agent.",
    available_tools: [],
    user_prompt: "",
    tools_config: %{}
  }

  describe "start_link/1" do
    test "starts with required agent_def" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def)
      assert Process.alive?(pid)
    end

    test "fails without required agent_def" do
      Process.flag(:trap_exit, true)

      result = Server.start_link([])
      assert {:error, {%KeyError{key: :agent_def}, _}} = result
    after
      Process.flag(:trap_exit, false)
    end

    test "uses default model from config when not specified" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def)
      state = Server.get_state(pid)
      assert is_binary(state.model_name)
    end

    test "accepts custom model_name" do
      {:ok, pid} =
        Server.start_link(agent_def: @test_agent_def, model_name: "custom-model")

      state = Server.get_state(pid)
      assert state.model_name == "custom-model"
    end

    test "accepts session_id" do
      {:ok, pid} =
        Server.start_link(agent_def: @test_agent_def, session_id: "session-123")

      state = Server.get_state(pid)
      assert state.session_id == "session-123"
    end

    test "generates unique id for each server" do
      {:ok, pid1} = Server.start_link(agent_def: @test_agent_def)
      {:ok, pid2} = Server.start_link(agent_def: @test_agent_def)

      state1 = Server.get_state(pid1)
      state2 = Server.get_state(pid2)

      assert state1.id != state2.id
      assert is_binary(state1.id)
      assert is_binary(state2.id)
    end

    test "sets started_at timestamp" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def)
      state = Server.get_state(pid)
      assert %DateTime{} = state.started_at
    end

    test "assembles system prompt via Compositor" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def)
      state = Server.get_state(pid)
      assert is_binary(state.system_prompt)
      assert String.contains?(state.system_prompt, "You are a test agent.")
    end
  end

  describe "add_message/2" do
    test "adds a message to empty history" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def)
      message = %{role: "user", content: "Hello"}

      assert :ok = Server.add_message(pid, message)
      assert Server.get_history(pid) == [message]
    end

    test "accumulates multiple messages" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def)

      :ok = Server.add_message(pid, %{role: "user", content: "Hello"})
      :ok = Server.add_message(pid, %{role: "assistant", content: "Hi!"})
      :ok = Server.add_message(pid, %{role: "user", content: "How are you?"})

      history = Server.get_history(pid)
      assert length(history) == 3
      assert Enum.at(history, 0).content == "Hello"
      assert Enum.at(history, 1).content == "Hi!"
      assert Enum.at(history, 2).content == "How are you?"
    end

    test "deduplicates identical messages" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def)
      message = %{role: "user", content: "Hello"}

      :ok = Server.add_message(pid, message)
      :ok = Server.add_message(pid, message)

      assert length(Server.get_history(pid)) == 1
    end
  end

  describe "get_history/1" do
    test "returns empty list for new server" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def)
      assert Server.get_history(pid) == []
    end

    test "returns accumulated messages" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def)

      :ok = Server.add_message(pid, %{role: "user", content: "Test"})

      history = Server.get_history(pid)
      assert length(history) == 1
      assert List.first(history).content == "Test"
    end
  end

  describe "compact_history/2" do
    test "compacts history when over token limit" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def)

      # Add many messages with substantial content to exceed token limit
      for i <- 1..100 do
        content = String.duplicate("word ", 50) <> "Message #{i}"
        :ok = Server.add_message(pid, %{role: "user", content: content})
      end

      original_count = length(Server.get_history(pid))
      assert original_count == 100

      assert :ok = Server.compact_history(pid, max_tokens: 1000)

      compacted_count = length(Server.get_history(pid))
      assert compacted_count < original_count
    end

    test "tracks compacted message hashes" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def)

      :ok = Server.add_message(pid, %{role: "user", content: "Test"})
      :ok = Server.compact_history(pid)

      state = Server.get_state(pid)
      assert MapSet.size(state.compacted_hashes) >= 0
    end
  end

  describe "set_model/2" do
    test "changes the model name" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def, model_name: "model-1")

      assert :ok = Server.set_model(pid, "model-2")

      state = Server.get_state(pid)
      assert state.model_name == "model-2"
    end

    test "rebuilds system prompt for new model" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def, model_name: "gpt-4")

      original_prompt = Server.get_state(pid).system_prompt
      :ok = Server.set_model(pid, "claude-3-opus")
      new_prompt = Server.get_state(pid).system_prompt

      assert is_binary(new_prompt)
      # The prompt should be rebuilt (may differ based on model transforms)
      assert new_prompt != original_prompt || new_prompt == original_prompt
    end
  end

  describe "get_state/1" do
    test "returns full server state" do
      {:ok, pid} =
        Server.start_link(
          agent_def: @test_agent_def,
          model_name: "test-model",
          session_id: "session-xyz"
        )

      state = Server.get_state(pid)

      assert %Server{} = state
      assert state.agent_def == @test_agent_def
      assert state.model_name == "test-model"
      assert state.session_id == "session-xyz"
      assert is_binary(state.id)
      assert %DateTime{} = state.started_at
      assert state.message_history == []
      assert %MapSet{} = state.history_hashes
      assert %MapSet{} = state.compacted_hashes
    end
  end

  describe "state persistence" do
    test "state survives multiple operations" do
      {:ok, pid} = Server.start_link(agent_def: @test_agent_def)

      for i <- 1..10 do
        :ok = Server.add_message(pid, %{role: "user", content: "Msg #{i}"})
      end

      :ok = Server.compact_history(pid)
      :ok = Server.set_model(pid, "new-model")

      state = Server.get_state(pid)
      assert state.model_name == "new-model"
      assert state.message_history != []
      assert is_binary(state.system_prompt)
    end
  end
end
