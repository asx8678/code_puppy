defmodule CodePuppyControl.SessionStorageAsyncTest do
  @moduledoc """
  Tests for async autosave and debounce/dedup logic.

  Covers:
  - `save_session_async/3` — fire-and-forget background save
  - `AutosaveTracker` — `should_skip_autosave?/1` and `mark_autosave_complete/1`

  All tests use System.tmp_dir!/0 for isolation — never touches ~/.code_puppy/.
  """

  use ExUnit.Case, async: true

  alias CodePuppyControl.SessionStorage
  alias CodePuppyControl.SessionStorage.AutosaveTracker

  # ---------------------------------------------------------------------------
  # Setup: temp directory per test
  # ---------------------------------------------------------------------------

  setup do
    tmp =
      Path.join(
        System.tmp_dir!(),
        "session_storage_async_test_#{System.unique_integer([:positive])}"
      )

    File.mkdir_p!(tmp)
    on_exit(fn -> File.rm_rf!(tmp) end)
    {:ok, base_dir: tmp}
  end

  # ---------------------------------------------------------------------------
  # save_session_async/3
  # ---------------------------------------------------------------------------

  describe "save_session_async/3" do
    test "returns :ok synchronously", %{base_dir: dir} do
      history = [%{"role" => "user", "content" => "Hello"}]
      assert :ok = SessionStorage.save_session_async("sync-test", history, base_dir: dir)
    end

    test "persists session to disk in background", %{base_dir: dir} do
      history = [%{"role" => "user", "content" => "Async save"}]
      :ok = SessionStorage.save_session_async("bg-test", history, base_dir: dir)

      # Wait for the background Task to complete
      Process.sleep(100)

      assert SessionStorage.session_exists?("bg-test", base_dir: dir)

      assert {:ok, %{messages: loaded}} =
               SessionStorage.load_session("bg-test", base_dir: dir)

      assert loaded == history
    end

    test "logs warning on failure without raising", %{base_dir: _dir} do
      # Use an invalid base_dir that will cause save to fail.
      # The path must exist as a string but be unwritable.
      # Using "/" which will fail mkdir_p on most systems.
      # We just verify no exception propagates to the caller.
      history = [%{"role" => "user", "content" => "fail"}]

      # This should NOT raise — errors are caught in the Task
      assert :ok = SessionStorage.save_session_async("fail-test", history, base_dir: "/")

      # Give the Task time to run and fail
      Process.sleep(100)
    end

    test "history snapshot is isolated from later mutations", %{base_dir: dir} do
      # In Elixir, lists are immutable — this test demonstrates intent
      # rather than guarding against a real mutation risk.
      original_history = [%{"role" => "user", "content" => "original"}]

      :ok = SessionStorage.save_session_async("snapshot-test", original_history, base_dir: dir)

      # Wait for save to complete
      Process.sleep(100)

      assert {:ok, %{messages: loaded}} =
               SessionStorage.load_session("snapshot-test", base_dir: dir)

      assert loaded == original_history
    end

    test "captures base_dir before Task spawn — immune to env teardown race", %{
      base_dir: dir
    } do
      # (code_puppy-dku) save_session_async/3 must resolve base_dir
      # BEFORE spawning the Task.  If it re-read PUP_SESSION_DIR inside
      # the Task, test teardown that restores env vars before the Task
      # starts would redirect the write to the real user session path.
      history = [%{"role" => "user", "content" => "race-test"}]

      # Set up env vars so base_dir/0 resolves to our temp dir.
      prev_session_dir = System.get_env("PUP_SESSION_DIR")
      prev_test_root = System.get_env("PUP_TEST_SESSION_ROOT")

      # PUP_TEST_SESSION_ROOT needs to cover the parent of sessions
      sandbox_ex = Path.join(dir, "..") |> Path.expand()
      System.put_env("PUP_TEST_SESSION_ROOT", sandbox_ex)
      System.put_env("PUP_SESSION_DIR", dir)

      on_exit(fn ->
        if prev_session_dir,
          do: System.put_env("PUP_SESSION_DIR", prev_session_dir),
          else: System.delete_env("PUP_SESSION_DIR")

        if prev_test_root,
          do: System.put_env("PUP_TEST_SESSION_ROOT", prev_test_root),
          else: System.delete_env("PUP_TEST_SESSION_ROOT")
      end)

      # Call without explicit :base_dir — forces resolution via base_dir/0
      :ok = SessionStorage.save_session_async("race-capture-test", history, [])

      # Wait for the background Task to complete
      Process.sleep(150)

      # Verify the session landed in the expected dir (resolved from
      # PUP_SESSION_DIR at call time, not at Task execution time)
      assert SessionStorage.session_exists?("race-capture-test", base_dir: dir)
    end
  end

  # ---------------------------------------------------------------------------
  # AutosaveTracker
  # ---------------------------------------------------------------------------

  describe "AutosaveTracker.should_skip_autosave?/1" do
    setup do
      # Start an isolated tracker with a controllable clock
      time_ref = :counters.new(1, [:atomics])
      :counters.add(time_ref, 1, 0)

      time_fn = fn -> :counters.get(time_ref, 1) end

      name = :"autosave_tracker_#{System.unique_integer([:positive])}"
      {:ok, _pid} = AutosaveTracker.start_link(name: name, time_fn: time_fn)

      {:ok, tracker: name, time_ref: time_ref}
    end

    test "fresh state returns false (no prior save)", %{tracker: tracker} do
      history = [%{"role" => "user", "content" => "first"}]
      refute AutosaveTracker.should_skip_autosave?(history, tracker)
    end

    test "immediately after mark_autosave_complete returns true (debounce)", %{
      tracker: tracker
    } do
      history = [%{"role" => "user", "content" => "first"}]
      :ok = AutosaveTracker.mark_autosave_complete(history, tracker)

      # Within the debounce window — should skip
      assert AutosaveTracker.should_skip_autosave?(history, tracker)
    end

    test "within debounce window with different history still returns true", %{
      tracker: tracker,
      time_ref: time_ref
    } do
      history1 = [%{"role" => "user", "content" => "first"}]
      history2 = [%{"role" => "user", "content" => "second"}]

      :ok = AutosaveTracker.mark_autosave_complete(history1, tracker)

      # Advance time but stay within 2000ms debounce window
      :counters.add(time_ref, 1, 1000)

      # Even with different history, debounce wins
      assert AutosaveTracker.should_skip_autosave?(history2, tracker)
    end

    test "past debounce window with same history returns true (dedup)", %{
      tracker: tracker,
      time_ref: time_ref
    } do
      history = [%{"role" => "user", "content" => "same"}]
      :ok = AutosaveTracker.mark_autosave_complete(history, tracker)

      # Advance past the 2000ms debounce window
      :counters.add(time_ref, 1, 3000)

      # Same fingerprint → still skip
      assert AutosaveTracker.should_skip_autosave?(history, tracker)
    end

    test "past debounce window with different history returns false", %{
      tracker: tracker,
      time_ref: time_ref
    } do
      history1 = [%{"role" => "user", "content" => "first"}]
      :ok = AutosaveTracker.mark_autosave_complete(history1, tracker)

      # Advance past the 2000ms debounce window
      :counters.add(time_ref, 1, 3000)

      history2 = [%{"role" => "user", "content" => "second"}]

      # Different fingerprint → don't skip
      refute AutosaveTracker.should_skip_autosave?(history2, tracker)
    end

    test "empty history has a stable fingerprint", %{tracker: tracker} do
      # Two calls with empty history should agree
      refute AutosaveTracker.should_skip_autosave?([], tracker)

      :ok = AutosaveTracker.mark_autosave_complete([], tracker)

      # After marking complete, same empty history → skip
      assert AutosaveTracker.should_skip_autosave?([], tracker)
    end
  end

  describe "AutosaveTracker.mark_autosave_complete/1" do
    setup do
      time_fn = fn -> System.monotonic_time(:millisecond) end
      name = :"autosave_tracker_mark_#{System.unique_integer([:positive])}"
      {:ok, _pid} = AutosaveTracker.start_link(name: name, time_fn: time_fn)
      {:ok, tracker: name}
    end

    test "returns :ok", %{tracker: tracker} do
      history = [%{"role" => "user", "content" => "test"}]
      assert :ok = AutosaveTracker.mark_autosave_complete(history, tracker)
    end

    test "successive marks with different histories update fingerprint", %{
      tracker: tracker
    } do
      history1 = [%{"role" => "user", "content" => "first"}]
      history2 = [%{"role" => "assistant", "content" => "second"}]

      :ok = AutosaveTracker.mark_autosave_complete(history1, tracker)
      # Wait out debounce
      Process.sleep(2100)
      refute AutosaveTracker.should_skip_autosave?(history2, tracker)

      :ok = AutosaveTracker.mark_autosave_complete(history2, tracker)
      assert AutosaveTracker.should_skip_autosave?(history2, tracker)
    end
  end
end
