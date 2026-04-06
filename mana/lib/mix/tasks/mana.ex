defmodule Mix.Tasks.Mana do
  use Mix.Task

  alias Mana.TUI.App

  @shortdoc "Start the Mana TUI"

  @moduledoc """
  Starts the Mana terminal user interface.

  ## Usage

      mix mana [options]

  ## Options

    --model MODEL    Set the default model
    --session ID     Load a specific session
    --headless       Run without TUI (for containers / non-TTY environments)
  """

  @impl Mix.Task
  def run(args) do
    # Start the application
    Mix.Task.run("app.start")

    # Parse args
    opts = parse_args(args)

    # Set headless env if requested
    if Keyword.get(opts, :headless) do
      System.put_env("MANA_HEADLESS", "true")
    end

    # Start TUI (will auto-detect headless environment)
    App.start(opts)
  end

  defp parse_args(args) do
    {opts, _, _} =
      OptionParser.parse(args,
        strict: [model: :string, session: :string, headless: :boolean]
      )

    opts
  end
end
