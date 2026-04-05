defmodule Mana.TUI.App do
  @moduledoc "Main TUI application loop"

  alias Mana.Agent.Runner
  alias Mana.Banner
  alias Mana.Commands.Registry
  alias Mana.Config
  alias Mana.MessageBus
  alias Mana.Session.Store
  alias Mana.TUI.Markdown

  require Logger

  @doc "Start the TUI application"
  @spec start(keyword()) :: :ok
  def start(opts \\ []) do
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

    IO.puts(
      IO.ANSI.format([:faint, "  v#{version}  •  Type /help for commands, /quit to exit\n", :reset])
      |> to_string()
    )

    # Main loop
    loop(session_id, opts)
  end

  defp loop(session_id, opts) do
    input = read_input()

    case String.trim(input) do
      "" ->
        loop(session_id, opts)

      "/quit" ->
        shutdown(session_id)

      "/help" ->
        print_help()
        loop(session_id, opts)

      "/clear" ->
        IO.write("\e[2J\e[H")
        loop(session_id, opts)

      "/" <> command ->
        dispatch_command(command, session_id)
        loop(session_id, opts)

      message ->
        run_agent(message, session_id, opts)
        loop(session_id, opts)
    end
  end

  defp read_input do
    prompt = IO.ANSI.format([:bright, :green, "❯ ", :reset]) |> to_string()
    IO.write(prompt)

    case IO.read(:line) do
      :eof -> "/quit\n"
      {:error, _} -> "/quit\n"
      line when is_binary(line) -> line
    end
  end

  defp dispatch_command(command, session_id) do
    [cmd | args] = String.split(command, " ", trim: true)
    full_cmd = "/#{cmd}"

    context = %{session_id: session_id}

    case Registry.dispatch(full_cmd, args, context) do
      {:ok, result} when is_binary(result) ->
        IO.puts(IO.ANSI.format([:green, result, :reset]) |> to_string())

      {:ok, result} ->
        IO.puts(IO.ANSI.format([:green, inspect(result), :reset]) |> to_string())

      :ok ->
        :ok

      {:error, :unknown_command} ->
        IO.puts(IO.ANSI.format([:red, "Unknown command: #{full_cmd}", :reset]) |> to_string())
        suggest_commands(full_cmd)

      {:error, reason} ->
        IO.puts(IO.ANSI.format([:red, "Error: #{inspect(reason)}", :reset]) |> to_string())
    end
  end

  defp suggest_commands(command) do
    available = Registry.list_commands()

    suggestions =
      Enum.filter(available, fn cmd ->
        String.jaro_distance(cmd, command) > 0.6
      end)

    if suggestions != [] do
      IO.puts(
        IO.ANSI.format([:faint, "Did you mean: #{Enum.join(suggestions, ", ")}?", :reset])
        |> to_string()
      )
    end
  end

  alias Mana.Agent.Builder

  defp run_agent(message, session_id, opts) do
    model = Keyword.get(opts, :model, Config.global_model_name())

    IO.puts(IO.ANSI.format([:faint, "Thinking...", :reset]) |> to_string())

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
            IO.puts(rendered)

          {:error, reason} ->
            IO.puts(IO.ANSI.format([:red, "Error: #{inspect(reason)}", :reset]) |> to_string())
        end

      {:error, reason} ->
        IO.puts(
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

    IO.puts(help_text)
  end

  defp shutdown(session_id) do
    Store.set_active_session(session_id)
    Store.save(session_id)
    MessageBus.remove_listener(self())
    IO.puts(IO.ANSI.format([:cyan, "Goodbye! 👋", :reset]) |> to_string())
    :ok
  end

  @doc "Handle messages from MessageBus (for async notifications)"
  @spec handle_message(any()) :: :ok
  def handle_message({:message, %{type: :text} = msg}) do
    IO.puts(IO.ANSI.format([:faint, msg.content, :reset]) |> to_string())
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
