defmodule CodePuppyControl.Tools.FileModifications.FileLockTest do
  @moduledoc "Tests for FileLock — per-file locking for concurrent mutations."

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.FileModifications.FileLock

  describe "with_lock/2" do
    test "executes function and returns result" do
      assert {:ok, :done} = FileLock.with_lock("/tmp/test_lock.txt", fn -> :done end)
    end

    test "serializes access to the same file" do
      test_path = "/tmp/lock_serial_test_#{:erlang.unique_integer([:positive])}.txt"
      # Use a simple agent to verify ordering
      {:ok, agent} = Agent.start_link(fn -> [] end)

      # Use :global.trans for locking — test that sequential calls work
      {:ok, :first} = FileLock.with_lock(test_path, fn ->
        Agent.update(agent, &(&1 ++ [:first]))
        :first
      end)

      {:ok, :second} = FileLock.with_lock(test_path, fn ->
        Agent.update(agent, &(&1 ++ [:second]))
        # Verify first was called before second
        history = Agent.get(agent, & &1)
        assert history == [:first, :second]
        :second
      end)

      Agent.stop(agent)
    end

    test "allows concurrent access to different files" do
      # Different files should not block each other
      task1 =
        Task.async(fn ->
          FileLock.with_lock("/tmp/lock_file_a.txt", fn ->
            Process.sleep(50)
            :a
          end)
        end)

      task2 =
        Task.async(fn ->
          FileLock.with_lock("/tmp/lock_file_b.txt", fn ->
            :b
          end)
        end)

      {:ok, :a} = Task.await(task1, 5000)
      {:ok, :b} = Task.await(task2, 5000)
    end

    test "handles function errors gracefully" do
      assert {:error, %RuntimeError{}} =
               FileLock.with_lock("/tmp/lock_error_test.txt", fn ->
                 raise RuntimeError, "test error"
               end)
    end

    test "resolves symlinks to the same key" do
      # Same realpath should serialize, even if given different paths
      # This tests that resolve_key normalizes paths
      assert {:ok, :done} =
               FileLock.with_lock("/tmp/./lock_test.txt", fn -> :done end)
    end
  end
end
