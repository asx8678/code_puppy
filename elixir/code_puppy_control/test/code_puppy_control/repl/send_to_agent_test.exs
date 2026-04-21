defmodule CodePuppyControl.REPL.SendToAgentTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.Agent.State
  alias CodePuppyControl.REPL.{History, Loop}
  alias CodePuppyControl.Tools.AgentCatalogue

  # ---------------------------------------------------------------------------
  # Mock LLM for send_to_agent/2 tests
  # ---------------------------------------------------------------------------

  defmodule REPLTestMockLLM do
    @moduledoc """
    Mock LLM module for REPL Loop send_to_agent/2 tests.

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

    def last_opts do
      case Process.whereis(__MODULE__) do
        nil -> nil
        _ -> Elixir.Agent.get(__MODULE__, & &1)[:last_opts]
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

  # Start a fresh History GenServer for each test.
  # async: false because we share the registered name and disk file.
  setup do
    case Process.whereis(History) do
      nil -> :ok
      pid -> GenServer.stop(pid, :shutdown, 5000)
    end

    # Wipe the history file so tests start clean
    File.rm(History.history_path())

    {:ok, _pid} = History.start_link()

    on_exit(fn ->
      try do
        case Process.whereis(History) do
          nil -> :ok
          pid -> GenServer.stop(pid, :shutdown, 5000)
        end
      catch
        :exit, _ -> :ok
      end

      File.rm(History.history_path())
    end)

    :ok
  end

  # ===========================================================================
  # send_to_agent/2 tests (bd-250 Phase 3)
  # ===========================================================================
  #
  # send_to_agent/2 is private, so we test it through the public
  # handle_input/2 which routes non-command, non-passthrough input to it.

  describe "send_to_agent/2 via handle_input/2 — happy path" do
    setup do
      # Fresh session ID per test to avoid cross-test pollution
      session_id = :crypto.strong_rand_bytes(4) |> Base.encode16(case: :lower)

      # Swap in mock LLM via app env
      prev_llm = Application.get_env(:code_puppy_control, :repl_llm_module)
      Application.put_env(:code_puppy_control, :repl_llm_module, REPLTestMockLLM)
      REPLTestMockLLM.reset()

      # Ensure the catalogue is running and has discovered agents.
      # In the test environment, the app supervision tree starts the catalogue,
      # but the "code_puppy" agent may not be registered if the catalogue was
      # cleared by a prior test's on_exit. Re-discover to be safe.
      try do
        AgentCatalogue.discover_agent_modules()
      catch
        _, _ -> :ok
      end

      on_exit(fn ->
        # Restore previous LLM module config
        if prev_llm do
          Application.put_env(:code_puppy_control, :repl_llm_module, prev_llm)
        else
          Application.delete_env(:code_puppy_control, :repl_llm_module)
        end

        REPLTestMockLLM.stop()

        # Clean up Agent.State for this session
        try do
          State.clear_messages(session_id, "code_puppy")
        catch
          _, _ -> :ok
        end

        # Clean up any renderer process started for this session
        renderer_name =
          String.to_atom("Elixir.CodePuppyControl.REPL.Renderer.#{session_id}")

        case Process.whereis(renderer_name) do
          nil -> :ok
          pid -> GenServer.stop(pid, :normal, 1_000)
        end
      end)

      # Use "code_puppy" (underscore) to match the catalogue registration.
      # The agent's name/0 callback returns :code_puppy, which becomes
      # "code_puppy" in the ETS table.
      state = %Loop{
        session_id: session_id,
        agent: "code_puppy",
        model: "claude-sonnet-4-20250514",
        running: true
      }

      {:ok, state: state, session_id: session_id}
    end

    test "dispatches prompt, streams response, persists both messages", %{
      state: state,
      session_id: session_id
    } do
      REPLTestMockLLM.set_response(%{text: "Hello, human!", tool_calls: []})

      _output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^state} = Loop.handle_input("Hi there", state)
        end)

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2

      assert [
               %{"role" => "user", "parts" => [%{"type" => "text", "text" => "Hi there"}]},
               %{"role" => "assistant", "parts" => [%{"type" => "text", "text" => "Hello, human!"}]}
             ] =
               messages
    end

    test "multi-turn conversation remembers first prompt", %{
      state: state,
      session_id: session_id
    } do
      REPLTestMockLLM.set_response(%{text: "First reply", tool_calls: []})

      ExUnit.CaptureIO.capture_io(fn ->
        Loop.handle_input("First prompt", state)
      end)

      REPLTestMockLLM.set_response(%{text: "Second reply", tool_calls: []})

      ExUnit.CaptureIO.capture_io(fn ->
        Loop.handle_input("Second prompt", state)
      end)

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 4

      roles = Enum.map(messages, &Map.get(&1, "role"))
      assert roles == ["user", "assistant", "user", "assistant"]

      # Extract text from parts-based message format
      contents =
        Enum.map(messages, fn msg ->
          msg |> Map.get("parts") |> hd() |> Map.get("text")
        end)

      assert contents == ["First prompt", "First reply", "Second prompt", "Second reply"]
    end
  end

  describe "send_to_agent/2 via handle_input/2 — error paths" do
    setup do
      session_id = :crypto.strong_rand_bytes(4) |> Base.encode16(case: :lower)

      prev_llm = Application.get_env(:code_puppy_control, :repl_llm_module)
      Application.put_env(:code_puppy_control, :repl_llm_module, REPLTestMockLLM)
      REPLTestMockLLM.reset()

      try do
        AgentCatalogue.discover_agent_modules()
      catch
        _, _ -> :ok
      end

      on_exit(fn ->
        if prev_llm do
          Application.put_env(:code_puppy_control, :repl_llm_module, prev_llm)
        else
          Application.delete_env(:code_puppy_control, :repl_llm_module)
        end

        REPLTestMockLLM.stop()

        try do
          State.clear_messages(session_id, "code_puppy")
        catch
          _, _ -> :ok
        end

        renderer_name =
          String.to_atom("Elixir.CodePuppyControl.REPL.Renderer.#{session_id}")

        case Process.whereis(renderer_name) do
          nil -> :ok
          pid -> GenServer.stop(pid, :normal, 1_000)
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

    test "LLM error: prints error, rolls back user message, REPL continues", %{
      state: state,
      session_id: session_id
    } do
      REPLTestMockLLM.set_error(:rate_limited)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          # REPL must survive the error — handle_input returns :continue
          assert {:continue, ^state} = Loop.handle_input("Hello", state)
        end)

      # Error marker should appear in output
      assert output =~ "⚠" or output =~ "\e[31m"

      # Agent.State should be empty — the user message was rolled back
      messages = State.get_messages(session_id, "code_puppy")
      assert messages == []
    end

    test "unknown agent: prints error, does not touch Agent.State, REPL continues", %{
      session_id: session_id
    } do
      bad_state = %Loop{
        session_id: session_id,
        agent: "this-agent-does-not-exist",
        model: "claude-sonnet-4-20250514",
        running: true
      }

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, ^bad_state} = Loop.handle_input("Hi", bad_state)
        end)

      assert output =~ "Unknown agent" or output =~ "⚠"

      # No messages should have been appended for this agent
      messages = State.get_messages(session_id, "this-agent-does-not-exist")
      assert messages == []
    end
  end

  describe "send_to_agent/2 via handle_input/2 — model override" do
    setup do
      session_id = :crypto.strong_rand_bytes(4) |> Base.encode16(case: :lower)

      prev_llm = Application.get_env(:code_puppy_control, :repl_llm_module)
      Application.put_env(:code_puppy_control, :repl_llm_module, REPLTestMockLLM)
      REPLTestMockLLM.reset()

      try do
        AgentCatalogue.discover_agent_modules()
      catch
        _, _ -> :ok
      end

      on_exit(fn ->
        if prev_llm do
          Application.put_env(:code_puppy_control, :repl_llm_module, prev_llm)
        else
          Application.delete_env(:code_puppy_control, :repl_llm_module)
        end

        REPLTestMockLLM.stop()

        try do
          State.clear_messages(session_id, "code_puppy")
        catch
          _, _ -> :ok
        end

        renderer_name =
          String.to_atom("Elixir.CodePuppyControl.REPL.Renderer.#{session_id}")

        case Process.whereis(renderer_name) do
          nil -> :ok
          pid -> GenServer.stop(pid, :normal, 1_000)
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

    test "model override from REPL state flows to llm_module.stream_chat opts", %{
      state: state
    } do
      state = %{state | model: "gpt-4o-2024-08-06"}
      REPLTestMockLLM.set_response(%{text: "ok", tool_calls: []})

      ExUnit.CaptureIO.capture_io(fn ->
        Loop.handle_input("test", state)
      end)

      # The mock records the opts it received; the :model key should match
      # the model override from the REPL state
      assert Keyword.get(REPLTestMockLLM.last_opts(), :model) == "gpt-4o-2024-08-06"
    end
  end
end
