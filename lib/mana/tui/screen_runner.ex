defmodule Mana.TUI.ScreenRunner do
  @moduledoc """
  Runs any module implementing `Mana.TUI.Screen` in a render → input → handle loop.

  ## Usage

      # Run a screen with default options
      Mana.TUI.ScreenRunner.run(MyScreen)

      # Run with initial options passed to `init/1`
      Mana.TUI.ScreenRunner.run(MyScreen, title: "Settings")

  The runner clears the terminal between renders, displays the screen
  output, and waits for a line of input. When the screen signals `:done`
  or `:exit`, the terminal is cleared and control returns to the caller.

  ## Integration with `Mana.TUI.App`

  Screens can be launched from command handlers in the main TUI:

      defp handle_input("/settings" <> _, session_id, opts, input_pid) do
        Mana.TUI.ScreenRunner.run(Mana.TUI.Screens.Settings, session_id: session_id)
        loop(session_id, opts, input_pid)
      end
  """


  @doc """
  Run a screen module in an interactive loop.

  ## Parameters

    * `screen_module` – a module implementing `Mana.TUI.Screen`
    * `opts`          – keyword list passed to `c:Screen.init/1` (if defined)

  ## Returns

    * `:ok`              – screen exited via `:exit`
    * `{:ok, result}`    – screen exited via `{:done, result}`
    * `{:error, reason}` – screen init failed
  """
  @spec run(module(), keyword()) :: :ok | {:ok, term()} | {:error, term()}
  def run(screen_module, opts \\ []) do
    # Initialise screen state
    with {:ok, state} <- init_screen(screen_module, opts) do
      # Spawn non-blocking input reader
      parent = self()
      input_pid = spawn(fn -> input_reader_loop(parent) end)

      # Enter the main loop
      result = loop(screen_module, state, input_pid)

      # Clean up input reader
      Process.exit(input_pid, :kill)

      # Clear screen before returning control
      IO.write("\e[2J\e[H")

      result
    end
  end

  # --- Private helpers ---

  defp init_screen(module, opts) do
    if function_exported?(module, :init, 1) do
      module.init(opts)
    else
      {:ok, %{}}
    end
  end

  defp loop(module, state, input_pid) do
    # Render
    rendered = module.render(state)
    IO.write("\e[2J\e[H")
    IO.puts(rendered)
    IO.write(prompt())

    # Wait for input
    receive do
      {:input, line} ->
        handle_screen_input(module, line, state, input_pid)

      _other ->
        # Ignore unexpected messages
        loop(module, state, input_pid)
    end
  end

  defp handle_screen_input(module, line, state, input_pid) do
    trimmed = String.trim(line)

    # Built-in exit shortcuts
    case trimmed do
      ":q" ->
        :ok

      "" ->
        loop(module, state, input_pid)

      _ ->
        case module.handle_input(trimmed, state) do
          {:ok, new_state} ->
            loop(module, new_state, input_pid)

          {:done, result} ->
            {:ok, result}

          :exit ->
            :ok
        end
    end
  end

  defp input_reader_loop(parent_pid) do
    case IO.read(:line) do
      :eof ->
        send(parent_pid, {:input, ":q"})

      {:error, _} ->
        send(parent_pid, {:input, ":q"})

      line when is_binary(line) ->
        send(parent_pid, {:input, line})
        input_reader_loop(parent_pid)
    end
  end

  defp prompt do
    IO.ANSI.format([:bright, :green, "❯ ", :reset]) |> to_string()
  end
end
