defmodule CodePuppyControl.REPL.DispatchRollbackBD254Test do
  @moduledoc """
  Regression tests for bd-254: broadened rollback for the full
  post-append critical section in dispatch_after_append/4.

  The original fix only caught :exit signals from the inner try block.
  The broadened fix moves catch clauses to the outer try, so
  raises/throws/exits from ensure_renderer/1, Loop.generate_run_id/0,
  start_agent_loop/4, and the success path ALL restore messages_before.

  Extracted from renderer_rollback_test.exs (bd-254 critic feedback).
  """
  use ExUnit.Case, async: false

  alias CodePuppyControl.Agent.State
  alias CodePuppyControl.REPL.Loop
  alias CodePuppyControl.Tools.AgentCatalogue

  # ---------------------------------------------------------------------------
  # Mock LLM (nested module to avoid BEAM global name collisions with
  # RollbackTestMockLLM and CrashMidCallMockLLM in sibling test files.)
  # ---------------------------------------------------------------------------

  defmodule BD254MockLLM do
    @moduledoc """
    Mock LLM module for bd-254 dispatch rollback regression tests.

    Implements `CodePuppyControl.Agent.LLM` behaviour with controllable
    responses and error injection via an Elixir Agent process.
    """
    @behaviour CodePuppyControl.Agent.LLM

    def ensure_started do
      case Elixir.Agent.start_link(fn -> %{} end, name: __MODULE__) do
        {:ok, pid} -> {:ok, pid}
        {:error, {:already_started, pid}} -> {:ok, pid}
      end
    end

    def set_response(response) when is_map(response) do
      ensure_started()
      Elixir.Agent.update(__MODULE__, &Map.put(&1, :response, response))
    end

    def set_error(reason) do
      ensure_started()
      Elixir.Agent.update(__MODULE__, &Map.put(&1, :error, reason))
    end

    def reset do
      case Process.whereis(__MODULE__) do
        nil -> :ok
        _ -> Elixir.Agent.update(__MODULE__, fn _ -> %{} end)
      end
    end

    def stop do
      try do
        Elixir.Agent.stop(__MODULE__)
      catch
        :exit, _ -> :ok
      end
    end

    @impl true
    def stream_chat(_messages, _tools, opts, callback_fn) do
      ensure_started()

      Elixir.Agent.update(__MODULE__, &Map.put(&1, :last_opts, opts))

      state = Elixir.Agent.get(__MODULE__, & &1)

      cond do
        state[:error] ->
          {:error, state[:error]}

        state[:response] ->
          resp = state[:response]

          if resp[:text] do
            callback_fn.({:text, resp.text})
          end

          if resp[:tool_calls] do
            for tc <- resp[:tool_calls] do
              callback_fn.({:tool_call, tc.name, tc.arguments, tc.id})
            end
          end

          callback_fn.({:done, :complete})
          {:ok, resp}

        true ->
          {:error, :no_mock_configured}
      end
    end
  end

  # ---------------------------------------------------------------------------
  # Shared setup
  # ---------------------------------------------------------------------------

  defp setup_mock_llm_and_session(_context) do
    session_id = :crypto.strong_rand_bytes(4) |> Base.encode16(case: :lower)

    prev_llm = Application.get_env(:code_puppy_control, :repl_llm_module)
    Application.put_env(:code_puppy_control, :repl_llm_module, BD254MockLLM)
    BD254MockLLM.reset()

    try do
      AgentCatalogue.discover_agent_modules()
    catch
      _, _ -> :ok
    end

    on_exit(fn ->
      # Restore ALL env vars that tests in this file may mutate.
      # Using on_exit ensures cleanup even if the test crashes.
      if prev_llm do
        Application.put_env(:code_puppy_control, :repl_llm_module, prev_llm)
      else
        Application.delete_env(:code_puppy_control, :repl_llm_module)
      end

      Application.delete_env(:code_puppy_control, :test_dispatch_success_fault)
      Application.delete_env(:code_puppy_control, :test_ensure_renderer_raise)
      Application.delete_env(:code_puppy_control, :test_start_agent_loop_raise)
      Application.delete_env(:code_puppy_control, :test_ensure_renderer_error)

      BD254MockLLM.stop()

      try do
        State.clear_messages(session_id, "code_puppy")
      catch
        _, _ -> :ok
      end

      # Safe renderer cleanup
      case Registry.lookup(CodePuppyControl.REPL.RendererRegistry, session_id) do
        [] -> :ok

        [{pid, _}] ->
          if Process.alive?(pid) do
            try do
              GenServer.stop(pid, :normal, 1_000)
            catch
              :exit, _ -> :ok
            end
          end
      end
    end)

    state = %Loop{
      session_id: session_id,
      agent: "code_puppy",
      model: "claude-sonnet-4-20250514",
      running: true
    }

    {:ok, state: state, session_id: session_id}
  end

  # ===========================================================================
  # Success-path fault injection: raise / throw / exit
  # ===========================================================================

  describe "dispatch_after_append — rollback on success-path faults (bd-254)" do
    setup :setup_mock_llm_and_session

    test "raise after run_until_done ok rolls back user message", %{
      state: state,
      session_id: session_id
    } do
      State.append_message(session_id, "code_puppy", %{
        "role" => "user",
        "parts" => [%{"type" => "text", "text" => "earlier message"}]
      })

      assert [%{"role" => "user"}] = State.get_messages(session_id, "code_puppy")

      # Seed a successful mock response so run_until_done returns :ok,
      # ensuring inject_success_fault() is actually reached (bd-254).
      BD254MockLLM.set_response(%{text: "mock reply", tool_calls: []})

      Application.put_env(
        :code_puppy_control,
        :test_dispatch_success_fault,
        "injected failure for bd-254 test"
      )

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Loop.handle_input("This should be rolled back", state)
        end)

      assert output =~ "⚠" or output =~ "\e[31m" or output =~ "Unexpected error"

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 1
      assert hd(messages)["parts"] |> hd() |> Map.get("text") == "earlier message"
    end

    test "raise with RuntimeError rolls back user message", %{
      state: state,
      session_id: session_id
    } do
      # Seed a successful mock response so run_until_done returns :ok,
      # ensuring inject_success_fault() is actually reached (bd-254).
      BD254MockLLM.set_response(%{text: "mock reply", tool_calls: []})

      Application.put_env(
        :code_puppy_control,
        :test_dispatch_success_fault,
        RuntimeError.exception("boom from bd-254 test")
      )

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Loop.handle_input("This should be rolled back", state)
        end)

      assert output =~ "⚠" or output =~ "\e[31m" or output =~ "Unexpected error"

      messages = State.get_messages(session_id, "code_puppy")
      assert messages == []
    end

    test "REPL survives and subsequent call works after post-append raise", %{
      state: state,
      session_id: session_id
    } do
      # Seed a successful mock response so run_until_done returns :ok,
      # ensuring inject_success_fault() is actually reached (bd-254).
      BD254MockLLM.set_response(%{text: "mock reply", tool_calls: []})

      Application.put_env(
        :code_puppy_control,
        :test_dispatch_success_fault,
        "first boom"
      )

      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, ^state} = Loop.handle_input("crash me", state)
      end)

      Application.delete_env(:code_puppy_control, :test_dispatch_success_fault)

      BD254MockLLM.set_response(%{text: "recovered reply", tool_calls: []})

      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, ^state} = Loop.handle_input("try again", state)
      end)

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2

      assert [
               %{"role" => "user", "parts" => [%{"type" => "text", "text" => "try again"}]},
               %{"role" => "assistant", "parts" => [%{"type" => "text", "text" => "recovered reply"}]}
             ] = messages
    end

    test "raise preserves earlier messages (rollback is surgical)", %{
      state: state,
      session_id: session_id
    } do
      State.append_message(session_id, "code_puppy", %{
        "role" => "user",
        "parts" => [%{"type" => "text", "text" => "msg one"}]
      })

      State.append_message(session_id, "code_puppy", %{
        "role" => "assistant",
        "parts" => [%{"type" => "text", "text" => "msg two"}]
      })

      assert length(State.get_messages(session_id, "code_puppy")) == 2

      # Seed a successful mock response so run_until_done returns :ok,
      # ensuring inject_success_fault() is actually reached (bd-254).
      BD254MockLLM.set_response(%{text: "mock reply", tool_calls: []})

      Application.put_env(
        :code_puppy_control,
        :test_dispatch_success_fault,
        "surgical test"
      )

      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, ^state} = Loop.handle_input("should be rolled back", state)
      end)

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2
      assert Enum.at(messages, 0)["parts"] |> hd() |> Map.get("text") == "msg one"
      assert Enum.at(messages, 1)["parts"] |> hd() |> Map.get("text") == "msg two"
    end

    test "throw in success path rolls back user message", %{
      state: state,
      session_id: session_id
    } do
      State.append_message(session_id, "code_puppy", %{
        "role" => "user",
        "parts" => [%{"type" => "text", "text" => "earlier message"}]
      })

      assert [%{"role" => "user"}] = State.get_messages(session_id, "code_puppy")

      # Seed a successful mock response so run_until_done returns :ok,
      # ensuring inject_success_fault() is actually reached (bd-254).
      BD254MockLLM.set_response(%{text: "mock reply", tool_calls: []})

      Application.put_env(
        :code_puppy_control,
        :test_dispatch_success_fault,
        {:throw, :bd254_throw_test}
      )

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Loop.handle_input("This should be rolled back", state)
        end)

      assert output =~ "⚠" or output =~ "\e[31m" or output =~ "throw"

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 1
      assert hd(messages)["parts"] |> hd() |> Map.get("text") == "earlier message"
    end

    test "throw preserves earlier messages (rollback is surgical)", %{
      state: state,
      session_id: session_id
    } do
      State.append_message(session_id, "code_puppy", %{
        "role" => "user",
        "parts" => [%{"type" => "text", "text" => "msg one"}]
      })

      State.append_message(session_id, "code_puppy", %{
        "role" => "assistant",
        "parts" => [%{"type" => "text", "text" => "msg two"}]
      })

      assert length(State.get_messages(session_id, "code_puppy")) == 2

      # Seed a successful mock response so run_until_done returns :ok,
      # ensuring inject_success_fault() is actually reached (bd-254).
      BD254MockLLM.set_response(%{text: "mock reply", tool_calls: []})

      Application.put_env(
        :code_puppy_control,
        :test_dispatch_success_fault,
        {:throw, :bd254_surgical_throw}
      )

      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, ^state} = Loop.handle_input("should be rolled back", state)
      end)

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2
      assert Enum.at(messages, 0)["parts"] |> hd() |> Map.get("text") == "msg one"
      assert Enum.at(messages, 1)["parts"] |> hd() |> Map.get("text") == "msg two"
    end

    test "exit in success path rolls back user message", %{
      state: state,
      session_id: session_id
    } do
      State.append_message(session_id, "code_puppy", %{
        "role" => "user",
        "parts" => [%{"type" => "text", "text" => "earlier message"}]
      })

      assert [%{"role" => "user"}] = State.get_messages(session_id, "code_puppy")

      # Seed a successful mock response so run_until_done returns :ok,
      # ensuring inject_success_fault() is actually reached (bd-254).
      BD254MockLLM.set_response(%{text: "mock reply", tool_calls: []})

      Application.put_env(
        :code_puppy_control,
        :test_dispatch_success_fault,
        {:exit, :bd254_exit_test}
      )

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Loop.handle_input("This should be rolled back", state)
        end)

      assert output =~ "⚠" or output =~ "\e[31m" or output =~ "crashed"

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 1
      assert hd(messages)["parts"] |> hd() |> Map.get("text") == "earlier message"
    end

    test "exit preserves earlier messages (rollback is surgical)", %{
      state: state,
      session_id: session_id
    } do
      State.append_message(session_id, "code_puppy", %{
        "role" => "user",
        "parts" => [%{"type" => "text", "text" => "msg one"}]
      })

      State.append_message(session_id, "code_puppy", %{
        "role" => "assistant",
        "parts" => [%{"type" => "text", "text" => "msg two"}]
      })

      assert length(State.get_messages(session_id, "code_puppy")) == 2

      # Seed a successful mock response so run_until_done returns :ok,
      # ensuring inject_success_fault() is actually reached (bd-254).
      BD254MockLLM.set_response(%{text: "mock reply", tool_calls: []})

      Application.put_env(
        :code_puppy_control,
        :test_dispatch_success_fault,
        {:exit, :bd254_surgical_exit}
      )

      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, ^state} = Loop.handle_input("should be rolled back", state)
      end)

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2
      assert Enum.at(messages, 0)["parts"] |> hd() |> Map.get("text") == "msg one"
      assert Enum.at(messages, 1)["parts"] |> hd() |> Map.get("text") == "msg two"
    end

    test "REPL survives and subsequent call works after post-append throw", %{
      state: state,
      session_id: session_id
    } do
      # Seed a successful mock response so run_until_done returns :ok,
      # ensuring inject_success_fault() is actually reached (bd-254).
      BD254MockLLM.set_response(%{text: "mock reply", tool_calls: []})

      Application.put_env(
        :code_puppy_control,
        :test_dispatch_success_fault,
        {:throw, :first_throw}
      )

      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, ^state} = Loop.handle_input("crash me", state)
      end)

      Application.delete_env(:code_puppy_control, :test_dispatch_success_fault)

      BD254MockLLM.set_response(%{text: "recovered reply", tool_calls: []})

      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, ^state} = Loop.handle_input("try again", state)
      end)

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2

      assert [
               %{"role" => "user", "parts" => [%{"type" => "text", "text" => "try again"}]},
               %{"role" => "assistant", "parts" => [%{"type" => "text", "text" => "recovered reply"}]}
             ] = messages
    end
  end

  # ===========================================================================
  # with-clause fault injection: raise from ensure_renderer / start_agent_loop
  # ===========================================================================

  describe "dispatch_after_append — rollback on with-clause raises (bd-254)" do
    setup :setup_mock_llm_and_session

    test "raise from ensure_renderer rolls back user message", %{
      state: state,
      session_id: session_id
    } do
      State.append_message(session_id, "code_puppy", %{
        "role" => "user",
        "parts" => [%{"type" => "text", "text" => "earlier message"}]
      })

      assert [%{"role" => "user"}] = State.get_messages(session_id, "code_puppy")

      Application.put_env(
        :code_puppy_control,
        :test_ensure_renderer_raise,
        "renderer boom for bd-254"
      )

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Loop.handle_input("This should be rolled back", state)
        end)

      assert output =~ "⚠" or output =~ "\e[31m" or output =~ "Unexpected error"

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 1
      assert hd(messages)["parts"] |> hd() |> Map.get("text") == "earlier message"
    end

    test "raise from ensure_renderer preserves earlier messages (surgical rollback)", %{
      state: state,
      session_id: session_id
    } do
      State.append_message(session_id, "code_puppy", %{
        "role" => "user",
        "parts" => [%{"type" => "text", "text" => "msg one"}]
      })

      State.append_message(session_id, "code_puppy", %{
        "role" => "assistant",
        "parts" => [%{"type" => "text", "text" => "msg two"}]
      })

      assert length(State.get_messages(session_id, "code_puppy")) == 2

      Application.put_env(
        :code_puppy_control,
        :test_ensure_renderer_raise,
        "renderer boom surgical"
      )

      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, ^state} = Loop.handle_input("should be rolled back", state)
      end)

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2
      assert Enum.at(messages, 0)["parts"] |> hd() |> Map.get("text") == "msg one"
      assert Enum.at(messages, 1)["parts"] |> hd() |> Map.get("text") == "msg two"
    end

    test "raise from start_agent_loop rolls back user message", %{
      state: state,
      session_id: session_id
    } do
      State.append_message(session_id, "code_puppy", %{
        "role" => "user",
        "parts" => [%{"type" => "text", "text" => "earlier message"}]
      })

      assert [%{"role" => "user"}] = State.get_messages(session_id, "code_puppy")

      Application.put_env(
        :code_puppy_control,
        :test_start_agent_loop_raise,
        "agent loop boom for bd-254"
      )

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Loop.handle_input("This should be rolled back", state)
        end)

      assert output =~ "⚠" or output =~ "\e[31m" or output =~ "Unexpected error"

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 1
      assert hd(messages)["parts"] |> hd() |> Map.get("text") == "earlier message"
    end

    test "raise from start_agent_loop preserves earlier messages (surgical rollback)", %{
      state: state,
      session_id: session_id
    } do
      State.append_message(session_id, "code_puppy", %{
        "role" => "user",
        "parts" => [%{"type" => "text", "text" => "msg one"}]
      })

      State.append_message(session_id, "code_puppy", %{
        "role" => "assistant",
        "parts" => [%{"type" => "text", "text" => "msg two"}]
      })

      assert length(State.get_messages(session_id, "code_puppy")) == 2

      Application.put_env(
        :code_puppy_control,
        :test_start_agent_loop_raise,
        "agent loop boom surgical"
      )

      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, ^state} = Loop.handle_input("should be rolled back", state)
      end)

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2
      assert Enum.at(messages, 0)["parts"] |> hd() |> Map.get("text") == "msg one"
      assert Enum.at(messages, 1)["parts"] |> hd() |> Map.get("text") == "msg two"
    end

    test "REPL survives and subsequent call works after ensure_renderer raise", %{
      state: state,
      session_id: session_id
    } do
      Application.put_env(
        :code_puppy_control,
        :test_ensure_renderer_raise,
        "first renderer boom"
      )

      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, ^state} = Loop.handle_input("crash me", state)
      end)

      Application.delete_env(:code_puppy_control, :test_ensure_renderer_raise)

      BD254MockLLM.set_response(%{text: "recovered reply", tool_calls: []})

      ExUnit.CaptureIO.capture_io(fn ->
        assert {:continue, ^state} = Loop.handle_input("try again", state)
      end)

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2

      assert [
               %{"role" => "user", "parts" => [%{"type" => "text", "text" => "try again"}]},
               %{"role" => "assistant", "parts" => [%{"type" => "text", "text" => "recovered reply"}]}
             ] = messages
    end
  end
end
