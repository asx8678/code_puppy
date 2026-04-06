defmodule Mana.CallbacksTest do
  @moduledoc """
  Tests for Mana.Callbacks module.
  """

  use ExUnit.Case, async: false

  alias Mana.Callbacks
  alias Mana.Callbacks.Registry

  setup do
    # Start a fresh registry for each test
    start_supervised!({Registry, max_backlog_size: 10, backlog_ttl: 1_000})

    :ok
  end

  describe "generated on_<phase> functions" do
    test "on_startup/0 dispatches to callbacks" do
      test_pid = self()
      callback = fn -> send(test_pid, :startup_called) end

      Callbacks.register(:startup, callback)
      Callbacks.on_startup()

      assert_receive :startup_called
    end

    test "on_shutdown/0 dispatches to callbacks" do
      test_pid = self()
      callback = fn -> send(test_pid, :shutdown_called) end

      Callbacks.register(:shutdown, callback)
      Callbacks.on_shutdown()

      assert_receive :shutdown_called
    end

    test "on_agent_run_start/3 dispatches with correct args" do
      test_pid = self()

      callback = fn agent, model, session ->
        send(test_pid, {:agent_run_start, agent, model, session})
      end

      Callbacks.register(:agent_run_start, callback)
      Callbacks.on_agent_run_start("my_agent", "gpt-4", "session_123")

      assert_receive {:agent_run_start, "my_agent", "gpt-4", "session_123"}
    end

    test "on_agent_run_end/7 dispatches with correct args" do
      test_pid = self()

      callback = fn agent, model, session, success, error, response, meta ->
        send(test_pid, {:agent_run_end, agent, model, session, success, error, response, meta})
      end

      Callbacks.register(:agent_run_end, callback)
      Callbacks.on_agent_run_end("agent", "model", "session", true, nil, "response", %{key: "value"})

      assert_receive {:agent_run_end, "agent", "model", "session", true, nil, "response", %{key: "value"}}
    end

    test "on_pre_tool_call/3 dispatches with correct args" do
      test_pid = self()

      callback = fn tool, args, ctx ->
        send(test_pid, {:pre_tool_call, tool, args, ctx})
      end

      Callbacks.register(:pre_tool_call, callback)
      Callbacks.on_pre_tool_call("read_file", %{path: "/test"}, %{session: "abc"})

      assert_receive {:pre_tool_call, "read_file", %{path: "/test"}, %{session: "abc"}}
    end

    test "on_post_tool_call/5 dispatches with correct args" do
      test_pid = self()

      callback = fn tool, args, result, duration, ctx ->
        send(test_pid, {:post_tool_call, tool, args, result, duration, ctx})
      end

      Callbacks.register(:post_tool_call, callback)
      Callbacks.on_post_tool_call("read_file", %{}, "content", 100, %{})

      assert_receive {:post_tool_call, "read_file", %{}, "content", 100, %{}}
    end

    test "on_stream_event/3 dispatches with correct args" do
      test_pid = self()

      callback = fn event_type, data, session ->
        send(test_pid, {:stream_event, event_type, data, session})
      end

      Callbacks.register(:stream_event, callback)
      Callbacks.on_stream_event("chunk", "data", "session_1")

      assert_receive {:stream_event, "chunk", "data", "session_1"}
    end

    test "on_file_permission/6 dispatches with correct args" do
      test_pid = self()

      callback = fn ctx, path, op, preview, group, data ->
        send(test_pid, {:file_permission, ctx, path, op, preview, group, data})
      end

      Callbacks.register(:file_permission, callback)
      Callbacks.on_file_permission(%{}, "/file", :read, "preview", "group1", %{})

      assert_receive {:file_permission, %{}, "/file", :read, "preview", "group1", %{}}
    end

    test "generated functions buffer to backlog when no callbacks" do
      # No callbacks registered
      {:ok, []} = Callbacks.on_startup()

      # Should be in backlog
      {:ok, events} = Callbacks.drain_backlog(:startup)
      assert length(events) == 1
    end

    test "generated functions support file operation hooks" do
      test_pid = self()

      callback = fn args, kwargs ->
        send(test_pid, {:create_file, args, kwargs})
      end

      Callbacks.register(:create_file, callback)
      Callbacks.on_create_file("path", %{content: "test"})

      assert_receive {:create_file, "path", %{content: "test"}}
    end

    test "generated functions support load_prompt hook" do
      test_pid = self()

      callback = fn ->
        send(test_pid, :load_prompt)
        "custom prompt"
      end

      Callbacks.register(:load_prompt, callback)
      {:ok, [result]} = Callbacks.on_load_prompt()

      assert_receive :load_prompt
      assert result == "custom prompt"
    end
  end

  describe "register/2 delegation" do
    test "delegates to Registry.register/2" do
      callback = fn -> :ok end
      assert :ok = Callbacks.register(:startup, callback)

      # Verify it was registered
      callbacks = Registry.get_callbacks(:startup)
      assert length(callbacks) == 1
    end
  end

  describe "unregister/2 delegation" do
    test "delegates to Registry.unregister/2" do
      callback = fn -> :ok end
      Callbacks.register(:startup, callback)
      assert :ok = Callbacks.unregister(:startup, callback)

      callbacks = Registry.get_callbacks(:startup)
      assert callbacks == []
    end
  end

  describe "clear/1 delegation" do
    test "delegates to Registry.clear/1" do
      callback = fn -> :ok end
      Callbacks.register(:startup, callback)
      assert :ok = Callbacks.clear(:startup)

      callbacks = Registry.get_callbacks(:startup)
      assert callbacks == []
    end
  end

  describe "dispatch/2 delegation" do
    test "delegates to Registry.dispatch/2" do
      callback = fn -> :ok end
      Callbacks.register(:startup, callback)

      {:ok, results} = Callbacks.dispatch(:startup, [])
      assert results == [:ok]
    end
  end

  describe "drain_backlog/1 delegation" do
    test "delegates to Registry.drain_backlog/1" do
      Callbacks.dispatch(:startup, [])

      {:ok, events} = Callbacks.drain_backlog(:startup)
      assert length(events) == 1
    end
  end

  describe "get_stats/0 delegation" do
    test "delegates to Registry.get_stats/0" do
      callback = fn -> :ok end
      Callbacks.register(:startup, callback)

      stats = Callbacks.get_stats()
      assert stats.callbacks_registered == 1
    end
  end
end
