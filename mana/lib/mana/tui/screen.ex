defmodule Mana.TUI.Screen do
  @moduledoc """
  Behaviour for TUI screens that run inside the main application loop.

  Each screen is a module that implements `render/1` and `handle_input/2`,
  optionally `init/1` for one-time setup. The `Mana.TUI.ScreenRunner` drives
  the render → input → handle cycle.

  ## Callbacks

    * `init/1`        – (optional) initialise screen state; defaults to `{:ok, %{}}`
    * `render/1`      – render current state to IO-compatible output
    * `handle_input/2`– process one line of user input

  ## Return values for `handle_input/2`

    * `{:ok, state}`  – continue the loop with updated state
    * `{:done, term}` – exit the screen, returning `term` to the caller
    * `:exit`         – exit the screen, returning `:ok`

  ## Example

      defmodule Mana.TUI.Screens.Echo do
        @behaviour Mana.TUI.Screen

        @impl true
        def render(state) do
          count = Map.get(state, :count, 0)
          \"Echo screen – \#{count} messages (type :q to quit)\"
        end

        @impl true
        def handle_input(\\":q\", _state), do: :exit
        def handle_input(line, state) do
          IO.puts(\"You said: \#{line}\")
          {:ok, Map.update(state, :count, 1, &(&1 + 1))}
        end
      end
  """

  @type state :: map()
  @type input :: String.t()

  @doc """
  Initialise screen state. Called once before the first render.
  Returns `{:ok, state}` on success or `{:error, reason}` to abort.
  """
  @callback init(opts :: keyword()) :: {:ok, state()} | {:error, term()}

  @doc """
  Render the current state to IO-compatible output (string or iodata).
  Called each loop iteration before waiting for input.
  """
  @callback render(state :: state()) :: IO.chardata()

  @doc """
  Handle one line of user input.

  Returns:
    * `{:ok, new_state}` – continue the loop
    * `{:done, result}`  – exit the screen, returning `result`
    * `:exit`            – exit the screen, returning `:ok`
  """
  @callback handle_input(input :: input(), state :: state()) ::
              {:ok, state()} | {:done, term()} | :exit

  @optional_callbacks [init: 1]
end
