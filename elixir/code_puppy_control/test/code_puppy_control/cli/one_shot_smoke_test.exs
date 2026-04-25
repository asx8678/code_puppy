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
  Smoke-level tests for the CLI one-shot prompt path.

  Verifies that `pup -p "..."` (and equivalent invocations) reach
  the OneShot runner/agent pipeline with parser-shaped opts, without
  duplicating low-value tests already in `cli/one_shot_test.exs`.

  ## What's tested here (and NOT in one_shot_test.exs)

    * `CLI.resolve_run_mode/1` routing logic (one-shot vs interactive)
    * Full Parser → OneShot pipeline (CLI args → parsed opts → OneShot.run)
    * Combined flag interactions (`-p` with `-m`, `-a`, positional args)
    * Parser opts shape / compatibility with `OneShot.run/1`
    * Error propagation through the full CLI → OneShot pipeline

  ## What's NOT tested here (already covered)

    * OneShot.run/1 internal dispatch logic
    * Message persistence / rollback details
    * Per-agent routing inside OneShot (those are unit-level)
  """

  use ExUnit.Case, async: false

  alias CodePuppyControl.Agent.State
  alias CodePuppyControl.CLI
  alias CodePuppyControl.CLI.OneShotSmokeMockLLM
  alias CodePuppyControl.CLI.Parser
  alias CodePuppyControl.REPL.OneShot
  alias CodePuppyControl.Tools.AgentCatalogue

  # ---------------------------------------------------------------------------
  # Shared setup
  # ---------------------------------------------------------------------------

  defp setup_mock_llm(_context) do
    session_id = :crypto.strong_rand_bytes(4) |> Base.encode16(case: :lower)

    prev_llm = Application.get_env(:code_puppy_control, :repl_llm_module)
    Application.put_env(:code_puppy_control, :repl_llm_module, OneShotSmokeMockLLM)
    OneShotSmokeMockLLM.reset()

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

      OneShotSmokeMockLLM.stop()

      Enum.each(["code_puppy", "code-puppy", "qa_kitten"], fn agent_key ->
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
  # CLI routing logic
  # ===========================================================================

  describe "CLI.resolve_run_mode/1 — routing" do
    test "-p with non-empty prompt routes to one-shot" do
      opts = %{prompt: "hello"}
      assert :one_shot = CLI.resolve_run_mode(opts)
    end

    test "positional prompt (non-empty string) routes to one-shot" do
      opts = %{prompt: "explain this code"}
      assert :one_shot = CLI.resolve_run_mode(opts)
    end

    test "-p with -i routes to interactive with prompt" do
      opts = %{prompt: "hello", interactive: true}
      assert :interactive_with_prompt = CLI.resolve_run_mode(opts)
    end

    test "-c (continue) routes to continue session" do
      opts = %{continue: true}
      assert :continue_session = CLI.resolve_run_mode(opts)
    end

    test "no prompt, no continue routes to interactive default" do
      opts = %{}
      assert :interactive_default = CLI.resolve_run_mode(opts)
    end

    test "nil prompt routes to interactive default (not one-shot)" do
      opts = %{prompt: nil}
      assert :interactive_default = CLI.resolve_run_mode(opts)
    end

    test "empty string prompt routes to interactive default (not one-shot)" do
      # Guard: `is_binary(prompt) and prompt != ""`
      opts = %{prompt: ""}
      assert :interactive_default = CLI.resolve_run_mode(opts)
    end

    test "-p with -c still routes to one-shot (prompt takes precedence)" do
      # When both prompt and continue are set, prompt wins because
      # it's matched first in the case statement.
      opts = %{prompt: "hello", continue: true}
      assert :one_shot = CLI.resolve_run_mode(opts)
    end
  end

  # ===========================================================================
  # Parser → OneShot pipeline — happy path
  # ===========================================================================

  describe "Parser → OneShot pipeline — happy path" do
    setup :setup_mock_llm

    test "pup -p \"hello\" dispatches through OneShot and persists messages", %{
      session_id: session_id
    } do
      OneShotSmokeMockLLM.set_response(%{text: "hello back!", tool_calls: []})

      {output, _opts} = parse_and_run_one_shot(["-p", "hello"], session_id)

      assert output =~ "hello back!"

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2
      assert [%{"role" => "user"}, %{"role" => "assistant"}] = messages
    end

    test "pup \"explain this\" (positional) dispatches through OneShot", %{
      session_id: session_id
    } do
      OneShotSmokeMockLLM.set_response(%{text: "explanation here", tool_calls: []})

      {output, _opts} = parse_and_run_one_shot(["explain this"], session_id)

      assert output =~ "explanation here"

      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2
    end

    test "pup -p \"hello\" -m custom-model reaches LLM with correct model", %{
      session_id: session_id
    } do
      OneShotSmokeMockLLM.set_response(%{text: "using custom model", tool_calls: []})

      {_output, opts} = parse_and_run_one_shot(["-p", "hello", "-m", "gpt-4o-mini"], session_id)

      # Verify the model opt was set in parsed opts
      assert opts[:model] == "gpt-4o-mini"

      # Verify the mock LLM received the model
      assert Keyword.get(OneShotSmokeMockLLM.last_opts(), :model) == "gpt-4o-mini"
    end

    test "pup -p \"hello\" -a qa-kitten routes to qa_kitten bucket", %{
      session_id: session_id
    } do
      OneShotSmokeMockLLM.set_response(%{text: "QA reply", tool_calls: []})

      {_output, _opts} = parse_and_run_one_shot(["-p", "hello", "-a", "qa-kitten"], session_id)

      messages = State.get_messages(session_id, "qa_kitten")
      assert length(messages) == 2
      assert [%{"role" => "user"}, %{"role" => "assistant"}] = messages
    end

    test "pup -p \"hello\" -m model -a agent combined reaches OneShot correctly", %{
      session_id: session_id
    } do
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
  end

  # ===========================================================================
  # Parser → OneShot pipeline — error paths
  # ===========================================================================

  describe "Parser → OneShot pipeline — error paths" do
    setup :setup_mock_llm

    test "pup -p \"test\" -a nonexistent-agent returns :error through pipeline", %{
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

      # Messages land in code_puppy (default)
      messages = State.get_messages(session_id, "code_puppy")
      assert length(messages) == 2
    end
  end

  # ===========================================================================
  # Parser opts shape / compatibility with OneShot.run/1
  # ===========================================================================

  describe "Parser opts shape for OneShot.run/1" do
    test "-p opts contain :prompt key fetchable by Map.fetch!" do
      assert {:ok, opts} = Parser.parse(["-p", "hello"])
      # OneShot.run/1 uses Map.fetch!(opts, :prompt) — must not raise
      assert {:ok, prompt} = Map.fetch(opts, :prompt)
      assert prompt == "hello"
    end

    test "combined -p -m -a opts produce complete map with all OneShot keys" do
      assert {:ok, opts} =
               Parser.parse(["-p", "do thing", "-m", "gpt-4o", "-a", "qa-kitten"])

      # Verify every key OneShot.run/1 reads is present (even if nil)
      assert Map.has_key?(opts, :prompt)
      assert Map.has_key?(opts, :model)
      assert Map.has_key?(opts, :agent)

      # And they have the expected values
      assert opts[:prompt] == "do thing"
      assert opts[:model] == "gpt-4o"
      assert opts[:agent] == "qa-kitten"
    end

    test "positional prompt produces :prompt key compatible with OneShot" do
      assert {:ok, opts} = Parser.parse(["explain this code"])
      assert Map.has_key?(opts, :prompt)
      assert opts[:prompt] == "explain this code"
    end

    test "no prompt at all produces :prompt == nil (not missing key)" do
      # Parser always includes the :prompt key, even when absent
      assert {:ok, opts} = Parser.parse([])
      assert Map.has_key?(opts, :prompt)
      assert opts[:prompt] == nil
    end

    test "-p with empty string produces :prompt == \"\" (non-nil, but empty)" do
      assert {:ok, opts} = Parser.parse(["-p", ""])
      assert opts[:prompt] == ""
      # This is correctly rejected by CLI.resolve_run_mode/1
      assert :interactive_default = CLI.resolve_run_mode(opts)
    end
  end

  # ===========================================================================
  # CLI.main/1 fast-path routing (help / version / error)
  # ===========================================================================

  describe "CLI.main/1 routing via Parser" do
    test "--help parses to {:help, _} (verified by Parser)" do
      assert {:help, _opts} = Parser.parse(["--help"])
    end

    test "-h parses to {:help, _}" do
      assert {:help, _opts} = Parser.parse(["-h"])
    end

    test "--version parses to {:version, _}" do
      assert {:version, _opts} = Parser.parse(["--version"])
    end

    test "-v parses to {:version, _}" do
      assert {:version, _opts} = Parser.parse(["-v"])
    end

    test "unknown flag parses to {:error, msg}" do
      assert {:error, msg} = Parser.parse(["--absolutely-bogus"])
      assert msg =~ "absolutely-bogus"
    end

    test "valid one-shot args parse to {:ok, opts} with prompt" do
      assert {:ok, opts} = Parser.parse(["-p", "do something"])
      assert opts[:prompt] == "do something"
    end
  end
end
