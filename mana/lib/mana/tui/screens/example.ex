defmodule Mana.TUI.Screens.Example do
  @moduledoc """
  Example screen that validates the `Mana.TUI.Screen` behaviour.

  A simple echo screen that counts lines and demonstrates all
  three `handle_input/2` return values.

  Run it manually:

      iex> Mana.TUI.ScreenRunner.run(Mana.TUI.Screens.Example)

  Commands:
    * `:q` or `quit` – exit the screen
    * `count`        – show how many lines were entered
    * `reset`        – reset the counter to zero
    * anything else  – echo it back and increment the counter
  """

  @behaviour Mana.TUI.Screen

  @impl true
  def init(_opts) do
    {:ok, %{count: 0, last: nil}}
  end

  @impl true
  def render(state) do
    """
    #{IO.ANSI.format([:bright, :cyan, "✦ Example Screen", :reset]) |> to_string()}
    #{IO.ANSI.format([:faint, String.duplicate("─", 40), :reset]) |> to_string()}

      Lines entered: #{state.count}
      Last input:    #{state.last || "(none)"}

    #{IO.ANSI.format([:faint, "Commands: :q to quit • count • reset", :reset]) |> to_string()}
    """
  end

  @impl true
  def handle_input("quit", _state), do: :exit

  def handle_input("count", state) do
    IO.puts(IO.ANSI.format([:yellow, "  Count: #{state.count}", :reset]) |> to_string())
    {:ok, state}
  end

  def handle_input("reset", state) do
    {:ok, %{state | count: 0, last: "reset"}}
  end

  def handle_input(input, state) do
    IO.puts(IO.ANSI.format([:faint, "  Echo: #{input}", :reset]) |> to_string())
    {:ok, %{count: state.count + 1, last: input}}
  end
end
