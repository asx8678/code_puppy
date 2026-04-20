defmodule CodePuppyControl.REPL.Loop do
  @moduledoc """
  Interactive REPL loop for Code Puppy.

  Handles the read-eval-print cycle:
  1. Display prompt with context (agent, model, session)
  2. Read user input (with history/multiline support via REPL.Input)
  3. Process input (slash commands or agent prompts)
  4. Display output via TUI.Renderer
  5. Repeat

  ## Architecture

  The REPL loop can operate in two modes:

  - **Blocking** (`run/1`) — The main CLI entry point. Blocks the calling
    process in a tight read-eval loop until `/quit` or EOF.
  - **GenServer** (`start_link/1`) — For supervision and hot code reload.
    The GenServer drives the same loop via `handle_continue/2`.

  ## Slash Commands (Phase 1)

    * `/help`    — Show available commands
    * `/quit`    — Exit the REPL
    * `/exit`    — Alias for /quit
    * `/model`   — Show current model
    * `/model <name>` — Switch model
    * `/agent`   — Show current agent
    * `/agent <name>` — Switch agent
    * `/clear`   — Clear the terminal screen
    * `/history` — Show command history

  Phase 2-3 will add tab completion, raw-mode key handling,
  and more commands (bd-161).
  """

  use GenServer

  require Logger

  alias CodePuppyControl.REPL.Input
  alias CodePuppyControl.Config.Models

  # ── Constants ─────────────────────────────────────────────────────────────

  # Maximum history entries to keep in-memory
  @max_history 1000

  # ── State ──────────────────────────────────────────────────────────────────

  defstruct [
    :session_id,
    agent: "code-puppy",
    model: nil,
    history: [],
    history_index: 0,
    running: true
  ]

  @type t :: %__MODULE__{
          session_id: String.t() | nil,
          agent: String.t(),
          model: String.t() | nil,
          history: [String.t()],
          history_index: non_neg_integer(),
          running: boolean()
        }

  # ── Client API ─────────────────────────────────────────────────────────────

  @doc """
  Starts the REPL loop GenServer.

  ## Options

    * `:agent` — Initial agent name (default: "code-puppy")
    * `:model` — Initial model override (default: from config)
    * `:session_id` — Session identifier
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Blocking REPL loop for CLI use.

  This is the main entry point from `CLI.run_interactive/1`.
  Runs the read-eval-print loop until `/quit`, `/exit`, or EOF.
  Does NOT start a GenServer — runs inline in the calling process.
  """
  @spec run(map()) :: :ok
  def run(opts) when is_map(opts) do
    agent = Map.get(opts, :agent, "code-puppy")
    model = Map.get(opts, :model) || Models.global_model_name()
    session_id = Map.get(opts, :session_id) || generate_session_id()

    state = %__MODULE__{
      agent: agent,
      model: model,
      session_id: session_id,
      history: [],
      history_index: 0,
      running: true
    }

    print_welcome(state)
    do_loop(state)
  end

  @doc """
  Process a single line of input through the REPL.

  Returns `{:continue, state}` to keep looping, or `{:halt, state}` to exit.
  Separated from the loop for testability.
  """
  @spec handle_input(String.t(), t()) :: {:continue, t()} | {:halt, t()}
  def handle_input(line, state) do
    trimmed = String.trim(line)

    cond do
      trimmed == "" ->
        {:continue, state}

      is_slash_command?(trimmed) ->
        execute_slash_command(trimmed, state)

      is_shell_passthrough?(trimmed) ->
        execute_shell_passthrough(trimmed, state)
        {:continue, state}

      true ->
        state = record_history(state, trimmed)
        send_to_agent(trimmed, state)
        {:continue, state}
    end
  end

  # ── GenServer Callbacks ────────────────────────────────────────────────────

  @impl true
  def init(opts) do
    agent = Keyword.get(opts, :agent, "code-puppy")
    model = Keyword.get(opts, :model) || Models.global_model_name()
    session_id = Keyword.get(opts, :session_id) || generate_session_id()

    state = %__MODULE__{
      agent: agent,
      model: model,
      session_id: session_id,
      history: [],
      history_index: 0,
      running: true
    }

    {:ok, state, {:continue, :loop}}
  end

  @impl true
  def handle_continue(:loop, %{running: false} = state) do
    {:stop, :normal, state}
  end

  def handle_continue(:loop, state) do
    prompt = Input.display_prompt(agent: state.agent, model: state.model)

    case Input.read_multiline(prompt, agent: state.agent, model: state.model) do
      {:ok, line} ->
        case handle_input(line, state) do
          {:continue, new_state} ->
            {:noreply, new_state, {:continue, :loop}}

          {:halt, new_state} ->
            {:stop, :normal, %{new_state | running: false}}
        end

      :eof ->
        IO.puts("\n👋 Bye!")
        {:stop, :normal, %{state | running: false}}

      {:error, reason} ->
        Logger.error("REPL input error: #{inspect(reason)}")
        {:stop, {:error, reason}, state}
    end
  end

  # ── Slash Command Detection ────────────────────────────────────────────────

  @doc """
  Returns true if the input line starts with `/` (slash command).
  """
  @spec is_slash_command?(String.t()) :: boolean()
  def is_slash_command?("/" <> _), do: true
  def is_slash_command?(_), do: false

  # ── Slash Command Execution ───────────────────────────────────────────────

  @spec execute_slash_command(String.t(), t()) :: {:continue, t()} | {:halt, t()}
  defp execute_slash_command(line, state) do
    # Split "/command arg1 arg2" into ["/command", "arg1 arg2"]
    [cmd | rest] = String.split(line, " ", parts: 2)
    args = List.first(rest, "")

    case cmd do
      "/quit" ->
        IO.puts("👋 Bye!")
        {:halt, %{state | running: false}}

      "/exit" ->
        IO.puts("👋 Bye!")
        {:halt, %{state | running: false}}

      "/help" ->
        print_help()
        {:continue, state}

      "/model" ->
        handle_model_command(args, state)

      "/agent" ->
        handle_agent_command(args, state)

      "/clear" ->
        # ANSI clear screen + cursor home
        IO.write("\e[2J\e[H")
        {:continue, state}

      "/history" ->
        print_history(state)
        {:continue, state}

      unknown ->
        IO.puts(IO.ANSI.red() <> "Unknown command: #{unknown}" <> IO.ANSI.reset())
        IO.puts("Type /help for available commands.")
        {:continue, state}
    end
  end

  # ── Command Handlers ──────────────────────────────────────────────────────

  defp handle_model_command("", state) do
    # Show current model
    IO.puts("Current model: #{state.model}")
    {:continue, state}
  end

  defp handle_model_command(model_name, state) do
    model_name = String.trim(model_name)
    IO.puts("Switching model: #{state.model} → #{model_name}")

    # Persist the change (best-effort; Config.Writer may not be running in test)
    try do
      :ok = Models.set_global_model(model_name)
    catch
      :exit, _ -> :ok
    end

    {:continue, %{state | model: model_name}}
  end

  defp handle_agent_command("", state) do
    # Show current agent
    IO.puts("Current agent: #{state.agent}")
    {:continue, state}
  end

  defp handle_agent_command(agent_name, state) do
    agent_name = String.trim(agent_name)
    IO.puts("Switching agent: #{state.agent} → #{agent_name}")
    {:continue, %{state | agent: agent_name}}
  end

  # ── Shell Passthrough ─────────────────────────────────────────────────────

  @doc """
  Returns true if the input line is a shell passthrough (`!command`).
  """
  @spec is_shell_passthrough?(String.t()) :: boolean()
  def is_shell_passthrough?("!" <> _), do: true
  def is_shell_passthrough?(_), do: false

  defp execute_shell_passthrough("!" <> cmd, _state) do
    # Run the shell command and display output
    case System.shell(cmd, stderr_to_stdout: true) do
      {output, 0} ->
        IO.puts(output)

      {output, exit_code} ->
        IO.puts(IO.ANSI.red() <> "Exit code: #{exit_code}" <> IO.ANSI.reset())
        IO.puts(output)
    end
  end

  # ── Agent Prompt Dispatch ─────────────────────────────────────────────────

  defp send_to_agent(prompt, state) do
    # TODO(bd-160): Phase 2 — wire to Agent.Loop.run/3 with streaming
    # For now, display intent and echo (no-op agent pipeline)
    Logger.debug("REPL: send_to_agent agent=#{state.agent} model=#{state.model}")

    IO.puts(IO.ANSI.faint() <> "[repl] Prompt dispatched to #{state.agent}@#{state.model}" <> IO.ANSI.reset())
    IO.puts(IO.ANSI.faint() <> "[repl] Agent pipeline not yet wired — prompt: \"#{String.slice(prompt, 0, 80)}\"" <> IO.ANSI.reset())
  end

  # ── History ────────────────────────────────────────────────────────────────

  defp record_history(state, line) do
    # Don't record blank or duplicate entries
    if line == "" || (state.history != [] && hd(state.history) == line) do
      state
    else
      history = [line | state.history] |> Enum.take(@max_history)
      %{state | history: history, history_index: 0}
    end
  end

  defp print_history(state) do
    if state.history == [] do
      IO.puts("(no history)")
    else
      state.history
      |> Enum.reverse()
      |> Enum.with_index(1)
      |> Enum.each(fn {entry, idx} ->
        IO.puts("  #{idx}: #{entry}")
      end)
    end
  end

  # ── Welcome & Help ─────────────────────────────────────────────────────────

  defp print_welcome(state) do
    IO.puts("""

    🐶 Code Puppy — Interactive Mode
    ─────────────────────────────────
    Agent:  #{state.agent}
    Model:  #{state.model}
    Session: #{state.session_id}

    Type /help for commands, /quit to exit.
    """)
  end

  defp print_help do
    IO.puts("""

    Available commands:
      /help              Show this help message
      /quit, /exit       Exit the REPL
      /model             Show current model
      /model <name>      Switch to a different model
      /agent             Show current agent
      /agent <name>      Switch to a different agent
      /clear             Clear the terminal screen
      /history           Show command history
      !<command>         Run a shell command (e.g., !git status)

    Tips:
      - Use Ctrl+D to exit
      - Unclosed brackets/quotes enable multi-line input
      - Phase 2 will add tab completion and arrow-key navigation
    """)
  end

  # ── Main Loop ──────────────────────────────────────────────────────────────

  defp do_loop(%{running: false} = state), do: state

  defp do_loop(state) do
    prompt = Input.display_prompt(agent: state.agent, model: state.model)

    case Input.read_multiline(prompt, agent: state.agent, model: state.model) do
      {:ok, line} ->
        case handle_input(line, state) do
          {:continue, new_state} ->
            do_loop(new_state)

          {:halt, new_state} ->
            new_state
        end

      :eof ->
        IO.puts("\n👋 Bye!")
        state

      {:error, reason} ->
        Logger.error("REPL input error: #{inspect(reason)}")
        state
    end
  end

  # ── Helpers ────────────────────────────────────────────────────────────────

  defp generate_session_id do
    :crypto.strong_rand_bytes(4) |> Base.encode16(case: :lower)
  end
end
