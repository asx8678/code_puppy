defmodule AssertEventually do
  @moduledoc """
  Provides assertion helpers that wait for conditions to become true.

  This module is primarily used in tests to handle asynchronous operations
  where conditions may not be immediately satisfied.

  ## Examples

      # Wait up to 1000ms (default) for condition to be true
      AssertEventually.assert_eventually(fn -> SomeModule.ready?() end)

      # Custom timeout and interval
      AssertEventually.assert_eventually(fn -> check_status() end, 5000, 100)
  """

  def assert_eventually(func, timeout \\ 1000, interval \\ 50) do
    deadline = System.monotonic_time(:millisecond) + timeout
    do_assert(func, deadline, interval)
  end

  defp do_assert(func, deadline, interval) do
    case func.() do
      true ->
        :ok

      false ->
        if System.monotonic_time(:millisecond) > deadline do
          raise "Condition not met within timeout"
        else
          Process.sleep(interval)
          do_assert(func, deadline, interval)
        end
    end
  end
end
