defmodule CodePuppyControl.CLI.OneShotMockLLM do
  @moduledoc false
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

    case state[:error] do
      nil ->
        resp = state[:response] || %{text: "no mock", tool_calls: []}
        callback_fn.({:text, resp[:text]})
        callback_fn.({:done, :complete})
        {:ok, resp}

      reason ->
        {:error, reason}
    end
  end
end

defmodule CodePuppyControl.CLI.OneShotTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.Agent.State
  alias CodePuppyControl.CLI.OneShotMockLLM
  alias CodePuppyControl.REPL.Loop
  alias CodePuppyControl.Tools.AgentCatalogue

  defp setup_mock_llm(_context) do
    session_id = :crypto.strong_rand_bytes(4) |> Base.encode16(case: :lower)

    prev_llm = Application.get_env(:code_puppy_control, :repl_llm_module)
    Application.put_env(:code_puppy_control, :repl_llm_module, OneShotMockLLM)
    OneShotMockLLM.reset()

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

      OneShotMockLLM.stop()

      Enum.each(["code_puppy", "code-puppy", "qa_kitten"], fn agent_key ->
        try do
          State.clear_messages(session_id, agent_key)
        catch
          _, _ -> :ok
        end
      end)

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

    {:ok, session_id: session_id}
  end

  describe "run_one_shot/1 happy path" do
    setup :setup_mock_llm

    test "dispatches prompt and persists messages", %{session_id: session_id} do
      OneShotMockLLM.set_response(%{text: "Sure thing!", tool_calls: []})

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert :ok = Loop.run_one_shot(%{prompt: "Do a thing", session_id: session_id})
        end)

      assert output =~ "Sure thing!"

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2

      assert [
               %{"role" => "user", "parts" => [%{"type" => "text", "text" => "Do a thing"}]},
               %{"role" => "assistant"}
             ] = messages
    end

    test "honors :agent opt", %{session_id: session_id} do
      OneShotMockLLM.set_response(%{text: "QA reply", tool_calls: []})

      ExUnit.CaptureIO.capture_io(fn ->
        assert :ok =
                 Loop.run_one_shot(%{
                   prompt: "Review this",
                   agent: "qa-kitten",
                   session_id: session_id
                 })
      end)

      messages = State.get_messages(session_id, "qa_kitten")
      assert length(messages) == 2
      assert [%{"role" => "user"}, %{"role" => "assistant"}] = messages
    end

    test "honors :model opt", %{session_id: session_id} do
      OneShotMockLLM.set_response(%{text: "ok", tool_calls: []})

      ExUnit.CaptureIO.capture_io(fn ->
        assert :ok =
                 Loop.run_one_shot(%{
                   prompt: "test",
                   model: "gpt-4o-2024-08-06",
                   session_id: session_id
                 })
      end)

      assert Keyword.get(OneShotMockLLM.last_opts(), :model) == "gpt-4o-2024-08-06"
    end

    test "honors :session_id opt", %{session_id: session_id} do
      OneShotMockLLM.set_response(%{text: "hi", tool_calls: []})

      ExUnit.CaptureIO.capture_io(fn ->
        assert :ok = Loop.run_one_shot(%{prompt: "hello", session_id: session_id})
      end)

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2
    end

    test "generates session_id when not provided" do
      OneShotMockLLM.set_response(%{text: "generated session", tool_calls: []})

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert :ok = Loop.run_one_shot(%{prompt: "hello"})
        end)

      assert output =~ "generated session"
    end
  end

  describe "run_one_shot/1 error paths" do
    setup :setup_mock_llm

    test "unknown agent returns :error", %{session_id: session_id} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert :error =
                   Loop.run_one_shot(%{
                     prompt: "test",
                     agent: "nonexistent-agent-xyz",
                     session_id: session_id
                   })
        end)

      assert output =~ "Unknown agent" or output =~ "⚠"
    end

    test "LLM error returns :error and rolls back user message", %{session_id: session_id} do
      OneShotMockLLM.set_error(:rate_limited)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert :error = Loop.run_one_shot(%{prompt: "hello", session_id: session_id})
        end)

      assert output =~ "⚠" or output =~ "\e[31m"

      messages = State.get_messages(session_id, "code_puppy")
      assert messages == []
    end
  end

  describe "send_to_agent/2 visibility" do
    setup :setup_mock_llm

    test "is callable externally", %{session_id: session_id} do
      OneShotMockLLM.set_response(%{text: "direct call works", tool_calls: []})

      state = %Loop{
        session_id: session_id,
        agent: "code-puppy",
        model: "claude-sonnet-4-20250514",
        running: true
      }

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert :ok = Loop.send_to_agent("test prompt", state)
        end)

      assert output =~ "direct call works"

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2
    end
  end

  describe "interactive mode preservation" do
    test "send_to_agent/2 is still exported" do
      assert function_exported?(Loop, :send_to_agent, 2)
    end

    test "run_one_shot/1 is exported" do
      assert function_exported?(Loop, :run_one_shot, 1)
    end
  end
end
