defmodule Mana.TUI.App do
  @moduledoc "Main TUI application loop with non-blocking input and tab completion"

  alias Mana.Agent.Runner
  alias Mana.Banner
  alias Mana.Commands.Registry
  alias Mana.Config
  alias Mana.MessageBus
  alias Mana.Session.Store
  alias Mana.TUI.Completion
  alias Mana.TUI.Markdown

  require Logger

  # Completion state tracks the in-progress tab cycle
  defmodule CompletionState do
    @moduledoc false
    defstruct completions: [], cycle_index: -1, last_input: ""
  end

  @doc "Start the TUI application"
  @spec start(keyword()) :: :ok | {:error, :no_tty}
  def start(opts \\ []) do
    # Guard: refuse to start TUI in headless environments
    if tty_available?() do
      start_with_tty(opts)
    else
      Logger.warning("No TTY available — skipping TUI. Set MANA_HEADLESS=true to silence this.")
      return_no_tty()
    end
  end

  defp return_no_tty do
    # In headless mode, start a simple loop that handles shutdown cleanly
    # without any IO operations
    receive do
      :shutdown -> :ok
    after
      :timer.hours(24) -> :ok
    end

    {:error, :no_tty}
  end

  defp start_with_tty(opts) do
    # Create or load session
    session_id =
      case Keyword.get(opts, :session) do
        nil ->
          case Store.active_session() do
            nil -> Store.create_session()
            session -> session
          end

        session ->
          case Store.load(session) do
            {:ok, _} ->
              Store.set_active_session(session)
              session

            {:error, _} ->
              IO.puts(IO.ANSI.format([:red, "Session #{session} not found", :reset]) |> to_string())
              Store.create_session()
          end
      end

    # Subscribe to MessageBus for async messages
    MessageBus.add_listener(self())

    # Print banner
    Banner.print()

    version = Mana.version()

    safe_puts(
      IO.ANSI.format([:faint, "  v#{version}  •  Type /help for commands, /quit to exit\n", :reset])
      |> to_string()
    )

    # Enable raw mode for character-by-character input (supports tab completion)
    enable_raw_mode()

    # Start input reader process for non-blocking raw input
    input_pid = spawn_raw_reader(self())

    # Print initial prompt
    redraw_prompt("")

    # Main loop with non-blocking input and completion state
    loop(session_id, opts, input_pid, %CompletionState{})
  end

  # Check if a TTY is available for IO operations
  defp tty_available? do
    Mana.Application.tty_available?()
  end

  # Safe IO.puts that catches errors from missing IO devices
  defp safe_puts(text) do
    IO.puts(text)
  rescue
    ArgumentError -> :ok
    ErlangError -> :ok
  end

  # Safe IO.write that catches errors from missing IO devices
  defp safe_write(text) do
    IO.write(text)
  rescue
    ArgumentError -> :ok
    ErlangError -> :ok
  end

  # Enable raw mode on the terminal so we receive individual keystrokes
  defp enable_raw_mode do
    case :io.getopts(:standard_io) do
      opts when is_list(opts) ->
        :io.setopts(:standard_io, [:binary, {:echo, false}, {:canonical, false}])

      _ ->
        :ok
    end
  rescue
    ArgumentError -> :ok
  end

  # Restore the terminal to cooked (line-buffered) mode
  defp restore_terminal_mode do
    :io.setopts(:standard_io, [:binary, {:echo, true}, {:canonical, true}])
  rescue
    _ -> :ok
  end

  # Spawns a separate process to read raw input and forward keystrokes/lines
  defp spawn_raw_reader(parent_pid) do
    spawn(fn -> raw_reader_loop(parent_pid) end)
  end

  # Raw reader loop — reads one byte/character at a time.
  # Sends {:key, char} for printable chars and {:key, sequence} for special keys.
  # On Enter (\n or \r), sends the accumulated line as {:input, line}.
  defp raw_reader_loop(parent_pid) do
    case IO.read(1) do
      :eof ->
        send(parent_pid, {:input, "/quit\n"})

      {:error, _} ->
        send(parent_pid, {:input, "/quit\n"})

      <<9>> ->
        # Tab key
        send(parent_pid, {:key, :tab})
        raw_reader_loop(parent_pid)

      <<3>> ->
        # Ctrl-C
        send(parent_pid, {:key, :ctrl_c})
        raw_reader_loop(parent_pid)

      <<127>> ->
        # Backspace (common terminal)
        send(parent_pid, {:key, :backspace})
        raw_reader_loop(parent_pid)

      <<27>> ->
        # Escape sequence — peek ahead for arrow keys etc.
        handle_escape(parent_pid)
        raw_reader_loop(parent_pid)

      <<10>> ->
        # Newline (\n) — Enter key
        send(parent_pid, {:key, :enter})
        raw_reader_loop(parent_pid)

      <<13>> ->
        # Carriage return (\r) — Enter key
        send(parent_pid, {:key, :enter})
        raw_reader_loop(parent_pid)

      <<ch>> when ch >= 32 ->
        # Printable character
        send(parent_pid, {:key, <<ch>>})
        raw_reader_loop(parent_pid)

      _other ->
        raw_reader_loop(parent_pid)
    end
  end

  # Handle ANSI escape sequences (arrow keys, etc.)
  defp handle_escape(parent_pid) do
    # Try to read the rest of the escape sequence with a small timeout
    receive do
      {:io_reply, _, <<91, 65>>} ->
        # Up arrow: \e[A
        send(parent_pid, {:key, :up})

      {:io_reply, _, <<91, 66>>} ->
        # Down arrow: \e[B
        send(parent_pid, {:key, :down})

      {:io_reply, _, <<91, 67>>} ->
        # Right arrow: \e[C
        send(parent_pid, {:key, :right})

      {:io_reply, _, <<91, 68>>} ->
        # Left arrow: \e[D
        send(parent_pid, {:key, :left})

      _ ->
        :ok
    after
      20 -> :ok
    end
  end

  # Main loop — processes key events and maintains a line buffer
  # along with completion state for tab cycling.
  defp loop(session_id, opts, input_pid, cs) do
    receive do
      {:key, :tab} ->
        cs = handle_tab(cs, opts)
        loop(session_id, opts, input_pid, cs)

      {:key, :enter} ->
        line = cs.last_input
        # Move to new line, then process
        IO.write("\n")
        cs = %CompletionState{}
        handle_input(line <> "\n", session_id, opts, input_pid)
        loop(session_id, opts, input_pid, cs)

      {:key, :backspace} ->
        buffer = cs.last_input

        new_buffer =
          if byte_size(buffer) > 0 do
            binary_part(buffer, 0, byte_size(buffer) - 1)
          else
            buffer
          end

        cs = reset_completion(new_buffer)
        redraw_prompt(new_buffer)
        loop(session_id, opts, input_pid, cs)

      {:key, :ctrl_c} ->
        safe_write("^C\n")
        cs = %CompletionState{}
        redraw_prompt("")
        loop(session_id, opts, input_pid, cs)

      {:key, ch} when is_binary(ch) ->
        new_buffer = cs.last_input <> ch
        cs = reset_completion(new_buffer)
        redraw_prompt(new_buffer)
        loop(session_id, opts, input_pid, cs)

      {:key, _other} ->
        # Ignore other special keys for now
        loop(session_id, opts, input_pid, cs)

      {:message, %{type: :text} = msg} ->
        # Clear current prompt line, print message, redraw prompt
        safe_write("\r\e[K")
        safe_puts(IO.ANSI.format([:faint, msg.content, :reset]) |> to_string())
        redraw_prompt(cs.last_input)
        loop(session_id, opts, input_pid, cs)

      {:message, _msg} ->
        loop(session_id, opts, input_pid, cs)

      _other ->
        loop(session_id, opts, input_pid, cs)
    end
  end

  # Handle Tab key — complete or cycle through completions
  defp handle_tab(%CompletionState{completions: [], last_input: input} = cs, _opts) do
    # No active completions — compute new ones
    {completions, common} = Completion.complete(input, %{})

    case completions do
      [] ->
        # No matches — beep
        safe_write("\a")
        cs

      [single] ->
        # Single match — auto-complete
        new_input = single <> " "
        redraw_prompt(new_input)
        %CompletionState{last_input: new_input}

      _multiple ->
        # Multiple matches — fill common prefix, show options, start cycling
        if common != input and common != "" do
          redraw_prompt(common)
        end

        # Display completions on a new line
        display_completions(completions)
        redraw_prompt(if common != "", do: common, else: input)

        %CompletionState{
          completions: completions,
          cycle_index: 0,
          last_input: if(common != "", do: common, else: input)
        }
    end
  end

  defp handle_tab(%CompletionState{completions: completions, cycle_index: idx} = cs, _opts)
       when completions != [] do
    # Already cycling — advance to next completion
    {next_idx, selected} = Completion.cycle(idx, completions)
    redraw_prompt(selected)
    %CompletionState{cs | cycle_index: next_idx, last_input: selected}
  end

  # Reset completion state when user types new characters or backspaces
  defp reset_completion(new_buffer) do
    %CompletionState{last_input: new_buffer}
  end

  # Redraw the prompt with the current buffer contents
  defp redraw_prompt(buffer) do
    prompt = IO.ANSI.format([:bright, :green, "❯ ", :reset]) |> to_string()
    IO.write("\r\e[K#{prompt}#{buffer}")
  end

  # Display a list of completion options
  defp display_completions(completions) do
    formatted =
      Enum.map_join(completions, "  ", fn c ->
        IO.ANSI.format([:cyan, c, :reset]) |> to_string()
      end)

    safe_write("\n#{formatted}\n")
  end

  defp handle_input(input, session_id, opts, input_pid) do
    cs = %CompletionState{}

    case String.trim(input) do
      "" ->
        redraw_prompt("")
        loop(session_id, opts, input_pid, cs)

      "/quit" ->
        shutdown(session_id, input_pid)

      "/help" ->
        print_help()
        redraw_prompt("")
        loop(session_id, opts, input_pid, cs)

      "/clear" ->
        safe_write("\e[2J\e[H")
        redraw_prompt("")
        loop(session_id, opts, input_pid, cs)

      "/" <> command ->
        dispatch_command(command, session_id)
        redraw_prompt("")
        loop(session_id, opts, input_pid, cs)

      message ->
        run_agent(message, session_id, opts)
        redraw_prompt("")
        loop(session_id, opts, input_pid, cs)
    end
  end

  defp dispatch_command(command, session_id) do
    [cmd | args] = String.split(command, " ", trim: true)
    full_cmd = "/#{cmd}"

    context = %{session_id: session_id}

    case Registry.dispatch(full_cmd, args, context) do
      {:ok, result} when is_binary(result) ->
        safe_puts(IO.ANSI.format([:green, result, :reset]) |> to_string())

      {:ok, result} ->
        safe_puts(IO.ANSI.format([:green, inspect(result), :reset]) |> to_string())

      :ok ->
        :ok

      {:error, :unknown_command} ->
        safe_puts(IO.ANSI.format([:red, "Unknown command: #{full_cmd}", :reset]) |> to_string())
        suggest_commands(full_cmd)

      {:error, reason} ->
        safe_puts(IO.ANSI.format([:red, "Error: #{inspect(reason)}", :reset]) |> to_string())
    end
  end

  defp suggest_commands(command) do
    available = Registry.list_commands()

    suggestions =
      Enum.filter(available, fn cmd ->
        String.jaro_distance(cmd, command) > 0.6
      end)

    if suggestions != [] do
      safe_puts(
        IO.ANSI.format([:faint, "Did you mean: #{Enum.join(suggestions, ", ")}?", :reset])
        |> to_string()
      )
    end
  end

  alias Mana.Agent.Builder

  defp run_agent(message, session_id, opts) do
    model = Keyword.get(opts, :model, Config.global_model_name())

    safe_puts(IO.ANSI.format([:faint, "Thinking...", :reset]) |> to_string())

    # Build a simple agent definition for general chat
    agent_def = %{
      name: "assistant",
      system_prompt: "You are a helpful assistant.",
      available_tools: []
    }

    # Start agent server
    case Builder.build_from_map(agent_def, model_name: model, session_id: session_id) do
      {:ok, agent_pid} ->
        case Runner.run(agent_pid, message, model: model) do
          {:ok, response} ->
            rendered = Markdown.render(response)
            safe_puts(rendered)

          {:error, reason} ->
            safe_puts(IO.ANSI.format([:red, "Error: #{inspect(reason)}", :reset]) |> to_string())
        end

      {:error, reason} ->
        safe_puts(
          IO.ANSI.format([:red, "Failed to start agent: #{inspect(reason)}", :reset])
          |> to_string()
        )
    end
  end

  defp print_help do
    help_text = """
    #{IO.ANSI.format([:bright, :cyan, "Commands:", :reset]) |> to_string()}
      /help          Show this help message
      /model         Manage AI models (/model list|set <name>|current)
      /agent         Manage agents (/agent list|set <name>|current)
      /session       Manage sessions (/session list|new|delete <id>)
      /save          Save current session
      /load          Load a saved session
      /compact       Compact conversation via summarization
      /truncate      Truncate conversation to last N messages
      /clear         Clear the terminal
      /quit          Exit Mana
    """

    safe_puts(help_text)
  end

  defp shutdown(session_id, input_pid) do
    # Restore terminal before exiting
    restore_terminal_mode()

    # Stop the input reader process
    Process.exit(input_pid, :kill)

    Store.set_active_session(session_id)
    Store.save(session_id)
    MessageBus.remove_listener(self())
    safe_puts(IO.ANSI.format([:cyan, "Goodbye! 👋", :reset]) |> to_string())
    :ok
  end

  # Deprecated: kept for backwards compatibility
  def handle_message({:message, %{type: :text} = msg}) do
    safe_puts(IO.ANSI.format([:faint, msg.content, :reset]) |> to_string())
    :ok
  end

  def handle_message({:message, _msg}) do
    # Ignore other message types
    :ok
  end

  def handle_message(_other) do
    :ok
  end
end
