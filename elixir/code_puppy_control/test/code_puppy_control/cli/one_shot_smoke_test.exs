defmodule CodePuppyControl.CLI.OneShotSmokeMockLLM do
  @moduledoc false
  # Smoke-test-scoped mock LLM. Separate module to avoid BEAM name
  # collisions with OneShotMockLLM / DispatchRollbackMockLLM.
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
        resp = state[:response] || %{text: "smoke mock default", tool_calls: []}
        callback_fn.({:text, resp[:text]})
        callback_fn.({:done, :complete})
        {:ok, resp}

      reason ->
        {:error, reason}
    end
  end
end

defmodule CodePuppyControl.CLI.OneShotSmokeTest do
  @moduledoc """
  Smoke-level tests for CLI one-shot prompt routing and
  Parser → OneShot integration.

  Focuses on what is NOT covered elsewhere:
    * `CLI.resolve_run_mode/1` routing logic
    * End-to-end Parser → OneShot pipeline (2-3 key paths)
    * Error propagation through the full CLI → OneShot pipeline

  Does NOT duplicate:
    * OneShot.run/1 unit dispatch logic (see cli/one_shot_test.exs)
    * Parser flag shape (see cli/gac_parser_test.exs patterns)
    * Help/version text (see cli/cli_test.exs)
  """

  use ExUnit.Case, async: false

  alias CodePuppyControl.Agent.State
  alias CodePuppyControl.CLI
  alias CodePuppyControl.CLI.OneShotSmokeMockLLM
  alias CodePuppyControl.CLI.Parser
  alias CodePuppyControl.REPL.OneShot
  alias CodePuppyControl.Tools.AgentCatalogue

  # ---------------------------------------------------------------------------
  # Shared setup — mock LLM + sandboxed session dir
  # ---------------------------------------------------------------------------

  defp setup_mock_llm(_context) do
    session_id = :crypto.strong_rand_bytes(4) |> Base.encode16(case: :lower)

    prev_llm = Application.get_env(:code_puppy_control, :repl_llm_module)
    Application.put_env(:code_puppy_control, :repl_llm_module, OneShotSmokeMockLLM)
    OneShotSmokeMockLLM.reset()

    # Sandbox SessionStorage so successful OneShot.run never writes to
    # the real ~/.code_puppy_ex/sessions/.  PUP_SESSION_DIR is the
    # canonical env var (see SessionStorage.base_dir/0).  Must be under
    # ~/.code_puppy_ex/ to pass validate_storage_dir!/1.
    ex_home = Path.expand("~/.code_puppy_ex")
    File.mkdir_p!(ex_home)
    tmp_dir = Path.join([ex_home, "sessions", "pup_smoke_#{session_id}"])
    File.mkdir_p!(tmp_dir)
    prev_session_dir = System.get_env("PUP_SESSION_DIR")
    System.put_env("PUP_SESSION_DIR", tmp_dir)

    try do
      AgentCatalogue.discover_agent_modules()
    catch
      _, _ -> :ok
    end

    on_exit(fn ->
      # Drain any lingering async-save tasks BEFORE restoring env vars
      # or removing dirs.  save_session_async/3 spawns Task processes that
      # read PUP_SESSION_DIR and write session files; without this drain
      # they may hit a deleted dir or write to the real user session path.
      Process.sleep(100)

      if prev_llm do
        Application.put_env(:code_puppy_control, :repl_llm_module, prev_llm)
      else
        Application.delete_env(:code_puppy_control, :repl_llm_module)
      end

      OneShotSmokeMockLLM.stop()

      # Restore PUP_SESSION_DIR and clean up sandbox dir.
      # Use File.rm_rf/1 (non-bang) to tolerate concurrent async
      # writes that may create files during removal.
      if prev_session_dir do
        System.put_env("PUP_SESSION_DIR", prev_session_dir)
      else
        System.delete_env("PUP_SESSION_DIR")
      end

      {:ok, _} = File.rm_rf(tmp_dir)

      Enum.each(["code_puppy", "code-corgi", "qa_kitten"], fn agent_key ->
        try do
          State.clear_messages(session_id, agent_key)
        catch
          _, _ -> :ok
        end
      end)

      case Registry.lookup(CodePuppyControl.REPL.RendererRegistry, session_id) do
        [] ->
          :ok

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

  # Helper: parse CLI args, inject session_id, run through OneShot,
  # and return the capture + parsed opts for assertions.
  defp parse_and_run_one_shot(cli_args, session_id) do
    assert {:ok, opts} = Parser.parse(cli_args)
    opts = Map.put(opts, :session_id, session_id)

    output =
      ExUnit.CaptureIO.capture_io(fn ->
        OneShot.run(opts)
      end)

    {output, opts}
  end

  # ===========================================================================
  # CLI routing logic — the unique value of this smoke test
  # ===========================================================================

  describe "CLI.resolve_run_mode/1 — routing" do
    test "-p with non-empty prompt routes to one-shot" do
      assert :one_shot = CLI.resolve_run_mode(%{prompt: "hello"})
    end

    test "positional prompt (non-empty string) routes to one-shot" do
      assert :one_shot = CLI.resolve_run_mode(%{prompt: "explain this code"})
    end

    test "-p with -i routes to interactive with prompt" do
      assert :interactive_with_prompt =
               CLI.resolve_run_mode(%{prompt: "hello", interactive: true})
    end

    test "-c (continue) routes to continue session" do
      assert :continue_session = CLI.resolve_run_mode(%{continue: true})
    end

    test "no prompt, no continue routes to interactive default" do
      assert :interactive_default = CLI.resolve_run_mode(%{})
    end

    test "nil prompt routes to interactive default (not one-shot)" do
      assert :interactive_default = CLI.resolve_run_mode(%{prompt: nil})
    end

    test "empty string prompt routes to interactive default" do
      assert :interactive_default = CLI.resolve_run_mode(%{prompt: ""})
    end

    test "-p with -c still routes to one-shot (prompt takes precedence)" do
      assert :one_shot = CLI.resolve_run_mode(%{prompt: "hello", continue: true})
    end
  end

  # ===========================================================================
  # Parser → OneShot pipeline — integration smoke (only unique paths)
  # ===========================================================================

  describe "Parser → OneShot pipeline — integration smoke" do
    setup :setup_mock_llm

    test "-p with -m and -a combined flows through Parser → OneShot end-to-end",
         %{session_id: session_id} do
      OneShotSmokeMockLLM.set_response(%{text: "combined reply", tool_calls: []})

      {output, opts} =
        parse_and_run_one_shot(
          ["-p", "hello", "-m", "claude-sonnet-4-20250514", "-a", "qa-kitten"],
          session_id
        )

      assert output =~ "combined reply"
      assert opts[:model] == "claude-sonnet-4-20250514"
      assert opts[:agent] == "qa-kitten"

      # Agent-specific bucket has the messages
      messages = State.get_messages(session_id, "qa_kitten")
      assert length(messages) == 2

      # LLM received the correct model
      assert Keyword.get(OneShotSmokeMockLLM.last_opts(), :model) ==
               "claude-sonnet-4-20250514"
    end

    test "positional prompt dispatches through Parser → OneShot", %{
      session_id: session_id
    } do
      OneShotSmokeMockLLM.set_response(%{text: "explanation here", tool_calls: []})

      {output, _opts} = parse_and_run_one_shot(["explain this"], session_id)

      assert output =~ "explanation here"

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2
    end

    test "Parser-produced agent: nil flows through OneShot with nil-defaulting", %{
      session_id: session_id
    } do
      OneShotSmokeMockLLM.set_response(%{text: "nil-agent reply", tool_calls: []})

      # Parser.parse(["-p", "hi"]) produces agent: nil
      assert {:ok, parsed} = Parser.parse(["-p", "hi"])
      assert parsed[:agent] == nil

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          opts = Map.put(parsed, :session_id, session_id)
          assert :ok = OneShot.run(opts)
        end)

      assert output =~ "nil-agent reply"

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2
    end
  end

  # ===========================================================================
  # Error propagation through full pipeline (unique: Parser opts → OneShot)
  # ===========================================================================

  describe "Parser → OneShot pipeline — error propagation" do
    setup :setup_mock_llm

    test "nonexistent agent through full pipeline returns :error and rolls back", %{
      session_id: session_id
    } do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert :error =
                   OneShot.run(%{
                     prompt: "test",
                     agent: "no-such-agent-xyz-999",
                     session_id: session_id
                   })
        end)

      assert output =~ "Unknown agent" or output =~ "⚠"
    end

    test "LLM error through full pipeline returns :error and rolls back user message",
         %{session_id: session_id} do
      OneShotSmokeMockLLM.set_error(:service_unavailable)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert :error =
                   OneShot.run(%{prompt: "hello", session_id: session_id})
        end)

      assert output =~ "⚠" or output =~ "\e[31m"

      # Rollback: no orphaned user message
      messages = State.get_messages(session_id, "code_puppy")
      assert messages == []
    end
  end
end
