defmodule AssertEventually do
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
