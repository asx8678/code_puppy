defmodule Mana.Callbacks.RegistryTest do
  @moduledoc """
  Tests for Mana.Callbacks.Registry module.
  """

  use ExUnit.Case, async: false

  alias Mana.Callbacks.Registry

  setup do
    # Start a fresh registry for each test
    start_supervised!({Registry, max_backlog_size: 10, backlog_ttl: 1_000})

    :ok
  end

  describe "start_link/1" do
    test "starts the GenServer successfully" do
      assert Process.whereis(Registry) != nil
    end

    test "returns correct child_spec" do
      spec = Registry.child_spec([])
      assert spec.id == Registry
      assert spec.type == :worker
      assert spec.restart == :permanent
    end
  end

  describe "register/2" do
    test "registers a callback for a valid phase" do
      callback = fn -> :ok end
      assert :ok = Registry.register(:startup, callback)
    end

    test "returns error for invalid phase" do
      callback = fn -> :ok end
      assert {:error, :invalid_phase} = Registry.register(:invalid_phase, callback)
    end

    test "returns error for duplicate registration" do
      callback = fn -> :ok end
      assert :ok = Registry.register(:startup, callback)
      assert {:error, :already_registered} = Registry.register(:startup, callback)
    end

    test "returns error for invalid arguments" do
      assert {:error, :invalid_arguments} = Registry.register("not_an_atom", fn -> :ok end)
      assert {:error, :invalid_arguments} = Registry.register(:startup, "not_a_function")
    end

    test "allows multiple callbacks for same phase" do
      callback1 = fn -> :ok end
      callback2 = fn -> :also_ok end
      assert :ok = Registry.register(:startup, callback1)
      assert :ok = Registry.register(:startup, callback2)

      callbacks = Registry.get_callbacks(:startup)
      assert length(callbacks) == 2
    end
  end

  describe "unregister/2" do
    test "unregisters a previously registered callback" do
      callback = fn -> :ok end
      Registry.register(:startup, callback)
      assert :ok = Registry.unregister(:startup, callback)

      callbacks = Registry.get_callbacks(:startup)
      assert callbacks == []
    end

    test "returns ok even if callback was not registered" do
      callback = fn -> :ok end
      assert :ok = Registry.unregister(:startup, callback)
    end

    test "only unregisters the specified callback" do
      callback1 = fn -> :ok end
      callback2 = fn -> :also_ok end
      Registry.register(:startup, callback1)
      Registry.register(:startup, callback2)

      Registry.unregister(:startup, callback1)

      callbacks = Registry.get_callbacks(:startup)
      assert length(callbacks) == 1
    end
  end

  describe "clear/1" do
    test "clears all callbacks for a phase" do
      callback1 = fn -> :ok end
      callback2 = fn -> :also_ok end
      Registry.register(:startup, callback1)
      Registry.register(:startup, callback2)

      assert :ok = Registry.clear(:startup)

      callbacks = Registry.get_callbacks(:startup)
      assert callbacks == []
    end

    test "returns ok for phase with no callbacks" do
      assert :ok = Registry.clear(:startup)
    end
  end

  describe "dispatch/2" do
    test "dispatches to registered callbacks" do
      test_pid = self()

      callback = fn agent, model, session ->
        send(test_pid, {:callback_called, agent, model, session})
        :ok
      end

      Registry.register(:agent_run_start, callback)

      {:ok, results} = Registry.dispatch(:agent_run_start, ["agent1", "model1", "session1"])

      assert results == [:ok]
      assert_receive {:callback_called, "agent1", "model1", "session1"}
    end

    test "dispatches to multiple callbacks" do
      test_pid = self()

      callback1 = fn ->
        send(test_pid, :callback1)
        :ok1
      end

      callback2 = fn ->
        send(test_pid, :callback2)
        :ok2
      end

      Registry.register(:startup, callback1)
      Registry.register(:startup, callback2)

      {:ok, results} = Registry.dispatch(:startup, [])

      assert results == [:ok1, :ok2]
      assert_receive :callback1
      assert_receive :callback2
    end

    test "buffers events to backlog when no callbacks registered" do
      {:ok, []} = Registry.dispatch(:startup, [])

      # Event should be in backlog
      {:ok, backlog} = Registry.drain_backlog(:startup)
      assert length(backlog) == 1
      [event] = backlog
      assert event.args == []
      assert is_integer(event.timestamp)
    end

    test "returns error for invalid phase" do
      assert {:error, :invalid_phase} = Registry.dispatch(:invalid_phase, [])
    end

    test "handles callback errors gracefully" do
      callback = fn -> raise "oops" end
      Registry.register(:startup, callback)

      # Should not crash, but return error in results
      {:ok, results} = Registry.dispatch(:startup, [])
      assert [{:error, {:error, %RuntimeError{message: "oops"}}}] = results
    end

    test "updates dispatch stats" do
      callback = fn -> :ok end
      Registry.register(:startup, callback)

      Registry.dispatch(:startup, [])

      stats = Registry.get_stats()
      assert stats.dispatches == 1
    end

    test "executes callbacks in caller process" do
      caller_pid = self()

      callback = fn ->
        send(caller_pid, {:callback_process, self()})
        :ok
      end

      Registry.register(:startup, callback)
      Registry.dispatch(:startup, [])

      assert_receive {:callback_process, pid}
      assert pid == caller_pid
    end
  end

  describe "drain_backlog/1" do
    test "returns and clears backlog for a phase" do
      # Buffer some events
      Registry.dispatch(:startup, ["arg1"])
      Registry.dispatch(:startup, ["arg2"])

      # Drain
      {:ok, events} = Registry.drain_backlog(:startup)
      assert length(events) == 2

      # Backlog should be empty now
      {:ok, events} = Registry.drain_backlog(:startup)
      assert events == []
    end

    test "returns empty list for phase with no backlog" do
      {:ok, events} = Registry.drain_backlog(:startup)
      assert events == []
    end
  end

  describe "get_stats/0" do
    test "returns initial stats" do
      stats = Registry.get_stats()
      assert stats.dispatches == 0
      assert stats.errors == 0
      assert stats.callbacks_registered == 0
      assert stats.backlog_size == 0
    end

    test "stats reflect registered callbacks" do
      Registry.register(:startup, fn -> :ok end)
      Registry.register(:shutdown, fn -> :ok end)

      stats = Registry.get_stats()
      assert stats.callbacks_registered == 2
    end

    test "stats reflect backlog size" do
      Registry.dispatch(:startup, [])
      Registry.dispatch(:agent_run_start, ["a", "b", "c"])

      stats = Registry.get_stats()
      assert stats.backlog_size == 2
    end
  end

  describe "get_callbacks/1" do
    test "returns empty list for phase with no callbacks" do
      assert Registry.get_callbacks(:startup) == []
    end

    test "returns registered callbacks" do
      callback = fn -> :ok end
      Registry.register(:startup, callback)

      callbacks = Registry.get_callbacks(:startup)
      assert length(callbacks) == 1
    end
  end

  describe "backlog management" do
    test "enforces max backlog size (FIFO eviction)" do
      # Register 11 events with max_backlog_size of 10
      for i <- 1..11 do
        Registry.dispatch(:startup, [i])
      end

      {:ok, events} = Registry.drain_backlog(:startup)
      assert length(events) == 10

      # First event should have been evicted (FIFO)
      [first | _] = events
      assert first.args == [2]
    end

    test "backlog entries have timestamps" do
      before = System.monotonic_time(:millisecond)
      Registry.dispatch(:startup, ["test"])
      after_time = System.monotonic_time(:millisecond)

      {:ok, [event]} = Registry.drain_backlog(:startup)
      assert event.timestamp >= before
      assert event.timestamp <= after_time
    end
  end
end
