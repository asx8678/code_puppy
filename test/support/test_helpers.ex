defmodule Mana.TestHelpers do
  @moduledoc """
  Shared test helpers for the Mana test suite.
  Provides async-safe assertion utilities to replace Process.sleep.
  """

  import ExUnit.Assertions

  @doc """
  Polls a function until it returns a truthy value or the timeout expires.

  ## Options
    * `:timeout` - max wait in ms (default: 1000)
    * `:interval` - polling interval in ms (default: 25)

  ## Examples

      assert_eventually(fn -> Executor.list_processes() == [] end)
      assert_eventually(fn -> GenServer.whereis(MyServer) != nil end, timeout: 5000)
  """
  def assert_eventually(fun, opts \\ []) do
    timeout = Keyword.get(opts, :timeout, 1000)
    interval = Keyword.get(opts, :interval, 25)
    deadline = System.monotonic_time(:millisecond) + timeout
    do_poll(fun, interval, deadline)
  end

  defp do_poll(fun, interval, deadline) do
    case fun.() do
      x when x in [false, nil] ->
        if System.monotonic_time(:millisecond) >= deadline do
          flunk("assert_eventually condition not met within timeout")
        else
          Process.sleep(interval)
          do_poll(fun, interval, deadline)
        end

      _ ->
        true
    end
  end

  @doc """
  Waits until a process is no longer alive.

  ## Options
    * `:timeout` - max wait in ms (default: 1000)

  ## Examples

      wait_for_exit(pid)
      wait_for_exit(pid, timeout: 5000)
  """
  def wait_for_exit(pid, opts \\ []) do
    timeout = Keyword.get(opts, :timeout, 1000)
    ref = Process.monitor(pid)

    receive do
      {:DOWN, ^ref, _, _, _} -> :ok
    after
      timeout ->
        Process.demonitor(ref, [:flush])
        flunk("Process #{inspect(pid)} did not exit within #{timeout}ms")
    end
  end
end
